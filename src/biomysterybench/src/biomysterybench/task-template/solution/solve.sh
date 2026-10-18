#!/bin/bash
set -euo pipefail
if [ ! -f /solution/answer.txt ]; then
    echo 'No released reference solution. Generate with --oracle-dir containing independently solved answers.' >&2
    exit 1
fi
cp /solution/answer.txt /workspace/answer.txt
cp /solution/report.md /workspace/report.md
