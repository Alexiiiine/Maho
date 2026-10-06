#!/bin/bash
set -euo pipefail

cd "$(dirname "$0")/.."
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"

if [ ! -x .venv/bin/python ] || [ ! -f maho/web/index.html ]; then
  echo "Run bash scripts/setup-mac.sh first to install Maho and build its browser interface." >&2
  exit 1
fi

exec .venv/bin/python -m maho serve "$@"
