import os
from pathlib import Path
import dj_database_url

BASE_DIR = Path(__file__).resolve().parent.parent

# Use environment variable for SECRET_KEY in production
SECRET_KEY = os.environ.get('SECRET_KEY', 'replace-this-with-a-secure-key-for-production')

# Use environment variable for DEBUG
DEBUG = os.environ.get('DEBUG', 'True') == 'True'

# Allow connections from Render domain, localhost, and 127.0.0.1
ALLOWED_HOSTS = [
    "caddie-baddie-1.onrender.com",
    "localhost",
    "127.0.0.1",
    "24.5.99.14"
]

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
if os.environ.get('DATABASE_URL'):
    DATABASES = {
        'default': dj_database_url.parse(os.environ.get('DATABASE_URL'))
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

# File Upload Settings - Optimized for iPhone/Mobile Videos
# iPhone videos can be large (100MB-1GB+), so we increase the limits
DATA_UPLOAD_MAX_MEMORY_SIZE = 524288000  # 500 MB (in bytes)
FILE_UPLOAD_MAX_MEMORY_SIZE = 524288000  # 500 MB (in bytes)

# Mapbox token used to fetch static map images when a local overlay isn't present.
# You can also override this at runtime with the MAPBOX_TOKEN environment variable.
MAPBOX_TOKEN = 'pk.eyJ1IjoibGR1Z2dzIiwiYSI6ImNtZ3d2bzVybjBsNGkya3ByaGY5MXA1MGIifQ.OVODkq1EaazsvaXtyeFE4A'
