#!/usr/bin/env bash
# exit on error
set -o errexit

# mediapipe's C shared library links against libGLESv2 even for CPU-only inference.
# Install the OpenGL ES stubs so the library can load on headless servers.
apt-get install -y --no-install-recommends libgles2 libegl1 libegl-mesa0 2>/dev/null || true

pip install -r requirements.txt

python manage.py migrate
python manage.py collectstatic --noinput
python manage.py requeue_processing --all
