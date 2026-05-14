#!/usr/bin/env bash
# exit on error
set -o errexit

# Install OpenGL ES / EGL libraries needed by mediapipe's C shared library.
# apt-get is attempted first; if the library is still missing after that,
# create_gl_stubs.py compiles minimal no-op stubs from source via gcc.
echo "=== Installing OpenGL ES stubs for mediapipe ==="
apt-get install -y --no-install-recommends libgles2 libegl1 2>&1
echo "=== Verifying libGLESv2 availability ==="
ldconfig -p | grep GLES || echo "libGLESv2 not in ldconfig cache"
python3 -c "import ctypes; ctypes.CDLL('libGLESv2.so.2'); print('BUILD CHECK: libGLESv2.so.2 OK')" 2>&1 || echo "BUILD CHECK: libGLESv2.so.2 NOT loadable — will compile stub at runtime"
python3 scripts/create_gl_stubs.py 2>&1 || true

pip install -r requirements.txt

python manage.py migrate
python manage.py collectstatic --noinput
python manage.py requeue_processing --all
