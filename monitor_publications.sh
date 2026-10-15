#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
umask 077
if [[ -f .env ]]; then
    set -a
    source .env
    set +a
fi
exec .venv/bin/python monitor_publications.py "$@"
