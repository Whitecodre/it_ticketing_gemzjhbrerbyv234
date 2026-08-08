import os
import sys
from pathlib import Path
import environ

# Build paths
BASE_DIR = Path(__file__).resolve().parent.parent.parent  # it_ticketing/

env = environ.Env()
environ.Env.read_env(os.path.join(BASE_DIR, '.env'))

# Session security
SESSION_COOKIE_AGE = 86400  # 24 hours (in seconds)
SESSION_EXPIRE_AT_BROWSER_CLOSE = False  # Session persists after browser close
SESSION_COOKIE_HTTPONLY = True  # Prevent JavaScript access to session cookie
SESSION_COOKIE_SAMESITE = 'Lax'  # CSRF protection (Lax or Strict)
# In config/settings/base.py or development.py
SESSION_ENGINE = 'django.contrib.sessions.backends.db'  # Should be this

# CSRF settings
CSRF_COOKIE_HTTPONLY = True  # Prevent JavaScript access to CSRF cookie
CSRF_COOKIE_SAMESITE = 'Lax'  # CSRF protection
CSRF_TRUSTED_ORIGINS = ['https://*.yourdomain.com', 'http://localhost:8000']  # Update with your domain

# SECURITY WARNING: keep the secret key secret!
SECRET_KEY = env('SECRET_KEY')

# Application definition
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'channels',
    'webpush',
    'tinymce',
    
    # Tailwind Helper App
    'theme',

    # Lucide Icons
    'lucide',

    # Third-party
    'rest_framework',
    'tailwind',
    # Rate Limiter
    # 'django_ratelimit',

    # Our apps (make sure these names match apps.py)
    'apps.accounts',
    'apps.tickets.apps.TicketsConfig',
    'apps.knowledge_base',
    'apps.common',
    'apps.maintenance',
    'apps.form_builder',
    'apps.organogram',
]

# VAPID for Web Push Notifications
VAPID_PUBLIC_KEY = env('VAPID_PUBLIC_KEY', default='')
VAPID_PRIVATE_KEY = env('VAPID_PRIVATE_KEY', default='')
VAPID_CLAIM_EMAIL = env('VAPID_CLAIM_EMAIL', default='noreply@example.com')

# Rate limiting settings
RATELIMIT_VIEW = 'apps.common.views.ratelimit_handler'
RATELIMIT_USE_CACHE = 'default'

# ================================================================
# CACHE CONFIGURATION (for rate limiting)
# ================================================================
# Use Redis cache for rate limiting (supports atomic increment)
CACHES = {
    'default': {
        'BACKEND': 'django_redis.cache.RedisCache',
        'LOCATION': env('REDIS_URL', default='redis://localhost:6379'),
        'OPTIONS': {
            'CLIENT_CLASS': 'django_redis.client.DefaultClient',
            'CONNECTION_POOL_CLASS': 'redis.BlockingConnectionPool',
            'CONNECTION_POOL_CLASS_KWARGS': {
                'max_connections': 50,
                'timeout': 20,
            },
            'MAX_CONNECTIONS': 1000,
            'PICKLE_VERSION': -1,
        },
    }
}

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'apps.common.middleware.SecurityHeadersMiddleware',  
    'apps.common.middleware.ImpersonationMiddleware',
]

ROOT_URLCONF = 'config.urls'

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
                'apps.common.context_processors.vapid_keys',
                'apps.common.context_processors.impersonation_context',
                'apps.common.context_processors.client_settings',
                'apps.common.context_processors.active_role_context',
            ],
            'builtins':[
                "lucide.templatetags.lucide",
            ]
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'

# Password validation
AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator', 
        'OPTIONS': {
            'min_length': 8,
        }
     },
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

# Authentication backends
AUTHENTICATION_BACKENDS = [
    'apps.accounts.backends.EmailBackend',
]

# Internationalization
LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_TZ = True

# Static files (CSS, JavaScript, Images)
STATIC_URL = '/static/'
STATICFILES_DIRS = [BASE_DIR / 'static']
STATIC_ROOT = BASE_DIR / 'staticfiles'

MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

# Default primary key field type
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# Custom user model
AUTH_USER_MODEL = 'accounts.User'

# Tailwind
TAILWIND_APP_NAME = 'theme'

# Django REST Framework
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'rest_framework.authentication.SessionAuthentication',
    ],
    'DEFAULT_PERMISSION_CLASSES': [
        'rest_framework.permissions.IsAuthenticated',
    ],
    'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.PageNumberPagination',
    'PAGE_SIZE': 20,
}

ASGI_APPLICATION = "config.asgi.application"

# Email (console backend for development)
EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'

# ================================================================
# NPM BINARY PATH - Cross-platform
# ================================================================

# Option 1: Use environment variable with fallback
NPM_BIN_PATH = os.environ.get('NPM_BIN_PATH', 'npm')

# Option 2: Platform-specific paths (if Option 1 doesn't work)
# if sys.platform == 'win32':
#     NPM_BIN_PATH = 'npm.cmd'
# elif sys.platform == 'darwin':
#     NPM_BIN_PATH = '/opt/homebrew/bin/npm'  # macOS with Homebrew
# else:
#     NPM_BIN_PATH = '/usr/bin/npm'  # Linux

# Option 3: Let django-tailwind auto-detect (simplest)
NPM_BIN_PATH = 'npm'  # Works if npm is in system PATH

# ================================================================
# TINYMCE CONFIGURATION
# ================================================================

TINYMCE_DEFAULT_CONFIG = {
    "height": "500px",
    "width": "100%",
    "menubar": "file edit view insert format tools table help",
    "plugins": """
        advlist autolink lists link image charmap print preview anchor
        searchreplace visualblocks code fullscreen
        insertdatetime media table paste code help wordcount
        image imagetools
    """,
    "toolbar": """
        undo redo | bold italic underline strikethrough | 
        forecolor backcolor | alignleft aligncenter alignright alignjustify | 
        bullist numlist | outdent indent | 
        link image media | table | code | 
        removeformat | help
    """,
    "relative_urls": False,
    "remove_script_host": False,
    "convert_urls": True,
    "paste_as_text": False,
    "paste_data_images": True,  # Allow pasting images directly
    "image_advtab": True,
    "image_class_list": [
        {"title": "Responsive", "value": "img-fluid"},
        {"title": "Border", "value": "img-border"},
        {"title": "Rounded", "value": "img-rounded"},
    ],
    "style_formats": [
        {"title": "Paragraph", "block": "p"},
        {"title": "Heading 2", "block": "h2"},
        {"title": "Heading 3", "block": "h3"},
        {"title": "Heading 4", "block": "h4"},
        {"title": "Code Block", "block": "pre", "classes": "code-block"},
        {"title": "Note", "block": "div", "classes": "note"},
        {"title": "Warning", "block": "div", "classes": "warning"},
    ],
    "branding": False,
    "resize": True,
    "statusbar": True,
    "autosave_ask_before_unload": True,
    "autosave_interval": "30s",
    "autosave_prefix": "kb-autosave",
}

# TinyMCE file upload settings
TINYMCE_COMPRESSOR = True
TINYMCE_UPLOAD_PATH = 'kb_images/'  # Where images will be stored

# Authentication Redirects
LOGIN_URL = 'accounts:login'
LOGIN_REDIRECT_URL = 'dashboard'
LOGOUT_REDIRECT_URL = 'accounts:login'