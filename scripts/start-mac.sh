#!/bin/bash
set -euo pipefail

cd "$(dirname "$0")/.."
export PATH="$PWD/.venv/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"

if [ ! -x .venv/bin/python ] || [ ! -f maho/web/index.html ]; then
  echo "Run bash scripts/setup-mac-no-admin.sh (no Homebrew needed) or bash scripts/setup-mac.sh first." >&2
  exit 1
fi

exec .venv/bin/python -m maho serve "$@"
