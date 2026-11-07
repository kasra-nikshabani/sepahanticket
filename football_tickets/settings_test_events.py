"""Isolated event tests: real migrations, no production DB, Redis or gateway."""
from .settings import *  # noqa: F401,F403

DATABASES = {'default': {'ENGINE': 'django.db.backends.sqlite3', 'NAME': ':memory:'}}
CACHES = {'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}}
SESSION_ENGINE = 'django.contrib.sessions.backends.db'
SECURE_SSL_REDIRECT = False
ALLOWED_HOSTS = ['testserver', 'localhost', '127.0.0.1']
PASSWORD_HASHERS = ['django.contrib.auth.hashers.MD5PasswordHasher']
MIDDLEWARE = [item for item in MIDDLEWARE if item not in (
    'accounts.middleware.GeoAccessMiddleware', 'accounts.middleware.VisitTrackingMiddleware',
    'accounts.middleware.KeycloakBearerAuthenticationMiddleware',
)]
STORAGES = {
    'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
    'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
}

# Retain regression coverage for historic sports workflows.
CULTURAL_PLATFORM = False
