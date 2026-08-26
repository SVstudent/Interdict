"""Test 11. No module under app/ may read the wall clock directly.

Every timestamp must come from the injected Clock, or `advance_clock` cannot move the system
four days forward and beat 5 becomes impossible. §15 lists retrofitting the Clock as an
anti-pattern precisely because this test is cheap now and expensive later.
"""
from __future__ import annotations

import ast
from pathlib import Path

APP = Path(__file__).resolve().parents[1] / "app"

# The single sanctioned call site: SystemClock itself has to read the wall clock somehow.
ALLOWED = {APP / "config.py"}

BANNED = {
    ("datetime", "now"),
    ("datetime", "utcnow"),
    ("datetime", "today"),
    ("time", "time"),
}


def _violations(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(), filename=str(path))
    found: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        owner = node.func.value
        name = owner.id if isinstance(owner, ast.Name) else getattr(owner, "attr", None)
        if (name, node.func.attr) in BANNED:
            found.append(f"{path.relative_to(APP.parent)}:{node.lineno} {name}.{node.func.attr}()")
    return found


def test_no_module_reads_the_wall_clock_directly():
    offenders: list[str] = []
    for path in sorted(APP.rglob("*.py")):
        if path in ALLOWED:
            continue
        offenders.extend(_violations(path))
    assert not offenders, "use the injected Clock instead:\n  " + "\n  ".join(offenders)


def test_the_allowlist_is_still_justified():
    """If config.py stops containing a wall-clock read, the allowlist entry must go too."""
    assert _violations(APP / "config.py"), (
        "config.py no longer reads the wall clock; remove it from ALLOWED"
    )
