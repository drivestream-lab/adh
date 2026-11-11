#!/usr/bin/env bash
# Progress monitor for Dev god INIT-REALWORLD-001 verify loop.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LOG="$ROOT/logs/verify-001-monitor.log"
BUZZ="${ORCH_BUZZ_BASE_URL:-http://localhost:8080}"
INIT="INIT-REALWORLD-001"
ENGG="engg-init-realworld-001"
DESIRED_RE='spec-draft|spec-pr-action|initiative-feasibility|spec-technical-review|technical-review-approval|spec-implementation-plan|coding-readiness|spec-merge|board-tickets-action'
LEGACY_RE='deps-acceptance|accept deps|Engg-Deps|verification.plan programme'

tick=0
while true; do
  tick=$((tick+1))
  ts=$(date -u +%Y-%m-%dT%H:%M:%SZ)
  {
    echo "===== TICK $tick $ts ====="
    echo "-- workers --"
    pgrep -lf 'adh_pe_worker|adh_dev_worker' || echo 'NO_WORKERS'
    echo "-- autonomy --"
    rg -n 'ADH_AUTONOMY_MODE' "$ROOT/.env" || true
    echo "-- redis work/baton --"
    docker exec adh-redis redis-cli --scan --pattern "*${INIT}*" 2>/dev/null | head -30 || true
    echo "-- ops tail --"
    curl -sf "$BUZZ/api/v1/buzz/rooms/realworld-ops/messages?limit=15" 2>/dev/null | python3 -c '
import sys,json
d=json.load(sys.stdin); items=d.get("items",d) if isinstance(d,dict) else d
for m in items[-12:]:
  b=(m.get("body") or "").replace("\n"," ")
  print(m.get("created_at","")[:19], m.get("identity_handle"),"|",b[:140])
' 2>/dev/null || echo 'ops_fetch_failed'
    echo "-- engg room --"
    curl -sf "$BUZZ/api/v1/buzz/rooms/$ENGG/messages?limit=15" 2>/dev/null | python3 -c '
import sys,json
d=json.load(sys.stdin); items=d.get("items",d) if isinstance(d,dict) else d
print("count", len(items))
for m in items[-12:]:
  b=(m.get("body") or "").replace("\n"," ")
  print(m.get("created_at","")[:19], m.get("identity_handle"),"|",b[:140])
' 2>/dev/null || echo 'engg_room_missing_or_empty'
    echo "-- task --"
    curl -sf "$BUZZ/api/v1/buzz/tenants/realworld/tasks/$INIT" 2>/dev/null | python3 -c '
import sys,json
t=json.load(sys.stdin)
print(t.get("task_id"), t.get("state"), t.get("task_room_slug"))
' 2>/dev/null || echo 'no_task'
    echo "-- log signals --"
    rg -n 'Handed|missing Impact|spec-draft|deps-acceptance|ERROR|Traceback|stall|god_halt|YAML|dev_outcome|board-tickets|Got it' \
      "$ROOT/logs/adh-pe-001-verify.log" "$ROOT/logs/adh-dev-001-verify.log" 2>/dev/null | tail -40 || true
    # classify — legacy only from engg room / current worker logs (ignore old ops traj)
    if curl -sf "$BUZZ/api/v1/buzz/rooms/$ENGG/messages?limit=40" 2>/dev/null | rg -q "$LEGACY_RE"; then
      echo "STATUS: LEGACY_DETECTED"
    elif rg -q "$LEGACY_RE" "$ROOT/logs/adh-dev-001-verify.log" 2>/dev/null; then
      echo "STATUS: LEGACY_DETECTED"
    elif curl -sf "$BUZZ/api/v1/buzz/rooms/$ENGG/messages?limit=40" 2>/dev/null | rg -q "$DESIRED_RE"; then
      echo "STATUS: YAML_PROGRESS"
    elif curl -sf "$BUZZ/api/v1/buzz/rooms/realworld-ops/messages?limit=20" 2>/dev/null | rg -q 'Handed \*\*INIT-REALWORLD-001\*\*'; then
      echo "STATUS: HANDOFF_DONE_WAIT_DEV"
    elif ! pgrep -f 'adh_dev_worker' >/dev/null; then
      echo "STATUS: DEV_DOWN"
    elif ! pgrep -f 'adh_pe_worker' >/dev/null; then
      echo "STATUS: PE_DOWN"
    else
      echo "STATUS: WAITING"
    fi
    echo
  } | tee -a "$LOG"
  sleep 45
done
