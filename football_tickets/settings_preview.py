"""Local demo only; uses a separate SQLite database and no production services."""
from .settings_test_events import *  # noqa: F401,F403

DEBUG = True
SHOW_DEV_OTP = True
EVENT_DEMO_MODE = True
DATABASES['default']['NAME'] = BASE_DIR / '.event-preview.sqlite3'
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False
MEDIA_ROOT = BASE_DIR / '.preview-media'
ZIBAL_MERCHANT_ID = 'zibal'
ZIBAL_SANDBOX = True
FANID_LOGIN_ENABLED = False
LOYALTY_POLL_SERVICE_TOKEN = ''
GATE_USERS = {}

CULTURAL_PLATFORM = True
PASSWORD_HASHERS = ['django.contrib.auth.hashers.PBKDF2PasswordHasher',
                    'django.contrib.auth.hashers.MD5PasswordHasher']
