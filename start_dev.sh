#!/bin/bash
# Start Django dev server + task worker together.
# Usage: ./start_dev.sh
# Stop everything: Ctrl+C

export DJANGO_DEBUG=1

# Load environment variables from .zshrc if OPENAI_API_KEY isn't already set
if [ -z "$OPENAI_API_KEY" ] && [ -f "$HOME/.zshrc" ]; then
    # Extract and export OPENAI_API_KEY from .zshrc without running interactive shell
    _key=$(grep -E '^\s*export OPENAI_API_KEY=' "$HOME/.zshrc" | tail -1 | sed 's/.*OPENAI_API_KEY=//' | tr -d '"'"'" | cut -d' ' -f1)
    if [ -n "$_key" ]; then
        export OPENAI_API_KEY="$_key"
    fi
fi

if [ -z "$OPENAI_API_KEY" ]; then
    echo "WARNING: OPENAI_API_KEY is not set — AI Swing Coach will not work."
    echo "         Add 'export OPENAI_API_KEY=sk-...' to your ~/.zshrc"
else
    echo "OPENAI_API_KEY loaded (${#OPENAI_API_KEY} chars)"
fi

cd "$(dirname "$0")"

# Make sure the output directory exists
mkdir -p media/output media/input media/thumbnails media/overlayed

echo "Running migrations..."
python manage.py migrate --run-syncdb 2>&1 | tail -5

echo ""
echo "Starting Django server on http://127.0.0.1:8000"
echo "Starting Django-Q worker (video processing)"
echo "Press Ctrl+C to stop both."
echo ""

# Run qcluster in the background, Django server in the foreground.
# When Ctrl+C hits the foreground process, the trap kills qcluster too.
python manage.py qcluster &
QCLUSTER_PID=$!

cleanup() {
    echo ""
    echo "Shutting down..."
    kill "$QCLUSTER_PID" 2>/dev/null
    exit 0
}
trap cleanup INT TERM

python manage.py runserver 8000

# If runserver exits normally, kill qcluster too
kill "$QCLUSTER_PID" 2>/dev/null
