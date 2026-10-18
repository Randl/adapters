#!/bin/bash
set -euo pipefail
if [ ! -f /solution/decompiled.c ]; then
    echo 'No upstream oracle. Generate with --oracle-dir containing independently reconstructed C.' >&2
    exit 1
fi
cp /solution/decompiled.c /workspace/decompiled.c
