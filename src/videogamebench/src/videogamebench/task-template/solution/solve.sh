#!/bin/bash
set -euo pipefail
if [ ! -f /solution/actions.json ]; then
    echo 'No released winning replay. Generate with --oracle-dir containing validated action traces.' >&2
    exit 1
fi
cp /solution/actions.json /workspace/actions.json
