# accounts/keycloak_auth.py
"""
اعتبارسنجی Bearer Token صادرشده توسط Keycloak (Fan ID مرکزی سوپراپ -- ریپوی
جدا sepapp) و Provisioning خودکار کاربر Django متناظر.

پیاده‌سازی واقعی تصمیم‌های زیر (مستندات کامل در ریپوی sepapp):
  - docs/adr/0004-django-ticketing-sso-integration.md
  - docs/adr/0008-new-user-jit-provisioning.md

این ماژول عمداً از accounts.middleware جدا نگه داشته شده -- همان الگویی که
در این اپ برای services.py (ارسال OTP) هم استفاده شده: منطق مستقل و
قابل‌تست، بدون وابستگی به چرخه‌ی درخواست/پاسخ جنگو.

مهم: این مسیر اضافه‌شده است، نه جایگزین. ورود فعلی (OTP برای کاربر عادی،
رمز برای ادمین/VIP در accounts/backends.py) دست‌نخورده می‌ماند.
"""
import logging

import jwt
from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction

logger = logging.getLogger(__name__)

User = get_user_model()

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


def decode_keycloak_token(token):
    """
    امضا/انقضا/صادرکننده را بررسی می‌کند و Claimها را برمی‌گرداند.

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
        options={'require': ['exp', 'iat', 'sub']},
    )

    # فقط توکن‌های صادرشده برای Clientهای شناخته‌شده‌ی خودمان (azp) پذیرفته
    # می‌شوند -- یک اپ ناشناس داخل همان Realm نباید بتواند کاربر Django
    # بسازد/جا بزند، حتی اگر امضایش هم از نظر رمزنگاری معتبر باشد.
    azp = claims.get('azp')
    if azp not in settings.KEYCLOAK_TRUSTED_CLIENTS:
        raise InvalidKeycloakToken(f'client غیرمجاز: {azp!r}')

    if not claims.get('national_code') or not claims.get('phone_number'):
        raise InvalidKeycloakToken('claim های national_code/phone_number در توکن نیستند')

    return claims


def get_or_create_user_from_claims(claims):
    """
    JIT Provisioning طبق ADR-0008.

    Race Condition (دو درخواست هم‌زمان با اولین توکن یک کاربر کاملاً جدید)
    با Unique Constraint سطح دیتابیس روی national_code مهار می‌شود، نه با
    قفل سطح اپلیکیشن -- همان الگویی که این پروژه قبلاً برای کیف‌پول/سهمیه‌ی
    VIP/کد تخفیف استفاده کرده (طبق گزارش موجود سیستم).
    """
    national_code = claims['national_code']
    phone_number = claims['phone_number']
    fan_id_subject = claims['sub']

    try:
        user = User.objects.get(national_code=national_code)
        if user.fan_id_subject != fan_id_subject:
            user.fan_id_subject = fan_id_subject
            user.save(update_fields=['fan_id_subject'])
        return user
    except User.DoesNotExist:
        pass

    try:
        with transaction.atomic():
            return User.objects.create(
                username=national_code,
                national_code=national_code,
                phone_number=phone_number,
                fan_id_subject=fan_id_subject,
                user_type='normal',
                is_phone_verified=True,  # شماره از قبل توسط Keycloak/OTP تأیید شده
            )
    except IntegrityError:
        # یکی دیگه هم‌زمان همین کاربر رو ساخت؛ همونو برگردون، خطا نده
        return User.objects.get(national_code=national_code)


def try_authenticate_keycloak(request):
    """
    اگر هدر Authorization حاوی یک Bearer Token معتبر Keycloak باشد، کاربر
    Django متناظر را برمی‌گرداند؛ در غیر این صورت None.

    این تابع هرگز خطا Raise نمی‌کند و هرگز درخواست را رد نمی‌کند -- فقط
    «آپگرید» یک درخواست Anonymous را به کاربر واقعی، وقتی ممکن باشد، امتحان
    می‌کند. اگر توکن نبود/نامعتبر بود/منقضی بود/از Client نامعتبر بود، درخواست
    دقیقاً مثل حالتی که هیچ Authorization Header ای نبود ادامه پیدا می‌کند --
    کنترل دسترسی صفحات محافظت‌شده همچنان با login_required/session فعلی است.
    """
    auth_header = request.META.get('HTTP_AUTHORIZATION', '')
    if not auth_header.startswith('Bearer '):
        return None
    token = auth_header[len('Bearer '):].strip()
    if not token:
        return None

    try:
        claims = decode_keycloak_token(token)
        return get_or_create_user_from_claims(claims)
    except (jwt.PyJWTError, jwt.PyJWKClientError, InvalidKeycloakToken) as exc:
        logger.info('Fan ID bearer token rejected: %s', exc)
        return None
