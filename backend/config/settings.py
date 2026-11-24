import os
from dotenv import load_dotenv
from pathlib import Path

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent


ROOT = BASE_DIR.parent
load_dotenv(ROOT / ".env")
SECRET_KEY = os.environ["DJANGO_SECRET_KEY"]
DEBUG = os.getenv("DJANGO_DEBUG", "0") == "1"
ALLOWED_HOSTS = os.getenv("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")
CSRF_TRUSTED_ORIGINS = [s for s in os.getenv("DJANGO_CSRF_TRUSTED_ORIGINS", "").split(",") if s]
if DEBUG:
    CSRF_TRUSTED_ORIGINS = list(dict.fromkeys([
        *CSRF_TRUSTED_ORIGINS,
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]))
SESSION_COOKIE_SECURE = CSRF_COOKIE_SECURE = not DEBUG
SESSION_COOKIE_AGE = 14 * 24 * 3600
CSRF_FAILURE_VIEW = "config.api.csrf_failure"
HISTORICO = os.getenv("AIRBYTE_HISTORICO", "rmcab-v1")
MODEL_PATH = Path(os.getenv("AIRBYTE_MODEL_PATH") or ROOT / "modelo/air_byte_pm25_24h_historial.joblib")
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")
GOOGLE_REDIRECT_URI = os.getenv("GOOGLE_REDIRECT_URI", "http://localhost:5173/api/v1/auth/google/callback")
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:5173").rstrip("/")

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'aire', 'comunidad', 'cuentas',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'config.middleware.PaginasDeError',
]

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
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

WSGI_APPLICATION = 'config.wsgi.application'


# Database
# https://docs.djangoproject.com/en/6.1/ref/settings/#databases

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': os.getenv('PGDATABASE', 'airbyte'),
        'USER': os.getenv('PGUSER', 'airbyte'),
        'PASSWORD': os.getenv('PGPASSWORD', ''),
        'HOST': os.getenv('PGHOST', '127.0.0.1'),
        'PORT': os.getenv('PGPORT', '5432'),
    }
}


# Password validation
# https://docs.djangoproject.com/en/6.1/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]


# Internationalization
# https://docs.djangoproject.com/en/6.1/topics/i18n/

LANGUAGE_CODE = 'es-co'

TIME_ZONE = 'America/Bogota'

USE_I18N = True

USE_TZ = True


# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/6.1/howto/static-files/

STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
MEDIA_URL = '/media/'
MEDIA_ROOT = ROOT / 'media'


# Email
# https://docs.djangoproject.com/en/6.1/topics/email/#topic-email-configuration

MAILERS = {
    'default': {
        'BACKEND': 'django.core.mail.backends.console.EmailBackend',
    },
}

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "filters": {"oauth": {"()": "config.logging.OcultarConsultaOAuth"}},
    "formatters": {"django.server": {"format": "%(message)s"}},
    "handlers": {"servidor": {
        "class": "logging.StreamHandler",
        "filters": ["oauth"],
        "formatter": "django.server",
    }},
    "loggers": {"django.server": {"handlers": ["servidor"], "level": "INFO", "propagate": False}},
}
