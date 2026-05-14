from django.apps import AppConfig
import logging

logger = logging.getLogger(__name__)


class ShotsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'shots'

    def ready(self):
        try:
            from shots.ai.gl_utils import ensure_gl_stubs
            ensure_gl_stubs()
        except Exception as exc:
            logger.warning('gl_stubs: app startup hook failed: %s', exc)
