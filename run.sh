#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
if [[ -x .venv/bin/python ]]; then
  runtime=.venv/bin/python
else
  printf '%s\n' 'Create an environment first: python3 -m venv .venv && .venv/bin/pip install -e .'
  exit 1
fi
exec "$runtime" -m mx700_studio "$@"
