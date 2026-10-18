#!/bin/bash
set -euo pipefail
mkdir -p /logs/verifier
rm -f /logs/verifier/reward.json /logs/verifier/reward.txt
python /tests/verify.py
