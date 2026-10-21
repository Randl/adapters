#!/bin/bash
set -euo pipefail
if [ ! -f /solution/actions.json ]; then
    echo 'Supply a candidate gameplay trace with --oracle-dir; no winning trace is bundled.' >&2
    exit 1
fi
python /opt/game/play.py --replay /solution/actions.json
