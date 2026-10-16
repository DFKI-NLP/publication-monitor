#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
for interpreter in python3.13 python3.14; do
    if command -v "$interpreter" >/dev/null 2>&1; then
        exec "$interpreter" setup_monitor.py "$@"
    fi
done
printf '%s\n' 'Install Python 3.13 or 3.14 with venv support, then run ./setup.sh again.' >&2
exit 1
