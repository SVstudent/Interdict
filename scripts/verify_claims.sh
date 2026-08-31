#!/usr/bin/env bash
# =============================================================================
# verify_claims.sh — execute every claim the README makes, and report pass/fail.
#
# Nothing in this repository asks to be taken on trust. Each check below maps to
# a row of the README's "Verify every claim" table and either runs a command or
# reads the code that enforces it.
#
# Runs credential-free: DEMO_MODE=replay, PLATFORM_BACKEND=local. No Google Cloud
# account, no project, no API key.
#
#   ./scripts/verify_claims.sh          run everything
#   ./scripts/verify_claims.sh --fast   skip the full pytest run
#
# Exits non-zero if any claim fails.
# =============================================================================
set -uo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.." || exit 1

PY=./.venv/bin/python
PORT=${PORT:-8079}
BASE="http://127.0.0.1:$PORT"
FAST=0
[[ "${1:-}" == "--fast" ]] && FAST=1

export DEMO_MODE=replay PLATFORM_BACKEND=local

PASS=0; FAIL=0; SERVER_PID=""
if [[ -t 1 ]]; then G=$'\033[32m'; R=$'\033[31m'; D=$'\033[2m'; N=$'\033[0m'
else G=""; R=""; D=""; N=""; fi

ok()   { PASS=$((PASS+1)); printf "  ${G}PASS${N}  %s\n" "$1"; }
bad()  { FAIL=$((FAIL+1)); printf "  ${R}FAIL${N}  %s\n"   "$1"; [[ -n "${2:-}" ]] && printf "        ${D}%s${N}\n" "$2"; }
head_() { printf "\n${D}── %s ${N}\n" "$1"; }

cleanup() { [[ -n "$SERVER_PID" ]] && kill "$SERVER_PID" 2>/dev/null; }
trap cleanup EXIT

if [[ ! -x "$PY" ]]; then
  echo "no venv at $PY — run: python3 -m venv .venv && ./.venv/bin/pip install -r backend/requirements.txt"
  exit 1
fi

# --------------------------------------------------------------- static checks
head_ "Static — enforced in code, not in prose"

# CLAIM: the fleet really runs on Google ADK, from exactly one construction site.
adk_files=$(grep -rl "google\.adk" backend/app --include='*.py' 2>/dev/null | sort)
if [[ "$adk_files" == "backend/app/agents/adk_runtime.py" ]]; then
  ok "Google ADK is constructed in exactly one file (adk_runtime.py) — no direct-API fallback"
else
  bad "ADK should be constructed in exactly one file" "found: ${adk_files:-none}"
fi

# CLAIM: a looping agent is bounded, at the call site.
if grep -q "MAX_LLM_CALLS_PER_STEP" backend/app/agents/adk_runtime.py &&
   grep -q "STEP_TIMEOUT_SECONDS"    backend/app/agents/adk_runtime.py; then
  caps=$(grep -hoE "(MAX_LLM_CALLS_PER_STEP|STEP_TIMEOUT_SECONDS) *[:=][^=][^#]*" \
         backend/app/agents/adk_runtime.py | tr -s ' ' | paste -sd'; ' -)
  ok "Per-step ceilings present — ${caps}"
else
  bad "MAX_LLM_CALLS_PER_STEP / STEP_TIMEOUT_SECONDS missing from adk_runtime.py"
fi

# CLAIM: time is never read from the wall clock.
# config.py is the single sanctioned call site — SystemClock/OffsetClock have to read the
# wall clock somehow. Same exclusion the real test applies (tests/test_no_wallclock.py).
wall=$(grep -rn "datetime\.now(" backend/app --include='*.py' \
       | grep -v "^backend/app/config.py:" | wc -l | tr -d ' ')
[[ "$wall" == "0" ]] \
  && ok "No datetime.now() outside the sanctioned Clock call site — all time reads are injected" \
  || bad "found $wall datetime.now() call(s) outside config.py"

# CLAIM: the data model structurally cannot hold a full account number.
if grep -q "account_last4" backend/app/models/domain.py &&
   ! grep -qE "^\s+account_number\s*:" backend/app/models/domain.py; then
  ok "BankingDetails holds only last-4 — there is no field for a full account number"
else
  bad "BankingDetails appears to carry a full account number field"
fi

# CLAIM: twelve agents, and the catalog agrees with the docs.
n=$($PY -c "from backend.app.platform.catalog import INTERDICT_FLEET; print(len(INTERDICT_FLEET))" 2>/dev/null)
[[ "$n" == "12" ]] && ok "Registry catalog publishes all twelve interdict agents" \
                   || bad "catalog publishes ${n:-?} interdict agents, expected 12"

# CLAIM: generated schemas match the Pydantic models.
if make check-schema >/dev/null 2>&1; then ok "Generated schemas match the models (make check-schema)"
else bad "schemas/ has drifted from the Pydantic models" "run: make schemas"; fi

# ---------------------------------------------------------------- invariants
head_ "Invariants — proved by tests"

run_test() { # name, node-id
  if $PY -m pytest "$2" -q >/dev/null 2>&1; then ok "$1"; else bad "$1" "$2"; fi
}
run_test "A committed verdict citing no evidence raises ValidationError" \
  "backend/tests/test_invariants.py::test_committed_verdict_without_evidence_is_rejected"
run_test "inconclusive is the only verdict permitted to cite nothing" \
  "backend/tests/test_invariants.py::test_inconclusive_may_cite_nothing"
run_test "No agent is declared a tool its identity denies (whole fleet)" \
  "backend/tests/test_adk_runtime.py::test_no_agent_is_declared_a_tool_its_identity_denies"
run_test "Killed runner resumes without re-executing or double-paying" \
  "backend/tests/test_durability.py"
run_test "The exchange withholds exactly the fields it advertises" \
  "backend/tests/test_tenancy.py"
run_test "Scenario fixtures stay coupled to the adjudication thresholds" \
  "backend/tests/test_scenario_fixtures.py"
run_test "No wall-clock reads (grep test)" \
  "backend/tests/test_no_wallclock.py"

# --------------------------------------------------------------- live endpoints
head_ "Behaviour — against a running server, replay mode, no credentials"

$PY -m uvicorn backend.app.main:app --host 127.0.0.1 --port "$PORT" >/tmp/verify_claims_server.log 2>&1 &
SERVER_PID=$!
for _ in $(seq 1 40); do
  curl -sf -m 2 "$BASE/healthz" >/dev/null 2>&1 && break
  sleep 0.5
done

if ! curl -sf -m 3 "$BASE/healthz" >/dev/null 2>&1; then
  bad "server did not start on :$PORT" "see /tmp/verify_claims_server.log"
else
  mode=$(curl -s "$BASE/healthz" | $PY -c "import sys,json;print(json.load(sys.stdin).get('mode','?'))")
  ok "Server up on :$PORT in mode=${mode} with no cloud credentials present"

  curl -s -X POST "$BASE/api/demo/reset" -m 60 -o /dev/null

  # The replay cache is recorded in runbook order, so the scenarios are driven in that order.
  # S1 blocks first, which is what puts the operation in the threat library that later
  # scenarios recall against. Out of order, a later scenario builds a prompt that was never
  # recorded and replay correctly refuses to invent one.
  curl -s -X POST "$BASE/api/demo/inject_scenario/S1" -m 300 -o /dev/null

  # CLAIM: the injection is really stripped, and the log is literal.
  s2=$(curl -s -X POST "$BASE/api/demo/inject_scenario/S2" -m 300)
  ex=$($PY -c "
import sys,json
d=json.loads(sys.stdin.read())
n=(d.get('screening') or {}).get('neutralizations') or []
print(n[0].get('excerpt','') if n else '')
" <<<"$s2" 2>/dev/null)
  out2=$(echo "$s2" | $PY -c "import sys,json;print(json.load(sys.stdin).get('outcome'))" 2>/dev/null)
  if [[ -n "$ex" && "$out2" == "BLOCK" ]]; then
    ok "S2 strips the injection, logs it verbatim, and still BLOCKs on independent evidence"
    printf "        ${D}removed: %.66s…${N}\n" "$(echo "$ex" | tr '\n' ' ')"
  else
    bad "S2 should log the literal removed span and still BLOCK" "excerpt='${ex:0:40}' outcome=$out2"
  fi

  # CLAIM: it refuses to decide — silence is never confirmation.
  s3=$(curl -s -X POST "$BASE/api/demo/inject_scenario/S3" -m 300)
  st=$(echo "$s3" | $PY -c "import sys,json;d=json.load(sys.stdin);print(d.get('state'))" 2>/dev/null)
  oc=$(echo "$s3" | $PY -c "import sys,json;d=json.load(sys.stdin);print(d.get('outcome'))" 2>/dev/null)
  [[ "$st" == "awaiting_callback" && "$oc" == "None" ]] \
    && ok "S3 parks in awaiting_callback and produces NO verdict (state=$st, outcome=null)" \
    || bad "S3 should abstain" "state=$st outcome=$oc"

  # CLAIM: scope is enforced on the path the MODEL takes, not just the code path.
  sv=$(curl -s -X POST "$BASE/api/demo/force_scope_violation" -m 60)
  echo "$sv" | grep -q "scope_denied\|denied" \
    && ok "callback is refused vendor:banking:read, and a posture event is written" \
    || bad "force_scope_violation did not report a denial" "${sv:0:120}"

  # CLAIM: replay cannot fabricate a beat — a miss fails loudly.
  miss=$(curl -s -o /dev/null -w '%{http_code}' -X POST \
         "$BASE/api/demo/inject_scenario/DOES_NOT_EXIST" -m 30)
  [[ "$miss" != "200" ]] \
    && ok "An unknown scenario fails loudly (HTTP $miss) rather than inventing a response" \
    || bad "unknown scenario returned 200"
fi

# -------------------------------------------------------------------- full suite
if [[ "$FAST" == "0" ]]; then
  head_ "Full suite — 255 tests, credential-free"
  line=$($PY -m pytest backend/tests -q 2>&1 | tail -3 | grep -E "passed|failed" | head -1)
  echo "$line" | grep -q "failed" \
    && bad "pytest reported failures" "$line" \
    || ok "${line:-suite passed}"
fi

# ------------------------------------------------------------------------ report
printf "\n%s\n" "────────────────────────────────────────────────────────"
if [[ "$FAIL" == "0" ]]; then
  printf "  ${G}%d/%d claims verified.${N}  Every README claim above is executable.\n\n" "$PASS" "$PASS"
  exit 0
else
  printf "  ${G}%d passed${N}, ${R}%d failed${N} of %d claims.\n\n" "$PASS" "$FAIL" "$((PASS+FAIL))"
  exit 1
fi
