import os
from pathlib import Path
from dotenv import load_dotenv
from django.contrib.messages import constants as messages

BASE_DIR = Path(__file__).resolve().parent.parent

load_dotenv(BASE_DIR / '.env')

SECRET_KEY = os.getenv('SECRET_KEY', 'change-me')
# DEBUG = os.getenv('DEBUG', 'False') == 'True'

CSRF_TRUSTED_ORIGINS = [
    'http://localhost:8000',
    'http://127.0.0.1:8000',
    'http://93.126.18.49',
    'http://ticket.sepahansc.com',  # اگر دامنه دارید
    'https://ticket.sepahansc.com',
]
DEBUG = False
ALLOWED_HOSTS = os.getenv('ALLOWED_HOSTS', '127.0.0.1,localhost').split(',')

# nginx به‌عنوان reverse proxy، SSL رو خودش terminate می‌کنه و این هدر رو
# ست می‌کنه (proxy_set_header X-Forwarded-Proto $scheme;) -- بدون این،
# جنگو هیچ‌وقت request.is_secure() رو True نمی‌بینه چون خودِ اتصال
# nginx<->gunicorn روی http هست.
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')

# settings.py
# ===== تنظیمات سشن =====
# مقدار واقعی SESSION_COOKIE_AGE/SESSION_SAVE_EVERY_REQUEST پایین‌تر (کنار
# SESSION_ENGINE) نهایی است -- این‌جا فقط تنظیمات مربوط به کوکی سشن هستند.
SESSION_COOKIE_SECURE = True
SESSION_EXPIRE_AT_BROWSER_CLOSE = False
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = 'Lax'
CSRF_COOKIE_SECURE = True
# شکست CSRF برای درخواست‌های fetch/AJAX باید JSON برگرداند، نه صفحه‌ی HTML
# پیش‌فرض جنگو -- وگرنه response.json() سمت جاوااسکریپت با خطای
# "Unexpected token '<'" می‌شکند. جزئیات در football_tickets/csrf.py
CSRF_FAILURE_VIEW = 'football_tickets.csrf.csrf_failure'

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
    'accounts.middleware.GeoAccessMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'accounts.middleware.VisitTrackingMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    # "django.middleware.cache.UpdateCacheMiddleware",
    # "django.middleware.cache.FetchFromCacheMiddleware",
]

ROOT_URLCONF = 'football_tickets.urls'

# settings.py
TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [os.path.join(BASE_DIR, 'templates')],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',  # ← این باید باشد
                'django.contrib.auth.context_processors.auth',  # ← این باید باشد
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
        # نگه داشتن اتصال بین درخواست‌ها (کاهش overhead در ترافیک بالا)
        'CONN_MAX_AGE': int(os.getenv('DB_CONN_MAX_AGE', '60')),
        'OPTIONS': {
            'connect_timeout': 5,
        },
    }
}

REDIS_URL = os.getenv('REDIS_URL', 'redis://127.0.0.1:6379/1')

CACHES = {
    'default': {
        'BACKEND': 'django_redis.cache.RedisCache',
        'LOCATION': REDIS_URL,
        'OPTIONS': {
            'CLIENT_CLASS': 'django_redis.client.DefaultClient',
            # جلوگیری از timeout طولانی زیر فشار
            'SOCKET_CONNECT_TIMEOUT': 2,
            'SOCKET_TIMEOUT': 2,
        },
        'KEY_PREFIX': 'sepahan',
    }
}

# Session روی Redis — حیاتی برای ترافیک بالا (جلوگیری از قفل جدول django_session)
SESSION_ENGINE = 'django.contrib.sessions.backends.cache'
SESSION_CACHE_ALIAS = 'default'
# کاربر مجموعاً ۳۰ دقیقه بعد از ورود لاگین می‌ماند (نه ۳۰ دقیقه‌ی بی‌فعالیت)؛
# چون SESSION_SAVE_EVERY_REQUEST خاموش است، این انقضا با هر درخواست تمدید
# نمی‌شود -- دقیقاً همان چیزی که خواسته شده: پایان‌یافتن نشست، فارغ از فعالیت کاربر.
SESSION_COOKIE_AGE = 60 * 30  # ۳۰ دقیقه
SESSION_SAVE_EVERY_REQUEST = False

SEAT_RESERVATION_TIMEOUT = int(os.getenv('SEAT_RESERVATION_TIMEOUT', '600'))

# فرم‌های تیک‌باکس گروهی (مثلاً دانلود دسته‌جمعی PDF بلیط‌های کانون هواداران)
# می‌توانند هزاران فیلد ticket_ids در یک POST داشته باشند -- پیش‌فرض جنگو
# (۱۰۰۰ فیلد) با آن‌ها 400 Bad Request برمی‌گرداند.
DATA_UPLOAD_MAX_NUMBER_FIELDS = int(os.getenv('DATA_UPLOAD_MAX_NUMBER_FIELDS', '20000'))

# بدون این تنظیم، جنگو خطاهای رخ‌نداده در ویوها (django.request) را فقط با
# ایمیل به ADMINS گزارش می‌کند -- که چون ADMINS/SMTP تنظیم نشده، این خطاها
# عملاً به‌جایی گزارش نمی‌شدند و ما موقع بررسی خطای 500 هیچ traceback ای
# در لاگ‌ها پیدا نمی‌کردیم. اینجا صراحتاً همه‌ی خطاها (django.request و بقیه‌ی
# logger های اپ) را به همان فایلی می‌فرستیم که از قبل هم دستی چک می‌شد.
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '{asctime} [{levelname}] {name}: {message}',
            'style': '{',
        },
    },
    'handlers': {
        'file': {
            'level': 'INFO',
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': os.path.join(BASE_DIR, 'logs', 'django-errors.log'),
            'maxBytes': 10 * 1024 * 1024,
            'backupCount': 5,
            'formatter': 'verbose',
        },
    },
    'root': {
        'handlers': ['file'],
        'level': 'INFO',
    },
    'loggers': {
        'django.request': {
            'handlers': ['file'],
            'level': 'ERROR',
            'propagate': False,
        },
        'django.security': {
            'handlers': ['file'],
            'level': 'WARNING',
            'propagate': False,
        },
    },
}

AUTH_PASSWORD_VALIDATORS = []

LANGUAGE_CODE = 'en-us'
# داده‌ها همچنان به‌صورت UTC در دیتابیس ذخیره می‌شوند (USE_TZ=True)؛ فقط
# نمایش تاریخ/ساعت (پنل ادمین، قالب‌ها و ...) با ساعت تهران محاسبه می‌شود.
TIME_ZONE = 'Asia/Tehran'
USE_I18N = True
USE_TZ = True

STATIC_URL = '/static/'
STATICFILES_DIRS = [os.path.join(BASE_DIR, 'static')]
STATIC_ROOT = os.path.join(BASE_DIR, 'staticfiles')

# با این storage، آدرس هر فایل استاتیک شامل هش محتوایش می‌شود
# (مثلاً script.a1b2c3d4.js) -- یعنی هر بار محتوای CSS/JS عوض بشود، آدرسش
# هم عوض می‌شود و مرورگر مجبور است نسخه‌ی جدید را بگیرد، حتی اگر نسخه‌ی
# قبلی را قبلاً به‌صورت طولانی‌مدت کش کرده باشد. تا امروز فایل‌های استاتیک
# فقط با ETag/Last-Modified سرو می‌شدند که همیشه revalidate درستی تضمین
# نمی‌کند (مثلاً با کش تهاجمی مرورگر یا CDN).
STORAGES = {
    'default': {
        'BACKEND': 'django.core.files.storage.FileSystemStorage',
    },
    'staticfiles': {
        'BACKEND': 'django.contrib.staticfiles.storage.ManifestStaticFilesStorage',
    },
}

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
SMS_IR_SANDBOX = os.getenv('SMS_IR_SANDBOX', 'False') == 'True'
SMS_IR_API_KEY = os.getenv('SMS_IR_API_KEY')
SMS_IR_SEND_URL = 'https://api.sms.ir/v1/send/verify'
SMS_IR_TEMPLATE_ID = 240573
SMS_IR_LINE_NUMBER = os.getenv('SMS_IR_LINE_NUMBER', '1000xxxx')
if not SMS_IR_API_KEY:
    raise ValueError("❌ SMS_IR_API_KEY not found in environment variables!")

FAN_API_USERNAME = os.getenv('FAN_API_USERNAME', '')
FAN_API_PASSWORD = os.getenv('FAN_API_PASSWORD', '')

# ===== گیت‌های اسکن بلیط =====
GATE_USERS = {
    'gate_class1': {'password': os.getenv('GATE_PASSWORD_CLASS1', ''), 'zone': 'class1'},
    'gate_home': {'password': os.getenv('GATE_PASSWORD_HOME', ''), 'zone': 'home'},
    'gate_away': {'password': os.getenv('GATE_PASSWORD_AWAY', ''), 'zone': 'away'},
    'gate_women': {'password': os.getenv('GATE_PASSWORD_WOMEN', ''), 'zone': 'women'},
    'gate_vip': {'password': os.getenv('GATE_PASSWORD_VIP', ''), 'zone': 'vip'},
}
GATE_TOKEN_TTL = int(os.getenv('GATE_TOKEN_TTL', str(12 * 60 * 60)))  # ۱۲ ساعت

ZIBAL_MERCHANT_ID = os.getenv('ZIBAL_MERCHANT_ID', 'zibal')
ZIBAL_SANDBOX = os.getenv('ZIBAL_SANDBOX', 'True') == 'True'
ZIBAL_CALLBACK_URL = os.getenv('ZIBAL_CALLBACK_URL', 'http://ticket.sepahansc.com/payment/verify/')

AUTHENTICATION_BACKENDS = [
    'accounts.backends.PhoneBackend',
    'django.contrib.auth.backends.ModelBackend',
]

LOGIN_URL = 'accounts:choose_login'
LOGIN_REDIRECT_URL = 'matches:home'
LOGOUT_REDIRECT_URL = 'accounts:choose_login'
OTP_ENABLED = True

