import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

# Use environment variable for SECRET_KEY in production (fallback to a dev-only key)
# Prefer setting DJANGO_SECRET_KEY in your environment rather than committing a secret here.
SECRET_KEY = os.environ.get('DJANGO_SECRET_KEY') or os.environ.get('SECRET_KEY') or 'dev-only-insecure-secret-change-me'

# Use environment variable for DEBUG (default False for safety; set DJANGO_DEBUG=1 locally)
DEBUG = os.environ.get('DJANGO_DEBUG', '0') in ('1', 'True', 'true')

# Allowed hosts — must be explicitly configured in production
_allowed_hosts_env = os.environ.get('ALLOWED_HOSTS', '')
ALLOWED_HOSTS = _allowed_hosts_env.split(',') if _allowed_hosts_env else (['localhost', '127.0.0.1'] if DEBUG else [])

_csrf_origins_env = os.environ.get('CSRF_TRUSTED_ORIGINS', '')
CSRF_TRUSTED_ORIGINS = _csrf_origins_env.split(',') if _csrf_origins_env else (['http://localhost', 'http://127.0.0.1'] if DEBUG else [])

# Security hardening toggles (applied only when DEBUG is False)
if not DEBUG:
    # Redirect all non-HTTPS requests to HTTPS
    SECURE_SSL_REDIRECT = os.environ.get('SECURE_SSL_REDIRECT', 'True') in ('1', 'True', 'true')
    # HTTP Strict Transport Security (HSTS)
    SECURE_HSTS_SECONDS = int(os.environ.get('SECURE_HSTS_SECONDS', '31536000'))
    SECURE_HSTS_INCLUDE_SUBDOMAINS = os.environ.get('SECURE_HSTS_INCLUDE_SUBDOMAINS', 'True') in ('1', 'True', 'true')
    SECURE_HSTS_PRELOAD = os.environ.get('SECURE_HSTS_PRELOAD', 'False') in ('1', 'True', 'true')
    # Secure-only cookies
    SESSION_COOKIE_SECURE = os.environ.get('SESSION_COOKIE_SECURE', 'True') in ('1', 'True', 'true')
    CSRF_COOKIE_SECURE = os.environ.get('CSRF_COOKIE_SECURE', 'True') in ('1', 'True', 'true')
    # Set this if you're behind a proxy that sets X-Forwarded-Proto
    # Example: SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
    proxy_header = os.environ.get('SECURE_PROXY_SSL_HEADER')
    if proxy_header:
        try:
            parts = proxy_header.split(',')
            if len(parts) == 2:
                SECURE_PROXY_SSL_HEADER = (parts[0].strip(), parts[1].strip())
        except Exception:
            pass
# Use BigAutoField by default to silence warnings about AutoField
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django_q',
    'storages',
    'shots',
    'accounts.apps.AccountsConfig',
    'widget_tweaks',
]

# Django-Q task queue — uses the existing database as broker (no Redis required).
# Run the worker with: python manage.py qcluster
Q_CLUSTER = {
    'name': 'caddie_baddie',
    'workers': int(os.environ.get('Q_WORKERS', '2')),
    'timeout': 900,        # 15 min hard limit per task (long videos need time)
    'retry': 1080,         # re-queue if not acknowledged within 18 min
    'queue_limit': 50,     # don't pile up more than 50 pending tasks
    'bulk': 10,
    'orm': 'default',      # use Django's default database as broker
    'save_limit': 500,     # keep last 500 task results for the admin dashboard
    'max_attempts': 2,     # retry a failed task once before giving up
    'ack_failures': True,  # acknowledge (remove from queue) even on failure
    'catch_up': False,     # don't replay missed scheduled tasks on restart
}

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'golf_caddie.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.template.context_processors.media',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'golf_caddie.wsgi.application'

# Database - use PostgreSQL on Render, SQLite locally
DATABASE_URL = os.environ.get('DATABASE_URL')
if DATABASE_URL:
    import dj_database_url
    DATABASES = {
        'default': dj_database_url.config(conn_max_age=600, ssl_require=False)
    }
else:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': BASE_DIR / 'db.sqlite3',
        }
    }

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_TZ = True

STATIC_URL = '/static/'
STATICFILES_DIRS = [BASE_DIR / 'static']
STATIC_ROOT = BASE_DIR / 'staticfiles'

# Configure WhiteNoise for static file serving in production
STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
    },
}

# ── Media storage — S3 in production, local in development ─────────────────
AWS_STORAGE_BUCKET_NAME = os.environ.get('AWS_STORAGE_BUCKET_NAME', '')
AWS_S3_REGION_NAME = os.environ.get('AWS_S3_REGION_NAME', 'us-east-2')
AWS_S3_CUSTOM_DOMAIN = f'{AWS_STORAGE_BUCKET_NAME}.s3.amazonaws.com'
AWS_DEFAULT_ACL = None          # bucket policy handles public read; ACLs disabled on new buckets
AWS_S3_OBJECT_PARAMETERS = {'CacheControl': 'max-age=86400'}
AWS_QUERYSTRING_AUTH = False

if AWS_STORAGE_BUCKET_NAME:
    STORAGES['default'] = {'BACKEND': 'storages.backends.s3boto3.S3Boto3Storage'}
    MEDIA_URL = f'https://{AWS_S3_CUSTOM_DOMAIN}/'
    MEDIA_ROOT = ''
else:
    MEDIA_URL = '/media/'
    MEDIA_ROOT = BASE_DIR / 'media'

# File Upload Settings - Optimized for iPhone/Mobile Videos
# iPhone videos can be large (100MB-1GB+), so we increase the limits
DATA_UPLOAD_MAX_MEMORY_SIZE = 524288000  # 500 MB (in bytes)
FILE_UPLOAD_MAX_MEMORY_SIZE = 524288000  # 500 MB (in bytes)


# Custom user model for email authentication
AUTH_USER_MODEL = 'accounts.CustomUser'

# ── Email (AWS SES via SMTP) ────────────────────────────────────────────────
# Set these environment variables in production:
#   AWS_SES_SMTP_USER      → SMTP username from IAM → SES SMTP credentials
#   AWS_SES_SMTP_PASSWORD  → SMTP password from IAM → SES SMTP credentials
#   AWS_SES_REGION         → e.g. us-east-1 (default)
#   DEFAULT_FROM_EMAIL     → e.g. noreply@yourdomain.com
_ses_region = os.environ.get('AWS_SES_REGION', 'us-east-1')
EMAIL_HOST = f'email-smtp.{_ses_region}.amazonaws.com'
EMAIL_PORT = 587
EMAIL_USE_TLS = True
EMAIL_HOST_USER = os.environ.get('AWS_SES_SMTP_USER', '')
EMAIL_HOST_PASSWORD = os.environ.get('AWS_SES_SMTP_PASSWORD', '')
DEFAULT_FROM_EMAIL = os.environ.get('DEFAULT_FROM_EMAIL', 'noreply@caddiebadie.com')
SERVER_EMAIL = DEFAULT_FROM_EMAIL

# Use console backend locally when SES credentials are not set
if EMAIL_HOST_USER:
    EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
else:
    EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'

# Password reset uses Django's built-in auth views (already wired via django.contrib.auth.urls)
LOGIN_URL = '/accounts/login/'
LOGIN_REDIRECT_URL = '/'

# Authentication backend for email login
AUTHENTICATION_BACKENDS = [
    'django.contrib.auth.backends.ModelBackend',
]

# Mapbox token used to fetch static map images when a local overlay isn't present.
# You can also override this at runtime with the MAPBOX_TOKEN environment variable.
MAPBOX_TOKEN = 'pk.eyJ1IjoibGR1Z2dzIiwiYSI6ImNtZ3d2bzVybjBsNGkya3ByaGY5MXA1MGIifQ.OVODkq1EaazsvaXtyeFE4A'
