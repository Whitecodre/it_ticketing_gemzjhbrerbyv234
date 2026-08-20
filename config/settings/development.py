# config/settings/development.py

from .base import *

DEBUG = True
ALLOWED_HOSTS = ['localhost', '127.0.0.1', 'testserver']

# Rate limiting settings for development
# NOTE: django-ratelimit's actual setting is RATELIMIT_ENABLE (no trailing
# "D") — RATELIMIT_ENABLED was a no-op name mismatch, silently inert while
# the @ratelimit decorator itself was commented out on CustomLoginView.
RATELIMIT_ENABLE = False

# Channels Layer (Redis)
CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels.layers.InMemoryChannelLayer",
    },
}

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': env('DB_NAME', default='it_ticketing_dev'),
        'USER': env('DB_USER', default='postgres'),
        'PASSWORD': env('DB_PASSWORD', default='postgres'),
        'HOST': env('DB_HOST', default='localhost'),
        'PORT': env('DB_PORT', default='5432'),
    }
}

TEST_PUSH = True
STATICFILES_STORAGE = 'django.contrib.staticfiles.storage.StaticFilesStorage'

# ================================================================
# EMAIL CONFIGURATION
# ================================================================
# Try SMTP first (if credentials exist)
if env('EMAIL_HOST', default=None):
    EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
    EMAIL_HOST = env('EMAIL_HOST')
    EMAIL_PORT = env('EMAIL_PORT', default=587)
    EMAIL_USE_TLS = env('EMAIL_USE_TLS', default=True)
    EMAIL_HOST_USER = env('EMAIL_HOST_USER')
    EMAIL_HOST_PASSWORD = env('EMAIL_HOST_PASSWORD')   
    DEFAULT_FROM_EMAIL = env('DEFAULT_FROM_EMAIL')
    EMAIL_TIMEOUT = 10
else:
    EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'

# Brevo API Key (for API-based sending)
BREVO_API_KEY = env('BREVO_API_KEY', default='')

# ================================================================
# CACHE
# ================================================================
CACHES = {
    'default': {
        'BACKEND': 'django_redis.cache.RedisCache',
        'LOCATION': env('REDIS_URL', default='redis://localhost:6379'),
        'OPTIONS': {
            'CLIENT_CLASS': 'django_redis.client.DefaultClient',
        }
    }
}