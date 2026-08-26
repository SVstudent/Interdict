#!/bin/bash
# One-time recording of every scenario into fixtures/replay_cache.json.
# Deliberately slow: Vertex limits requests per minute and the fan-out is bursty, so we pace
# between scenarios rather than relying on retry backoff, which costs far more wall-clock.
set -u
API=http://localhost:8077
PY=./.venv/bin/python
PACE=${PACE:-75}

report () { $PY -c "
import json,sys
try:
    d=json.load(sys.stdin)
except Exception:
    print('  non-JSON response'); raise SystemExit
if 'detail' in d: print('  ERROR:', str(d['detail'])[:160]); raise SystemExit
print(f\"  -> {d.get('outcome') or d.get('state')}  {d.get('elapsed_ms')}ms\")"; }

echo "recording into fixtures/replay_cache.json (pace ${PACE}s between scenarios)"
curl -s -X POST "$API/api/demo/reset" > /dev/null

for S in S1 S2 S3; do
  echo "[$S]"
  curl -s -X POST "$API/api/demo/inject_scenario/$S" -m 600 | report
  echo "   cached entries: $($PY -c "
import json,pathlib
p=pathlib.Path('fixtures/replay_cache.json')
print(len(json.loads(p.read_text())['entries']) if p.exists() else 0)")"
  sleep "$PACE"
done

# S4 is S3 four days later with the vendor confirming.
echo "[S4 — advance clock, vendor returns the callback]"
curl -s -X POST "$API/api/demo/advance_clock" -H 'Content-Type: application/json' -d '{"days":4}' > /dev/null
curl -s -X POST "$API/api/demo/inject_scenario/S4" -m 600 | report
sleep "$PACE"

echo "[S5 — crash and resume]"
curl -s -X POST "$API/api/demo/inject_scenario/S5" -m 600 | report

echo
echo "final cache size: $($PY -c "
import json,pathlib
p=pathlib.Path('fixtures/replay_cache.json')
print(len(json.loads(p.read_text())['entries']) if p.exists() else 0)") entries"
