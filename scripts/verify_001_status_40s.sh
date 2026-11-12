#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BUZZ="${ORCH_BUZZ_BASE_URL:-http://localhost:8080}"
INIT=INIT-REALWORLD-001
ENGG=engg-init-realworld-001
while true; do
  ts=$(date -u +%H:%M:%SZ)
  workers=$(pgrep -lf 'adh_dev_worker|adh_pe_worker' 2>/dev/null | wc -l | tr -d ' ')
  sess=$(docker exec adh-redis redis-cli GET "adh:agent:work:realworld:adh.dev:$INIT" 2>/dev/null || true)
  stage=$(python3 -c 'import json,sys; t=sys.stdin.read().strip()
print("none" if not t else json.loads(t).get("stage","?"))' <<<"$sess")
  awaiting=$(python3 -c 'import json,sys; t=sys.stdin.read().strip()
print("-" if not t else (json.loads(t).get("awaiting") or "-"))' <<<"$sess")
  last=$(curl -sf "$BUZZ/api/v1/buzz/rooms/$ENGG/messages?limit=8" 2>/dev/null | python3 -c '
import sys,json
items=(json.load(sys.stdin).get("items") or [])
if not items: print("(no engg msgs)"); raise SystemExit
b=(items[-1].get("body") or "").replace("\n"," ")
print(b[:110])' 2>/dev/null || echo "(engg unavailable)")
  task=$(curl -sf "$BUZZ/api/v1/buzz/tenants/realworld/tasks/$INIT" 2>/dev/null | python3 -c 'import sys,json; t=json.load(sys.stdin); print(t.get("state","?"))' 2>/dev/null || echo "?")
  cursor=$(rg -n 'Spawning Cursor CLI|Cursor CLI exited|Cursor CLI still running|ERROR|Traceback|stall|dev_outcome' "$ROOT/logs/adh-dev-001-verify.log" 2>/dev/null | tail -1 | sed 's/^[^:]*://' | cut -c1-90 || echo "-")
  echo "STATUS40 $ts workers=$workers task=$task stage=$stage awaiting=$awaiting | engg: $last | log: $cursor"
  sleep 40
done
