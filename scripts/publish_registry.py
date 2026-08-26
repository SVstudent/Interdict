"""Publish the Interdict fleet to the real GEAP Agent Registry.

Metadata only — no compute is provisioned, so this carries no fixed cost. Agent Registry lives at
`locations/global`; every regional endpoint returns "AgentService not supported in this location"
(DECISIONS D-002a).

Run: ./.venv/bin/python scripts/publish_registry.py [--delete]
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.config import Settings          # noqa: E402
from app.platform.catalog import full_catalog  # noqa: E402

LOCATION = "global"
HOST = "https://aiplatform.googleapis.com/v1beta1"


def token() -> str:
    import google.auth
    import google.auth.transport.requests

    creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
    creds.refresh(google.auth.transport.requests.Request())
    return creds.token


def agent_id(catalog_id: str) -> str:
    """`interdict.registry-check` -> `interdict-registry-check`. Resource IDs disallow dots."""
    return catalog_id.replace(".", "-")


def to_agent_body(entry) -> dict:
    """Map our catalog entry onto the GEAP Agent resource.

    The resource is deliberately sparse (id/name/description/system_instruction/tools/metadata),
    so the governance detail a procurement reviewer needs — owner, department, data
    classification, granted and denied scopes, changelog — goes into `metadata` where it stays
    queryable rather than being flattened into prose.
    """
    return {
        "id": agent_id(entry.agent_id),
        "name": entry.display_name,
        "description": entry.description,
        "metadata": {
            "catalog_id": entry.agent_id,
            "version": entry.version,
            "owner": entry.owner,
            "department": entry.department,
            "data_classification": entry.data_classification,
            "granted_scopes": ",".join(entry.granted_scopes),
            "denied_scopes": ",".join(entry.denied_scopes),
            "used_by": ",".join(entry.used_by),
            "changelog": json.dumps(entry.changelog),
            "fleet": entry.agent_id.split(".", 1)[0],
        },
    }


def main() -> int:
    settings = Settings()
    project = settings.GCP_PROJECT_ID
    if not project:
        print("GCP_PROJECT_ID is not set")
        return 1

    base = f"{HOST}/projects/{project}/locations/{LOCATION}/agents"
    headers = {"Authorization": f"Bearer {token()}", "Content-Type": "application/json"}
    delete = "--delete" in sys.argv

    with httpx.Client(timeout=60) as client:
        if delete:
            existing = client.get(base, headers=headers).json().get("agents", [])
            for a in existing:
                name = a.get("name", "")
                r = client.delete(f"{HOST}/{name}", headers=headers)
                print(f"  DELETE {name.rsplit('/', 1)[-1]}: HTTP {r.status_code}")
            return 0

        print(f"Publishing to projects/{project}/locations/{LOCATION}/agents\n")
        ok = 0
        for entry in full_catalog():
            body = to_agent_body(entry)
            r = client.post(base, headers=headers, json=body)
            if r.status_code in (200, 201):
                ok += 1
                print(f"  ✓ {body['id']:<30} v{entry.version:<8} {entry.department}")
            elif r.status_code == 409 or "ALREADY_EXISTS" in r.text:
                # Idempotent: patch the existing entry instead.
                r2 = client.patch(f"{base}/{body['id']}", headers=headers, json=body)
                state = "updated" if r2.status_code == 200 else f"HTTP {r2.status_code}"
                ok += r2.status_code == 200
                print(f"  ~ {body['id']:<30} v{entry.version:<8} {state}")
            else:
                msg = r.json().get("error", {}).get("message", r.text)[:150]
                print(f"  ✗ {body['id']:<30} HTTP {r.status_code}  {msg}")

        print(f"\n{ok}/{len(full_catalog())} published")

        listed = client.get(base, headers=headers).json().get("agents", [])
        print(f"registry now lists {len(listed)} agent(s)")
        for a in listed:
            md = a.get("metadata") or {}
            print(f"  {a.get('id', a.get('name','').rsplit('/',1)[-1]):<30} "
                  f"v{md.get('version','?'):<8} {md.get('department','?')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
