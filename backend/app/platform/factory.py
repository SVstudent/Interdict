"""Platform assembly. One switch chooses local or GEAP for the whole surface."""
from __future__ import annotations

from dataclasses import dataclass

from ..config import PlatformBackend, Settings
from ..store.base import Repository
from .armor import ArmorPort, GeapArmor, LocalArmor
from .catalog import full_catalog
from .exchange import ExchangePort, LocalExchange
from .gateway import GatewayPort, GeapGateway, LocalGateway
from .memory import GeapMemory, LocalMemory, MemoryPort
from .precedent import LocalPrecedent, PrecedentPort
from .recall import LocalRecall, RecallPort
from .registry import GeapRegistry, LocalRegistry, RegistryPort
from .runtime import GeapRuntime, LocalRuntime, RuntimePort
from .telemetry import GeapTelemetry, LocalTelemetry, Telemetry


@dataclass
class Platform:
    registry: RegistryPort
    runtime: RuntimePort
    memory: MemoryPort
    armor: ArmorPort
    gateway: GatewayPort
    telemetry: Telemetry
    recall: RecallPort
    precedent: PrecedentPort
    exchange: ExchangePort
    backend: PlatformBackend

    @property
    def is_geap(self) -> bool:
        return self.backend is PlatformBackend.GEAP


def _build_armor(settings: Settings) -> ArmorPort:
    """Real Model Armor when configured, otherwise our own screening alone.

    GeapArmor runs OUR guardrail unconditionally and treats Model Armor as a second opinion. That
    ordering is deliberate: measured against the S2 poisoned artifact, Model Armor returned
    NO_MATCH_FOUND while our hidden-text screen caught the injection. A managed service that can
    miss must never be the only layer, and its unavailability must never mean an unscreened
    artifact reaches an agent.
    """
    if settings.USE_MODEL_ARMOR and settings.GCP_PROJECT_ID:
        return GeapArmor(
            settings.GCP_PROJECT_ID,
            settings.MODEL_ARMOR_LOCATION,
            settings.MODEL_ARMOR_TEMPLATE,
        )
    return LocalArmor()


def build_platform(settings: Settings, repo: Repository) -> Platform:
    if settings.PLATFORM_BACKEND is PlatformBackend.GEAP:
        if not settings.GCP_PROJECT_ID:
            raise RuntimeError(
                "PLATFORM_BACKEND=geap requires GCP_PROJECT_ID. Refusing to start half-bound: "
                "a demo that silently falls back to local impls is the fakery §15 forbids."
            )
        project = settings.GCP_PROJECT_ID
        return Platform(
            registry=GeapRegistry(project, settings.GEAP_REGISTRY_LOCATION),
            runtime=GeapRuntime(project, settings.GEAP_RUNTIME_LOCATION),
            memory=GeapMemory(project, settings.GEAP_RUNTIME_LOCATION, "interdict-fleet"),
            armor=GeapArmor(project, settings.GEAP_RUNTIME_LOCATION, "interdict-inbound"),
            gateway=GeapGateway(project, settings.GEAP_RUNTIME_LOCATION, "interdict-gw"),
            telemetry=GeapTelemetry(project),
            # Fingerprints are additionally journalled through sessions.appendEvent by the
            # orchestrator, so the threat memory is auditable per case either way.
            recall=LocalRecall(),
            # Precedent goes through the Repository rather than a platform service: it is a
            # record of what a named human decided, and losing it to a restart would mean
            # asking them the same question twice.
            precedent=LocalPrecedent(repo),
            exchange=LocalExchange(),
            backend=PlatformBackend.GEAP,
        )
    return Platform(
        registry=LocalRegistry(seed=full_catalog()),
        runtime=LocalRuntime(),
        memory=LocalMemory(),
        armor=_build_armor(settings),
        gateway=LocalGateway(),
        telemetry=LocalTelemetry(),
        recall=LocalRecall(),
        precedent=LocalPrecedent(repo),
        exchange=LocalExchange(),
        backend=PlatformBackend.LOCAL,
    )
