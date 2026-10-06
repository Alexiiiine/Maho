#!/bin/bash
set -euo pipefail

cd "$(dirname "$0")/.."

if [ "$(uname -s)" != "Darwin" ]; then
  echo "This setup script is for macOS. See README.md for Windows setup." >&2
  exit 1
fi

if ! command -v brew >/dev/null 2>&1; then
  for candidate in /opt/homebrew/bin/brew /usr/local/bin/brew; do
    if [ -x "$candidate" ]; then
      export PATH="$(dirname "$candidate"):$PATH"
      break
    fi
  done
fi
if ! command -v brew >/dev/null 2>&1; then
  echo "Install Homebrew using the instructions at https://brew.sh, then run this script again." >&2
  exit 1
fi

export PATH="$(brew --prefix)/bin:$(brew --prefix)/sbin:$PATH"
echo "Installing Python, FFmpeg, and Node.js with Homebrew..."
brew install python@3.13 ffmpeg node@24
export PATH="$(brew --prefix node@24)/bin:$PATH"

if [ ! -d .venv ]; then
  "$(brew --prefix)/bin/python3.13" -m venv .venv
fi
if [ ! -x .venv/bin/python ]; then
  echo "The existing .venv is not a Mac environment. Rename it, then rerun setup; virtual environments cannot be copied between operating systems." >&2
  exit 1
fi
.venv/bin/python -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else "Python 3.11+ is required. Rename .venv and rerun setup.")'
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -e .
npm --prefix frontend ci
npm --prefix frontend run build
ffprobe -version >/dev/null
encoders="$(ffmpeg -hide_banner -encoders 2>/dev/null)"
if [[ "$encoders" != *libx264* ]]; then
  echo "FFmpeg needs the libx264 encoder. Reinstall Homebrew FFmpeg before running Maho." >&2
  exit 1
fi

if [ -t 0 ]; then
  for service in assemblyai openai; do
    if ! .venv/bin/python - "$service" <<'PY'
import sys
from maho.credentials import get_key
try:
    get_key(sys.argv[1])
except RuntimeError:
    sys.exit(1)
PY
    then
      .venv/bin/python -m maho set-key --service "$service"
    fi
  done
  .venv/bin/python -m maho doctor
else
  echo "Save your keys using .venv/bin/maho set-key --service assemblyai and --service openai."
  echo "Then check access with .venv/bin/maho doctor."
fi

echo "Setup complete. Start Maho with: bash scripts/start-mac.sh"
