import os
from pathlib import Path
from dotenv import load_dotenv
from urllib.parse import urlparse, parse_qsl
from datetime import timedelta

# Load environment variables
load_dotenv()

# ----------------- BASE -----------------
BASE_DIR = Path(__file__).resolve().parent.parent

# ----------------- SECURITY -----------------
SECRET_KEY = os.getenv("SECRET_KEY")
DEBUG = os.getenv("DEBUG", "False") == "True"
ALLOWED_HOSTS = os.getenv("ALLOWED_HOSTS", "*").split(",")


# ----------------- APPLICATIONS -----------------
INSTALLED_APPS = [
    # Django apps
    # 'simpleui', 
    'daphne',
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',

    # Third-party apps
    'corsheaders',
    'django_filters',
    'rest_framework',
    'rest_framework_simplejwt',
    'rest_framework_simplejwt.token_blacklist',
    'django_celery_beat',
    'channels',
    'push_notifications',

    # Cloudinary Apps only when enabled
    'cloudinary',
    'cloudinary_storage',
    
    # Project apps
    'accounts',
    'venue_manager',
    'booking',
    "attendance",
    "payroll",
    "notification",
    "analysis",
    "wallet",
    "faq",
]

# ----------------- MIDDLEWARE -----------------
MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'corsheaders.middleware.CorsMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

# ----------------- CORS & CSRF -----------------
# =========================
# CORS
# =========================
CORS_ALLOW_ALL_ORIGINS = True
CORS_ALLOW_CREDENTIALS = True

CSRF_TRUSTED_ORIGINS = [
    "https://vaishnavimedicare.com",
    "https://valueoccasions.com",
    "https://168.144.213.88",
    "http://localhost:3000",
    "http://localhost:5173",
]
]

SECURE_PROXY_SSL_HEADER = (
    "HTTP_X_FORWARDED_PROTO",
    "https",
)

SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True

SESSION_COOKIE_SAMESITE = "None"
CSRF_COOKIE_SAMESITE = "None"

# JavaScript needs to read the CSRF cookie
CSRF_COOKIE_HTTPONLY = False

# ----------------- WSGI, ASGI & URLS -----------------
ROOT_URLCONF = 'vaishnavi_backend.urls'
WSGI_APPLICATION = 'vaishnavi_backend.wsgi.application'
ASGI_APPLICATION = "vaishnavi_backend.asgi.application"

# ----------------- Notification, Redis, Celery and channel -----------------

REDIS_URL = os.getenv("vaishnavi_REDIS_URL", "redis://127.0.0.1:6379")

# Separate DBs to avoid key collisions
REDIS_CACHE_URL    = f"{REDIS_URL}/0"
REDIS_BROKER_URL   = f"{REDIS_URL}/1"
REDIS_RESULTS_URL  = f"{REDIS_URL}/2"
REDIS_CHANNELS_URL = f"{REDIS_URL}/3"

CACHES = {
    "default": {
        "BACKEND": "django_redis.cache.RedisCache",
        "LOCATION": REDIS_CACHE_URL,
        "OPTIONS": {
            "CLIENT_CLASS": "django_redis.client.DefaultClient",
        },
    }
}

CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels_redis.core.RedisChannelLayer",
        "CONFIG": {
            "hosts": [REDIS_CHANNELS_URL],
        },
    },
}

CELERY_BROKER_URL     = REDIS_BROKER_URL
CELERY_RESULT_BACKEND = REDIS_RESULTS_URL

CELERY_BEAT_SCHEDULER = "django_celery_beat.schedulers:DatabaseScheduler"

CELERY_ACCEPT_CONTENT    = ["json"]
CELERY_TASK_SERIALIZER   = "json"
CELERY_RESULT_SERIALIZER = "json"

PUSH_NOTIFICATIONS_SETTINGS = {
    'FCM_API_KEY': 'your-firebase-key',   # Android
    'APNS_CERTIFICATE': '/path/to/cert',  # iOS
}
 

# ----------------- TEMPLATES -----------------
TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

# ----------------- AUTH -----------------
AUTH_USER_MODEL = 'accounts.CustomUser'

AUTHENTICATION_BACKENDS = [
    'accounts.authentication.EmailMobileAuthBackend',
    'django.contrib.auth.backends.ModelBackend',
]

# ----------------- PASSWORD VALIDATION -----------------
if not DEBUG:
    AUTH_PASSWORD_VALIDATORS = [
        {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
        {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
        {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
        {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
    ]

# ----------------- INTERNATIONALIZATION -----------------
LANGUAGE_CODE = 'en-in'
TIME_ZONE = 'Asia/Kolkata'
USE_I18N = True
USE_TZ = True

# ----------------- REST FRAMEWORK & JWT -----------------
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': (
        'rest_framework_simplejwt.authentication.JWTAuthentication',
        "rest_framework.authentication.SessionAuthentication",
        "rest_framework.authentication.BasicAuthentication",
        "rest_framework.authentication.TokenAuthentication",

    ),
    'DEFAULT_PERMISSION_CLASSES': (
        'rest_framework.permissions.IsAuthenticated',
    ),
    'DEFAULT_PAGINATION_CLASS':(
        'vaishnavi_backend.pagination.StandardResultsSetPagination'
    ),
    'DEFAULT_FILTER_BACKENDS': (
        'django_filters.rest_framework.DjangoFilterBackend',
        'rest_framework.filters.SearchFilter',
        'rest_framework.filters.OrderingFilter',
    )

}

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=int(os.getenv("ACCESS_TOKEN_LIFETIME_MINUTES", 5))),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=int(os.getenv("REFRESH_TOKEN_LIFETIME_DAYS", 1))),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
    "AUTH_HEADER_TYPES": ("Bearer",),
}

# ----------------- DEFAULT PRIMARY KEY -----------------
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# ----------------- FILE STORAGE (Cloudinary) -----------------

CLOUDINARY_STORAGE = {
    "CLOUD_NAME": os.getenv("CLOUDINARY_CLOUD_NAME"),
    "API_KEY": os.getenv("CLOUDINARY_API_KEY"),
    "API_SECRET": os.getenv("CLOUDINARY_API_SECRET"),    
}

STORAGES = {
    "default": {
        "BACKEND": "cloudinary_storage.storage.RawMediaCloudinaryStorage"
    },
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
    },
}
    
RAZORPAY_KEY_ID     = os.getenv('RAZORPAY_KEY_ID')
RAZORPAY_KEY_SECRET = os.getenv('RAZORPAY_KEY_SECRET')
# ----------------- DATABASE -----------------

tmpPostgres = urlparse(os.getenv("DATABASE_URL"))
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': tmpPostgres.path.replace('/', ''),
        'USER': tmpPostgres.username,
        'PASSWORD': tmpPostgres.password,
        'HOST': tmpPostgres.hostname,
        'PORT': 5432,
        'OPTIONS': dict(parse_qsl(tmpPostgres.query)),
    }
}


# ----------------- Email & Twilio config -----------------
EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'

EMAIL_HOST = os.getenv('EMAIL_HOST')
EMAIL_PORT = os.getenv('EMAIL_PORT')
EMAIL_USE_TLS = os.getenv('EMAIL_USE_TLS')

EMAIL_HOST_USER = os.getenv('EMAIL_HOST_USER')
EMAIL_HOST_PASSWORD = os.getenv('EMAIL_HOST_PASSWORD')

DEFAULT_FROM_EMAIL = EMAIL_HOST_USER


TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_PHONE_NUMBER = os.getenv("TWILIO_PHONE_NUMBER")
TWILIO_WHATSAPP_NUMBER = os.getenv("TWILIO_WHATSAPP_NUMBER")

# ----------------- STATIC FILES -----------------
STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'

#-------------------MEDIA FILES -------------------
MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'