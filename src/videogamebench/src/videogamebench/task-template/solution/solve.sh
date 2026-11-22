#!/bin/bash
set -euo pipefail
if [ ! -f /solution/actions.json ]; then
    echo 'Supply a candidate gameplay trace with --oracle-dir; no winning trace is bundled.' >&2
    exit 1
fi
args=(--replay /solution/actions.json)
if [ -f /solution/checks.json ]; then
    args+=(--replay-timing recorded --visual-checks /solution/checks.json
        --check-log /logs/agent/visual-checks/checks.jsonl
        --screen /logs/agent/visual-checks/final.png)
else
    timing=$(python -c 'import json; from pathlib import Path; trace = json.loads(Path("/solution/actions.json").read_text()); print("recorded" if isinstance(trace, dict) and trace.get("mode") == "realtime" else "immediate")')
    args+=(--replay-timing "$timing")
fi
# Explicit arguments can override timing, scheduling and lateness limits.
exec python /opt/game/play.py "${args[@]}" "$@"
