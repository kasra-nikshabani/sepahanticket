"""
تست‌های احراز هویت Fan ID (Keycloak) -- Phase 7 (sepapp).

طبق بند «Testing» بریف اصلی: بخش‌های حساس (Authentication) نیاز به تست
بیشتری دارند. این‌ها توکن واقعی Keycloak لازم ندارند -- با یک جفت‌کلید
RSA یک‌بارمصرف، JWT امضا می‌شود و PyJWKClient واقعی Mock می‌شود، پس بدون
هیچ سرویس خارجی (Keycloak/شبکه) قابل اجرا هستند.

چون کاربر دیتابیس این پروژه (sepahan_user) به‌عمد CREATEDB ندارد (بررسی‌شده
در Phase 7)، این تست‌ها را از دیتابیس واقعی Postgres کاملاً جدا نگه داشتیم:
SQLite In-memory + غیرفعال‌کردن Migration بقیه‌ی اپ‌ها (که تست‌های این فایل
اصلاً به جدول‌هایشان نیاز ندارند).
"""
import time
from unittest.mock import patch

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase, override_settings

from accounts.keycloak_auth import (
    InvalidKeycloakToken,
    decode_keycloak_token,
    get_or_create_user_from_claims,
    try_authenticate_keycloak,
)
from accounts.middleware import KeycloakBearerAuthenticationMiddleware

User = get_user_model()

_PRIVATE_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_PUBLIC_KEY = _PRIVATE_KEY.public_key()

ISSUER = 'http://localhost:8080/realms/sepahan'
TRUSTED_CLIENT = 'mobile-app'


class _FakeSigningKey:
    def __init__(self, key):
        self.key = key


class _FakeJWKSClient:
    """جایگزین PyJWKClient واقعی -- به‌جای زدن به شبکه، کلید عمومی تست را برمی‌گرداند."""

    def get_signing_key_from_jwt(self, token):
        return _FakeSigningKey(_PUBLIC_KEY)


def _make_token(*, national_code='0012345678', phone_number='+989120000000',
                 sub='11111111-1111-1111-1111-111111111111', azp=TRUSTED_CLIENT,
                 issuer=ISSUER, exp_delta=300, include_claims=True):
    now = int(time.time())
    claims = {
        'iss': issuer,
        'sub': sub,
        'azp': azp,
        'iat': now,
        'exp': now + exp_delta,
    }
    if include_claims:
        claims['national_code'] = national_code
        claims['phone_number'] = phone_number
    return jwt.encode(claims, _PRIVATE_KEY, algorithm='RS256')


# این فایل باید با football_tickets.settings_test اجرا شود (نه settings.py
# معمولی) -- دلیل کامل در docstring همان فایل: کاربر دیتابیس این پروژه عمداً
# CREATEDB ندارد و override_settings به‌تنهایی برای DATABASES/MIGRATION_MODULES
# در اینجا کافی نیست (Django پایگاه‌داده‌ی تست را قبل از اجرای TestCaseها می‌سازد).
@override_settings(
    KEYCLOAK_ISSUER=ISSUER,
    KEYCLOAK_TRUSTED_CLIENTS=[TRUSTED_CLIENT, 'admin-panel'],
)
class KeycloakAuthTests(TestCase):

    def setUp(self):
        patcher = patch('accounts.keycloak_auth._get_jwks_client', return_value=_FakeJWKSClient())
        self.addCleanup(patcher.stop)
        patcher.start()
        self.factory = RequestFactory()

    # ---------- decode_keycloak_token ----------

    def test_valid_token_decodes(self):
        claims = decode_keycloak_token(_make_token())
        self.assertEqual(claims['national_code'], '0012345678')
        self.assertEqual(claims['phone_number'], '+989120000000')

    def test_wrong_issuer_rejected(self):
        with self.assertRaises(jwt.InvalidIssuerError):
            decode_keycloak_token(_make_token(issuer='http://evil.example/realms/sepahan'))

    def test_expired_token_rejected(self):
        with self.assertRaises(jwt.ExpiredSignatureError):
            decode_keycloak_token(_make_token(exp_delta=-10))

    def test_untrusted_client_rejected(self):
        with self.assertRaises(InvalidKeycloakToken):
            decode_keycloak_token(_make_token(azp='some-random-unregistered-client'))

    def test_missing_claims_rejected(self):
        with self.assertRaises(InvalidKeycloakToken):
            decode_keycloak_token(_make_token(include_claims=False))

    # ---------- get_or_create_user_from_claims (JIT Provisioning) ----------

    def test_new_user_is_jit_provisioned(self):
        claims = decode_keycloak_token(_make_token())
        user = get_or_create_user_from_claims(claims)

        self.assertEqual(user.national_code, '0012345678')
        self.assertEqual(user.phone_number, '+989120000000')
        self.assertEqual(user.user_type, 'normal')
        self.assertTrue(user.is_phone_verified)
        self.assertEqual(user.fan_id_subject, '11111111-1111-1111-1111-111111111111')
        self.assertEqual(User.objects.count(), 1)

    def test_second_call_reuses_same_user_no_duplicate(self):
        claims = decode_keycloak_token(_make_token())
        first = get_or_create_user_from_claims(claims)
        second = get_or_create_user_from_claims(claims)

        self.assertEqual(first.id, second.id)
        self.assertEqual(User.objects.count(), 1)

    def test_existing_user_gets_fan_id_subject_backfilled(self):
        # کاربری که از قبل با OTP عادی (بدون Fan ID) ثبت‌نام کرده -- سناریوی
        # دقیقاً همان چیزی که ADR-0008 برایش طراحی شده.
        existing = User.objects.create(
            username='0012345678', national_code='0012345678',
            phone_number='+989120000000', user_type='normal', is_phone_verified=True,
        )
        self.assertIsNone(existing.fan_id_subject)

        claims = decode_keycloak_token(_make_token())
        user = get_or_create_user_from_claims(claims)

        self.assertEqual(user.id, existing.id)
        self.assertEqual(User.objects.count(), 1)
        user.refresh_from_db()
        self.assertEqual(user.fan_id_subject, '11111111-1111-1111-1111-111111111111')

    # ---------- try_authenticate_keycloak / Middleware (سطح درخواست) ----------

    def test_try_authenticate_with_valid_token(self):
        request = self.factory.get('/', HTTP_AUTHORIZATION=f'Bearer {_make_token()}')
        user = try_authenticate_keycloak(request)
        self.assertIsNotNone(user)
        self.assertEqual(user.national_code, '0012345678')

    def test_try_authenticate_no_header_returns_none(self):
        request = self.factory.get('/')
        self.assertIsNone(try_authenticate_keycloak(request))

    def test_try_authenticate_garbage_bearer_returns_none_not_raises(self):
        # این دقیقاً سناریوی توکن Opaque اسکنر گیت است -- نباید Exception بدهد
        request = self.factory.get('/', HTTP_AUTHORIZATION='Bearer this-is-not-a-jwt-at-all')
        self.assertIsNone(try_authenticate_keycloak(request))
        self.assertEqual(User.objects.count(), 0)

    def test_middleware_upgrades_anonymous_request(self):
        from django.contrib.auth.models import AnonymousUser

        request = self.factory.get('/', HTTP_AUTHORIZATION=f'Bearer {_make_token()}')
        request.user = AnonymousUser()
        middleware = KeycloakBearerAuthenticationMiddleware(get_response=lambda r: r.user)

        result_user = middleware(request)
        self.assertTrue(result_user.is_authenticated)
        self.assertEqual(result_user.national_code, '0012345678')

    def test_middleware_never_overrides_existing_session_auth(self):
        # الزام صریح ADR-0004: این مسیر افزودنی است، جایگزین نیست.
        session_user = User.objects.create(
            username='already-logged-in', national_code='0099999999',
            phone_number='+989121111111', user_type='vip',
        )
        request = self.factory.get('/', HTTP_AUTHORIZATION=f'Bearer {_make_token()}')
        request.user = session_user
        middleware = KeycloakBearerAuthenticationMiddleware(get_response=lambda r: r.user)

        result_user = middleware(request)
        self.assertEqual(result_user.id, session_user.id)
        # کاربر Fan ID (national_code متفاوت از توکن) نباید ساخته شده باشد
        self.assertEqual(User.objects.count(), 1)
