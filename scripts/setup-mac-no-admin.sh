#!/bin/bash
set -euo pipefail

cd "$(dirname "$0")/.."
if [ "$(uname -s)" != "Darwin" ]; then
  echo "This setup script is for macOS." >&2
  exit 1
fi

case "$(uname -m)" in
  arm64) installer_arch=arm64; installer_sha256=d70bfa2e97afcda96927c9b9ca0e2316cb7750e4ce651c94388267cbe9588711 ;;
  x86_64) installer_arch=x86_64; installer_sha256=b00e7798658f92721a3ae2f6b9832695ffc6baf07758894d726268055359f6c5 ;;
  *) echo "Unsupported Mac architecture: $(uname -m)" >&2; exit 1 ;;
esac
mac_major="$(sw_vers -productVersion | cut -d. -f1)"
if [ "$mac_major" -lt 11 ]; then
  echo "This setup requires macOS 11 or newer." >&2
  exit 1
fi
if [ -d .venv ] && [ ! -d .venv/conda-meta ]; then
  echo "An existing .venv was created by another setup. Rename that folder, then rerun this script; your outputs and keys will be preserved." >&2
  exit 1
fi

# All installation paths are writable by the current user. No shell profile changes.
miniforge_prefix="$HOME/.maho/miniforge3"
if [ ! -x "$miniforge_prefix/bin/conda" ]; then
  mkdir -p .tools "$HOME/.maho"
  installer=".tools/Miniforge3-MacOSX-${installer_arch}.sh"
  echo "Downloading Miniforge into your own folders..."
  curl -fL --retry 3 -o "$installer" "https://github.com/conda-forge/miniforge/releases/download/26.7.2-0/Miniforge3-MacOSX-${installer_arch}.sh"
  actual_sha256="$(shasum -a 256 "$installer" | cut -d' ' -f1)"
  if [ "$actual_sha256" != "$installer_sha256" ]; then
    echo "Installer checksum did not match. Stopping before installation." >&2
    exit 1
  fi
  bash "$installer" -b -p "$miniforge_prefix"
fi

echo "Installing Python, FFmpeg, and Node.js without administrator access..."
if [ -d .venv/conda-meta ]; then
  conda_action=install
else
  conda_action=create
fi
"$miniforge_prefix/bin/conda" "$conda_action" --yes --prefix "$PWD/.venv" \
  --override-channels --channel conda-forge \
  "python=3.13" pip "ffmpeg=8.*=gpl_*" "nodejs>=22.12,<23"

export PATH="$PWD/.venv/bin:$PATH"
python -m pip install -e .
npm --prefix frontend ci
npm --prefix frontend run build
ffprobe -version >/dev/null
encoders="$(ffmpeg -hide_banner -encoders 2>/dev/null)"
if [[ "$encoders" != *libx264* ]]; then
  echo "The installed FFmpeg is missing libx264. Rerun setup to install the GPL build." >&2
  exit 1
fi

if [ -t 0 ]; then
  for service in assemblyai openai; do
    if ! python - "$service" <<'PY'
import sys
from maho.credentials import get_key
try:
    get_key(sys.argv[1])
except RuntimeError:
    sys.exit(1)
PY
    then
      python -m maho set-key --service "$service"
    fi
  done
  python -m maho doctor
else
  echo "Save your keys using .venv/bin/maho set-key --service assemblyai and --service openai."
  echo "Then check access with .venv/bin/maho doctor."
fi

echo "Setup complete. Start Maho with: bash scripts/start-mac.sh"
