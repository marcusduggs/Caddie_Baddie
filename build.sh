#!/usr/bin/env bash
# exit on error
set -o errexit

# Install OpenGL ES / EGL libraries needed by mediapipe's C shared library.
# apt-get is attempted first; if the library is still missing after that,
# create_gl_stubs.py compiles minimal no-op stubs from source via gcc.
apt-get install -y --no-install-recommends libgles2 libegl1 2>&1 | tail -5 || true
python3 scripts/create_gl_stubs.py || true

pip install -r requirements.txt

python manage.py migrate
python manage.py collectstatic --noinput
python manage.py requeue_processing --all
