# config/settings/production.py

import os
import dj_database_url
from .base import *

DEBUG = env.bool('DEBUG', default=False)
ALLOWED_HOSTS = env.list('ALLOWED_HOSTS', default=[])

# ================================================================
# PRODUCTION - Enable rate limiting
# ================================================================
# django-ratelimit's actual setting is RATELIMIT_ENABLE (no trailing "D").
RATELIMIT_ENABLE = True

# ================================================================
# SECURITY HEADERS
# ================================================================
SECURE_HSTS_SECONDS = env.int('SECURE_HSTS_SECONDS', default=31536000)
SECURE_HSTS_INCLUDE_SUBDOMAINS = env.bool('SECURE_HSTS_INCLUDE_SUBDOMAINS', default=True)
SECURE_HSTS_PRELOAD = env.bool('SECURE_HSTS_PRELOAD', default=True)
X_FRAME_OPTIONS = 'DENY'
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_BROWSER_XSS_FILTER = True
SECURE_SSL_REDIRECT = env.bool('SECURE_SSL_REDIRECT', default=True)
SESSION_COOKIE_SECURE = env.bool('SESSION_COOKIE_SECURE', default=True)
CSRF_COOKIE_SECURE = env.bool('CSRF_COOKIE_SECURE', default=True)
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')

# Cookie security
CSRF_COOKIE_HTTPONLY = True
SESSION_COOKIE_HTTPONLY = True
CSRF_COOKIE_SAMESITE = 'Lax'
SESSION_COOKIE_SAMESITE = 'Lax'

# Session security
SESSION_COOKIE_AGE = env.int('SESSION_COOKIE_AGE', default=86400)
SESSION_EXPIRE_AT_BROWSER_CLOSE = False

# Database
DATABASES = {
    'default': dj_database_url.config(
        default=env('DATABASE_URL', default=None),
        conn_max_age=60,
    )
}
if DATABASES['default'] is None:
    raise ValueError("DATABASE_URL environment variable is required for production.")

# Static files
MIDDLEWARE.insert(1, 'whitenoise.middleware.WhiteNoiseMiddleware')
STATICFILES_STORAGE = 'whitenoise.storage.CompressedManifestStaticFilesStorage'
STATIC_ROOT = BASE_DIR / 'staticfiles'
# Long-lived cache for hashed static assets, which is the safe CDN-friendly
# pattern for Cloudflare: file names change when content changes, so the cache
# can be aggressively reused without stale HTML concerns.
WHITENOISE_MAX_AGE = 31536000
WHITENOISE_IMMUTABLE_FILE_TEST = lambda path, url: 'static/' in url

# ================================================================
# EMAIL CONFIGURATION (Production)
# ================================================================
EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
EMAIL_HOST = env('EMAIL_HOST')
EMAIL_PORT = env.int('EMAIL_PORT', default=587)
EMAIL_USE_TLS = env.bool('EMAIL_USE_TLS', default=True)
EMAIL_HOST_USER = env('EMAIL_HOST_USER')
EMAIL_HOST_PASSWORD = env('EMAIL_HOST_PASSWORD')
DEFAULT_FROM_EMAIL = env('DEFAULT_FROM_EMAIL')
EMAIL_TIMEOUT = 30

if not EMAIL_HOST_USER or not EMAIL_HOST_PASSWORD:
    raise ValueError("EMAIL_HOST_USER and EMAIL_HOST_PASSWORD are required for production.")

# Brevo API Key (for API-based sending fallback)
BREVO_API_KEY = env('BREVO_API_KEY', default='')

CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels_redis.core.RedisChannelLayer",
        "CONFIG": {
            "hosts": [os.environ.get("REDIS_URL", "redis://127.0.0.1:6379")],
        },
    },
}

CACHES = {
    'default': {
        'BACKEND': 'django_redis.cache.RedisCache',
        'LOCATION': env('REDIS_URL', default='redis://127.0.0.1:6379'),
        'OPTIONS': {
            'CLIENT_CLASS': 'django_redis.client.DefaultClient',
        }
    }
}

DEFAULT_FILE_STORAGE = 'cloudinary_storage.storage.MediaCloudinaryStorage'
CLOUDINARY_STORAGE = {
    'CLOUD_NAME': env('CLOUDINARY_CLOUD_NAME'),
    'API_KEY': env('CLOUDINARY_API_KEY'),
    'API_SECRET': env('CLOUDINARY_API_SECRET'),
}

CSRF_TRUSTED_ORIGINS = env.list('CSRF_TRUSTED_ORIGINS', default=[])