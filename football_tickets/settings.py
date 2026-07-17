import os
from pathlib import Path
from dotenv import load_dotenv
from django.contrib.messages import constants as messages

BASE_DIR = Path(__file__).resolve().parent.parent

load_dotenv(BASE_DIR / '.env')

SECRET_KEY = os.getenv('SECRET_KEY', 'change-me')
# DEBUG = os.getenv('DEBUG', 'False') == 'True'

DEBUG = True
ALLOWED_HOSTS = os.getenv('ALLOWED_HOSTS', '127.0.0.1,localhost').split(',')

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'accounts',
    'matches',
    'tickets',
    'payments',
    'crispy_forms',
    'wallet',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'football_tickets.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [os.path.join(BASE_DIR, 'templates')],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'accounts.context_processors.site_settings',
            ],
        },
    },
]

WSGI_APPLICATION = 'football_tickets.wsgi.application'

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': os.getenv('DB_NAME', 'sepahan_ticket'),
        'USER': os.getenv('DB_USER', 'sepahan_user'),
        'PASSWORD': os.getenv('DB_PASSWORD', 'kasra123'),
        'HOST': os.getenv('DB_HOST', '127.0.0.1'),
        'PORT': os.getenv('DB_PORT', '5432'),
    }
}

CACHES = {
    'default': {
        'BACKEND': 'django_redis.cache.RedisCache',
        'LOCATION': 'redis://127.0.0.1:6379/1',
        'OPTIONS': {
            'CLIENT_CLASS': 'django_redis.client.DefaultClient',
        }
    }
}

SEAT_RESERVATION_TIMEOUT = 600

AUTH_PASSWORD_VALIDATORS = []

LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_TZ = True

STATIC_URL = '/static/'
STATICFILES_DIRS = [os.path.join(BASE_DIR, 'static')]
STATIC_ROOT = os.path.join(BASE_DIR, 'staticfiles')

MEDIA_URL = '/media/'
MEDIA_ROOT = os.path.join(BASE_DIR, 'media')

AUTH_USER_MODEL = 'accounts.User'

PAYMENT_GATEWAY = {
    'sandbox': True,
    'merchant_id': 'your_merchant_id',
}

EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
EMAIL_HOST = os.getenv('EMAIL_HOST', 'smtp.gmail.com')
EMAIL_PORT = int(os.getenv('EMAIL_PORT', 587))
EMAIL_USE_TLS = os.getenv('EMAIL_USE_TLS', 'True') == 'True'
EMAIL_HOST_USER = os.getenv('EMAIL_HOST_USER', '')
EMAIL_HOST_PASSWORD = os.getenv('EMAIL_HOST_PASSWORD', '')

MESSAGE_TAGS = {
    messages.DEBUG: 'debug',
    messages.INFO: 'info',
    messages.SUCCESS: 'success',
    messages.WARNING: 'warning',
    messages.ERROR: 'danger',
}

SMS_IR_SANDBOX = False
SMS_IR_API_KEY = os.getenv('GvuGJ87XBIrAghd7OfA28vhxof9rlYBfvULTPBBhzb8TbXkw')
SMS_IR_SEND_URL = 'https://api.sms.ir/v1/send/verify'
SMS_IR_TEMPLATE_ID = int(os.getenv('SMS_IR_TEMPLATE_ID', 123456))
SMS_IR_LINE_NUMBER = os.getenv('SMS_IR_LINE_NUMBER', '1000xxxx')

ZIBAL_MERCHANT_ID = os.getenv('ZIBAL_MERCHANT_ID', 'zibal')
ZIBAL_SANDBOX = os.getenv('ZIBAL_SANDBOX', 'True') == 'True'
ZIBAL_CALLBACK_URL = os.getenv('ZIBAL_CALLBACK_URL', 'http://93.126.18.49/payment/verify/')

AUTHENTICATION_BACKENDS = [
    'accounts.backends.PhoneBackend',
    'django.contrib.auth.backends.ModelBackend',
]

LOGIN_URL = 'accounts:choose_login'
LOGIN_REDIRECT_URL = 'matches:home'
LOGOUT_REDIRECT_URL = 'accounts:choose_login'
OTP_ENABLED = True
