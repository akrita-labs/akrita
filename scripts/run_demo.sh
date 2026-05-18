#!/usr/bin/env bash
# AKRITA — drive a single demo iteration against a running orchestrator.
# Usage:
#   ./scripts/run_demo.sh                # localhost:8000
#   ORCH=http://otherhost:8000 ./scripts/run_demo.sh
set -euo pipefail

ORCH="${ORCH:-http://localhost:8000}"

echo "▸ checking orchestrator at $ORCH ..."
for i in {1..30}; do
    if curl -sS -o /dev/null --max-time 1 "$ORCH/health"; then
        break
    fi
    [ "$i" = "30" ] && { echo "✗ orchestrator not responding after 30s"; exit 1; }
    sleep 1
done

echo "▸ orchestrator is up. Running demo sequence..."
curl -sS -X POST "$ORCH/demo/run" | python3 -m json.tool

echo ""
echo "▸ post-demo state:"
echo "  /state/balances:"
curl -sS "$ORCH/state/balances" | python3 -m json.tool

echo "  /state/fills (last 5):"
curl -sS "$ORCH/state/fills?limit=5" | python3 -m json.tool

echo ""
echo "▸ Dashboard: open $ORCH/ in a browser."
