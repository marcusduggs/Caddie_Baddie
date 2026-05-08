#!/bin/bash
# Start Django dev server + task worker together.
# Usage: ./start_dev.sh
# Stop everything: Ctrl+C

export DJANGO_DEBUG=1

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
