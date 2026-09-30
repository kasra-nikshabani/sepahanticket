# accounts/keycloak_auth.py
"""
احراز هویت با Fan ID (Keycloak -- حساب مرکزی اپ سپاهان، ریپوی جدا sepapp).

دو مسیر، هر دو افزودنی؛ ورود فعلی (OTP برای کاربر عادی، رمز برای ادمین/VIP در
accounts/backends.py) دست‌نخورده می‌ماند:
  - Bearer (درخواست از اپ): فقط کاربری که از قبل به همین Fan ID متصل شده.
  - مرورگر (دکمه‌ی «ورود با Fan ID»): accounts/fanid_views.py.

چرا این‌جا هیچ کاربری ساخته یا متصل نمی‌شود: ثبت‌نام Fan ID مالکیت شماره‌ی
موبایل و کد ملی را تأیید نمی‌کند، فقط فرمتشان را. نسخه‌ی قبلی این ماژول حساب
موجود را با کد ملیِ داخل توکن پیدا و به همان Fan ID متصل می‌کرد -- یعنی هر کس با
کد ملی شخص دیگری در اپ ثبت‌نام می‌کرد، حساب او در این سایت (بلیط‌ها، کیف پول) را
تصاحب می‌کرد. حالا اتصال فقط یک‌بار و بعد از OTP به شماره‌ای انجام می‌شود که
همین سایت از قبل دارد (fanid_views.py).
"""
import hmac
import logging

import jwt
from django.conf import settings
from django.contrib.auth import get_user_model

logger = logging.getLogger(__name__)

User = get_user_model()

# اختلاف ساعت چندثانیه‌ای بین سرور Keycloak و این سرور نباید ورود را بشکند.
CLOCK_SKEW_SECONDS = 30

_jwks_client = None


class InvalidKeycloakToken(Exception):
    """توکن ظاهراً JWT است ولی معتبر نیست (صادرکننده/Client/Claim ناقص)."""


def _get_jwks_client():
    # Lazy + Module-level singleton: PyJWKClient خودش کلیدها را کش می‌کند
    # (lifespan=3600 ثانیه) پس هر درخواست به JWKS Endpoint واقعی کیکلوک زده
    # نمی‌شود، فقط وقتی Cache منقضی شده یا کلید ناشناخته‌ای دیده شود.
    global _jwks_client
    if _jwks_client is None:
        _jwks_client = jwt.PyJWKClient(settings.KEYCLOAK_JWKS_URL, cache_keys=True, lifespan=3600)
    return _jwks_client


def _require_identity_claims(claims):
    if not claims.get('national_code') or not claims.get('phone_number'):
        raise InvalidKeycloakToken('claim های national_code/phone_number در توکن نیستند')


def decode_keycloak_token(token):
    """
    Access Token مسیر Bearer: امضا/انقضا/صادرکننده و Client را بررسی می‌کند.

    Raises:
        jwt.PyJWTError / jwt.PyJWKClientError: اگر رشته اصلاً JWT معتبر نباشد
            یا امضا/انقضا/صادرکننده نادرست باشد (شامل توکن Opaque اسکنر گیت،
            که این‌جا فقط شکست می‌خورد و caller آن را جدا مدیریت می‌کند).
        InvalidKeycloakToken: توکن از نظر رمزنگاری معتبر است ولی از Client
            نامعتبر صادر شده یا Claim لازم (national_code/phone_number) را ندارد.
    """
    signing_key = _get_jwks_client().get_signing_key_from_jwt(token)
    claims = jwt.decode(
        token,
        signing_key.key,
        algorithms=['RS256'],
        issuer=settings.KEYCLOAK_ISSUER,
        leeway=CLOCK_SKEW_SECONDS,
        options={'require': ['exp', 'iat', 'sub']},
    )

    # فقط توکن‌های صادرشده برای Clientهای شناخته‌شده‌ی خودمان (azp) پذیرفته
    # می‌شوند -- یک اپ ناشناس داخل همان Realm نباید بتواند جای کاربر بنشیند،
    # حتی اگر امضایش هم از نظر رمزنگاری معتبر باشد.
    azp = claims.get('azp')
    if azp not in settings.KEYCLOAK_TRUSTED_CLIENTS:
        raise InvalidKeycloakToken(f'client غیرمجاز: {azp!r}')

    _require_identity_claims(claims)
    return claims


def decode_fanid_id_token(id_token, nonce):
    """
    ID Token ورود مرورگری (پاسخ Token Endpoint در fanid_views.py). علاوه بر
    امضا/صادرکننده، باید دقیقاً برای Client همین سایت صادر شده باشد (aud/azp)
    و nonce همان باشد که در شروع ورود در Session گذاشتیم -- وگرنه یک ID Token
    دزدیده‌شده/قدیمی قابل تزریق بود.
    """
    signing_key = _get_jwks_client().get_signing_key_from_jwt(id_token)
    claims = jwt.decode(
        id_token,
        signing_key.key,
        algorithms=['RS256'],
        issuer=settings.KEYCLOAK_ISSUER,
        audience=settings.FANID_CLIENT_ID,
        leeway=CLOCK_SKEW_SECONDS,
        options={'require': ['exp', 'iat', 'sub', 'nonce']},
    )

    azp = claims.get('azp', settings.FANID_CLIENT_ID)
    if azp != settings.FANID_CLIENT_ID:
        raise InvalidKeycloakToken(f'client غیرمجاز: {azp!r}')
    if not hmac.compare_digest(str(claims['nonce']), nonce):
        raise InvalidKeycloakToken('nonce نامعتبر')

    _require_identity_claims(claims)
    return claims


def get_linked_user(claims):
    """
    فقط کاربری که قبلاً (بعد از OTP، در fanid_views.py) به همین Fan ID متصل شده؛
    هرگز کاربر نمی‌سازد و متصل نمی‌کند. محدود به user_type='normal' -- هم‌الگوی
    PhoneBackend: ورود بدون رمز برای ادمین/VIP مجاز نیست.
    """
    return User.objects.filter(fan_id_subject=claims['sub'], user_type='normal', is_active=True).first()


def try_authenticate_keycloak(request):
    """
    اگر هدر Authorization حاوی یک Bearer Token معتبر Keycloak متعلق به یک کاربر
    متصل‌شده باشد، همان کاربر را برمی‌گرداند؛ در غیر این صورت None.

    این تابع هرگز خطا Raise نمی‌کند و هرگز درخواست را رد نمی‌کند -- فقط
    «آپگرید» یک درخواست Anonymous را به کاربر واقعی، وقتی ممکن باشد، امتحان
    می‌کند. در هر حالت دیگر، درخواست دقیقاً مثل حالتی که هیچ Authorization Header ای
    نبود ادامه پیدا می‌کند -- کنترل دسترسی صفحات محافظت‌شده همچنان با
    login_required/session فعلی است.
    """
    auth_header = request.META.get('HTTP_AUTHORIZATION', '')
    if not auth_header.startswith('Bearer '):
        return None
    token = auth_header[len('Bearer '):].strip()
    if not token:
        return None

    try:
        claims = decode_keycloak_token(token)
    except (jwt.PyJWTError, jwt.PyJWKClientError, InvalidKeycloakToken) as exc:
        logger.info('Fan ID bearer token rejected: %s', exc)
        return None
    return get_linked_user(claims)
