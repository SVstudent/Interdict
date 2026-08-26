# reference/inherited

Code carried out of the `untitled/` scaffold that is worth **reading** but is not part of the
build. It is outside `backend/app/` on purpose: these files do not import, do not run, and are
not covered by the test suite.

- `adjudicator.py` — the five adjudication rules, which were the one genuinely deterministic
  piece of the inherited fleet. Kept for the rule shapes only. Known defects, all documented in
  `context/DECISIONS.md` D-001: it consults a single global `challenge.survived` flag instead of
  per-finding rebuttals, its idempotency guard logs and then proceeds anyway, and it calls
  `datetime.now()` (which is why `test_no_wallclock.py` failed the moment it was added to the
  package). Rewritten properly in Phase 2 against `context/AGENTS.md`.
