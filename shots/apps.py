from django.apps import AppConfig
import logging

logger = logging.getLogger(__name__)


class ShotsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'shots'

    def ready(self):
        import ctypes
        try:
            ctypes.CDLL('libGLESv2.so.2')
            print('[startup] libGLESv2.so.2: already available on system', flush=True)
        except OSError:
            print('[startup] libGLESv2.so.2: not found — running ensure_gl_stubs()', flush=True)
            try:
                from shots.ai.gl_utils import ensure_gl_stubs
                ensure_gl_stubs()
            except Exception as exc:
                print(f'[startup] gl_stubs failed: {exc}', flush=True)
