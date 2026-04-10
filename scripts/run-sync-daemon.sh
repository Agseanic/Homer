#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INTERVAL="${MONITOR_SYNC_INTERVAL:-30}"

while true; do
  python3 "${SCRIPT_DIR}/collect_status.py"
  sleep "${INTERVAL}"
done
