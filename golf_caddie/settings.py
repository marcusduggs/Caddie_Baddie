import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

# Use environment variable for SECRET_KEY in production (fallback to a dev-only key)
# Prefer setting DJANGO_SECRET_KEY in your environment rather than committing a secret here.
SECRET_KEY = os.environ.get('DJANGO_SECRET_KEY') or os.environ.get('SECRET_KEY') or 'dev-only-insecure-secret-change-me'

# Use environment variable for DEBUG (default True for local development)
DEBUG = os.environ.get('DJANGO_DEBUG', '1') in ('1', 'True', 'true')

# Allowed hosts
# In development it's often convenient to allow all. In production set a comma-separated
# list via the ALLOWED_HOSTS environment variable (for example: "example.com,www.example.com").
if os.environ.get('ALLOWED_HOSTS'):
    ALLOWED_HOSTS = [h.strip() for h in os.environ.get('ALLOWED_HOSTS').split(',') if h.strip()]
else:
    # Default to permissive for local development. When DEBUG is False keep an empty
    # ALLOWED_HOSTS by default to avoid accidentally exposing the site; set the
    # environment variable in production to the allowed hostnames.
    ALLOWED_HOSTS = ['*'] if DEBUG else []

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
    'shots',
    'accounts.apps.AccountsConfig',
    'widget_tweaks',
]

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

AUTH_PASSWORD_VALIDATORS = []

LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_TZ = True

STATIC_URL = '/static/'
STATICFILES_DIRS = [BASE_DIR / 'static']
STATIC_ROOT = BASE_DIR / 'staticfiles'

# Note: static files storage is configured via the `STORAGES` mapping above.
# If you enable USE_S3 in production, update the STORAGES mapping to point
# at S3Boto3Storage (and install django-storages[boto3]).

# Configure WhiteNoise for static file serving in production
STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
    },
}

MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

# Minimal production logging: send warnings/errors to stdout so they are visible
# in systemd/journald or container logs. Adjust handlers/formatters as needed.
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'handlers': {
        'console': {'class': 'logging.StreamHandler'},
    },
    'root': {
        'handlers': ['console'],
        'level': 'WARNING' if not DEBUG else 'INFO',
    },
}

# File Upload Settings - Optimized for iPhone/Mobile Videos
# iPhone videos can be large (100MB-1GB+), so we increase the limits
DATA_UPLOAD_MAX_MEMORY_SIZE = 524288000  # 500 MB (in bytes)
FILE_UPLOAD_MAX_MEMORY_SIZE = 524288000  # 500 MB (in bytes)


# Custom user model for email authentication
AUTH_USER_MODEL = 'accounts.CustomUser'

# Authentication backend for email login
AUTHENTICATION_BACKENDS = [
    'django.contrib.auth.backends.ModelBackend',
]

# Mapbox token used to fetch static map images when a local overlay isn't present.
# DO NOT put secrets in source control. Provide MAPBOX_TOKEN via environment
# variables on the server (for example: export MAPBOX_TOKEN="pk..."), or
# configure your secret manager.
MAPBOX_TOKEN = os.environ.get('MAPBOX_TOKEN') or ''
