#!/bin/bash
set -euo pipefail
if [ ! -f /solution/answer.txt ]; then
    echo 'Missing reference assets. Generate with --oracle-dir (independent solutions or explicitly labeled GT fixtures).' >&2
    exit 1
fi
cp /solution/answer.txt /workspace/answer.txt
cp /solution/report.md /workspace/report.md
