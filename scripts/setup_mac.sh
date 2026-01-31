#!/usr/bin/env zsh
# Minimal setup script for macOS to create a venv and check/install prerequisites.
# Run: ./scripts/setup_mac.sh

set -euo pipefail
PROJECT_ROOT=$(cd "$(dirname "$0")/.." && pwd)
VENV_DIR="$PROJECT_ROOT/.venv-py311"
REQUIREMENTS="$PROJECT_ROOT/requirements.txt"

echo "Project root: $PROJECT_ROOT"

# Check python
if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 is not installed. Install via Homebrew: brew install python@3.11 or use pyenv." >&2
  exit 1
fi
PYTHON_VERSION=$(python3 -c 'import sys; print("%s.%s"%(sys.version_info.major, sys.version_info.minor))')
echo "Found python $PYTHON_VERSION"

# Create venv if missing
if [ ! -d "$VENV_DIR" ]; then
  echo "Creating venv at $VENV_DIR (uses python3)"
  python3 -m venv "$VENV_DIR"
fi

echo "To activate the venv run: source $VENV_DIR/bin/activate"

echo "Installing pip requirements (inside the venv):"
echo "  source $VENV_DIR/bin/activate && pip install --upgrade pip && pip install -r $REQUIREMENTS"

# Check ffmpeg
if command -v ffmpeg >/dev/null 2>&1; then
  FFMPEG_BIN=$(command -v ffmpeg)
  echo "ffmpeg found: $FFMPEG_BIN"
else
  echo "ffmpeg not found. Install with Homebrew: brew install ffmpeg" >&2
  echo "If you need drawtext (burned text), install freetype/fontconfig-enabled ffmpeg: brew install ffmpeg --with-freetype" >&2
fi

# Check ffprobe
if command -v ffprobe >/dev/null 2>&1; then
  echo "ffprobe found: $(command -v ffprobe)"
else
  echo "ffprobe not found. Install ffmpeg (ffprobe included) via Homebrew: brew install ffmpeg" >&2
fi

# Check drawtext support
if command -v ffmpeg >/dev/null 2>&1; then
  if ffmpeg -hide_banner -filters 2>&1 | grep -qi drawtext; then
    echo "ffmpeg supports drawtext (text burn-in)"
  else
    echo "ffmpeg does not appear to support 'drawtext'. Drawtext features will be skipped by the app." >&2
  fi
fi

# Mapbox token check
if [ -n "${MAPBOX_TOKEN-}" ] || python3 - <<'PY'
import os
print(bool(os.environ.get('MAPBOX_TOKEN')))
PY
then
  echo "MAPBOX_TOKEN is set in environment (map overlays will work)."
else
  echo "MAPBOX_TOKEN not set. Map overlays will be skipped unless you set MAPBOX_TOKEN in the environment or settings." >&2
fi

# Mediapipe/OpenCV guidance
cat <<'EOF'
Optional: install mediapipe+opencv in the venv to enable pose overlays (may be tricky on Apple Silicon).
Inside the venv try:
  pip install opencv-python
  pip install mediapipe
If that fails, pose overlays will be skipped and the processed video will still be generated.
EOF


echo "Setup helper finished. Next steps (recommended):"
echo "  1) source $VENV_DIR/bin/activate"
echo "  2) pip install -r $REQUIREMENTS"
echo "  3) set MAPBOX_TOKEN and any other env vars (e.g., export MAPBOX_TOKEN=... )"
echo "  4) run migrations: python manage.py migrate"
echo "  5) create superuser if needed: python manage.py createsuperuser"
echo "  6) run server: python manage.py runserver"
