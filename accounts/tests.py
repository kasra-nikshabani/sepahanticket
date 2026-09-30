"""
تست‌های ورود با Fan ID (Keycloak): مسیر Bearer (اپ) و مسیر مرورگر (دکمه‌ی صفحه‌ی ورود).

توکن واقعی Keycloak لازم نیست -- با یک جفت‌کلید RSA یک‌بارمصرف JWT امضا می‌شود و
PyJWKClient، Token Endpoint و ارسال پیامک Mock می‌شوند؛ هیچ تماس شبکه‌ای انجام نمی‌شود.
با اجرای معمولی تست‌ها (manage.py test) اجرا می‌شوند.
"""
import base64
import hashlib
import time
from datetime import timedelta
from unittest.mock import MagicMock, patch
from urllib.parse import parse_qs, urlparse

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.keycloak_auth import InvalidKeycloakToken, decode_keycloak_token, try_authenticate_keycloak
from accounts.middleware import KeycloakBearerAuthenticationMiddleware
from accounts.models import OTP

User = get_user_model()

_PRIVATE_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_PUBLIC_KEY = _PRIVATE_KEY.public_key()

ISSUER = 'http://localhost:8080/realms/sepahan'
TRUSTED_CLIENT = 'mobile-app'
SITE_CLIENT = 'ticket-site'
SUB = '11111111-1111-1111-1111-111111111111'
NATIONAL_CODE = '0012345678'
FANID_PHONE = '09120000000'


class _FakeSigningKey:
    def __init__(self, key):
        self.key = key


class _FakeJWKSClient:
    """جایگزین PyJWKClient واقعی -- به‌جای زدن به شبکه، کلید عمومی تست را برمی‌گرداند."""

    def get_signing_key_from_jwt(self, token):
        return _FakeSigningKey(_PUBLIC_KEY)


def _make_token(*, national_code=NATIONAL_CODE, phone_number=FANID_PHONE, sub=SUB, azp=TRUSTED_CLIENT,
                issuer=ISSUER, exp_delta=300, include_claims=True, **extra):
    now = int(time.time())
    claims = {'iss': issuer, 'sub': sub, 'azp': azp, 'iat': now, 'exp': now + exp_delta, **extra}
    if include_claims:
        claims['national_code'] = national_code
        claims['phone_number'] = phone_number
    return jwt.encode(claims, _PRIVATE_KEY, algorithm='RS256')


def _patch_jwks(test_case):
    patcher = patch('accounts.keycloak_auth._get_jwks_client', return_value=_FakeJWKSClient())
    test_case.addCleanup(patcher.stop)
    patcher.start()


def _allow_all_ips():
    # هم‌الگوی بقیه‌ی تست‌های این پروژه: کلاینت تست هدر X-Iran-IP ندارد.
    from accounts.models import SiteSettings
    s = SiteSettings.get_solo()
    s.block_foreign_ips = False
    s.save()


@override_settings(KEYCLOAK_ISSUER=ISSUER, KEYCLOAK_TRUSTED_CLIENTS=[TRUSTED_CLIENT, 'admin-panel'])
class KeycloakBearerTests(TestCase):

    def setUp(self):
        _patch_jwks(self)
        self.factory = RequestFactory()

    def _request(self, token=None):
        headers = {'HTTP_AUTHORIZATION': f'Bearer {token}'} if token else {}
        return self.factory.get('/', **headers)

    # ---------- decode_keycloak_token ----------

    def test_valid_token_decodes(self):
        claims = decode_keycloak_token(_make_token())
        self.assertEqual(claims['national_code'], NATIONAL_CODE)
        self.assertEqual(claims['phone_number'], FANID_PHONE)

    def test_wrong_issuer_rejected(self):
        with self.assertRaises(jwt.InvalidIssuerError):
            decode_keycloak_token(_make_token(issuer='http://evil.example/realms/sepahan'))

    def test_expired_token_rejected(self):
        with self.assertRaises(jwt.ExpiredSignatureError):
            decode_keycloak_token(_make_token(exp_delta=-120))

    def test_untrusted_client_rejected(self):
        with self.assertRaises(InvalidKeycloakToken):
            decode_keycloak_token(_make_token(azp='some-random-unregistered-client'))

    def test_missing_claims_rejected(self):
        with self.assertRaises(InvalidKeycloakToken):
            decode_keycloak_token(_make_token(include_claims=False))

    # ---------- هرگز ساختن یا متصل‌کردن حساب از روی توکن ----------

    def test_unknown_fan_id_creates_no_user(self):
        self.assertIsNone(try_authenticate_keycloak(self._request(_make_token())))
        self.assertEqual(User.objects.count(), 0)

    def test_national_code_alone_never_links_existing_account(self):
        # سناریوی تصاحب حساب: کسی با کد ملی صاحب این حساب در Fan ID ثبت‌نام کرده.
        victim = User.objects.create_user(
            username=NATIONAL_CODE, national_code=NATIONAL_CODE, phone_number='09121111111',
            user_type='normal', is_phone_verified=True)

        self.assertIsNone(try_authenticate_keycloak(self._request(_make_token())))
        victim.refresh_from_db()
        self.assertIsNone(victim.fan_id_subject)

    def test_linked_user_is_authenticated(self):
        linked = User.objects.create_user(
            username=NATIONAL_CODE, national_code=NATIONAL_CODE, phone_number=FANID_PHONE,
            user_type='normal', fan_id_subject=SUB)
        self.assertEqual(try_authenticate_keycloak(self._request(_make_token())), linked)

    def test_linked_vip_is_not_authenticated(self):
        # ورود بدون رمز فقط برای کاربر عادی -- هم‌الگوی PhoneBackend.
        User.objects.create_user(
            username=NATIONAL_CODE, national_code=NATIONAL_CODE, phone_number=FANID_PHONE,
            user_type='vip', fan_id_subject=SUB)
        self.assertIsNone(try_authenticate_keycloak(self._request(_make_token())))

    def test_no_header_returns_none(self):
        self.assertIsNone(try_authenticate_keycloak(self._request()))

    def test_garbage_bearer_returns_none_not_raises(self):
        # سناریوی توکن Opaque اسکنر گیت -- نباید Exception بدهد
        self.assertIsNone(try_authenticate_keycloak(self._request('this-is-not-a-jwt-at-all')))

    # ---------- Middleware ----------

    def test_middleware_upgrades_anonymous_request_for_linked_user(self):
        linked = User.objects.create_user(
            username=NATIONAL_CODE, national_code=NATIONAL_CODE, phone_number=FANID_PHONE,
            user_type='normal', fan_id_subject=SUB)
        request = self._request(_make_token())
        request.user = AnonymousUser()
        middleware = KeycloakBearerAuthenticationMiddleware(get_response=lambda r: r.user)
        self.assertEqual(middleware(request), linked)

    def test_middleware_never_overrides_existing_session_auth(self):
        session_user = User.objects.create_user(
            username='already-logged-in', national_code='0099999999', phone_number='09121111111', user_type='vip')
        User.objects.create_user(
            username=NATIONAL_CODE, national_code=NATIONAL_CODE, phone_number=FANID_PHONE,
            user_type='normal', fan_id_subject=SUB)
        request = self._request(_make_token())
        request.user = session_user
        middleware = KeycloakBearerAuthenticationMiddleware(get_response=lambda r: r.user)
        self.assertEqual(middleware(request), session_user)


def _fake_otp(phone_number):
    return OTP.objects.create(phone_number=phone_number, code='1234',
                              expires_at=timezone.now() + timedelta(minutes=5))


@override_settings(
    KEYCLOAK_ISSUER=ISSUER,
    FANID_LOGIN_ENABLED=True,
    FANID_CLIENT_ID=SITE_CLIENT,
    FANID_CLIENT_SECRET='test-secret',
    FANID_REDIRECT_URI='http://testserver/accounts/fanid/callback/',
    SECURE_SSL_REDIRECT=False,
)
class FanIdBrowserLoginTests(TestCase):

    def setUp(self):
        _allow_all_ips()
        _patch_jwks(self)
        otp_patcher = patch('accounts.fanid_views.create_otp', side_effect=_fake_otp)
        self.addCleanup(otp_patcher.stop)
        self.create_otp = otp_patcher.start()

    def _start(self, next_url=None):
        url = reverse('accounts:fanid_login') + (f'?next={next_url}' if next_url else '')
        response = self.client.get(url)
        return response, self.client.session['fanid_auth']

    def _callback(self, *, nonce=None, aud=SITE_CLIENT, state=None, **claims):
        response, auth = self._start()
        id_token = _make_token(azp=aud, aud=aud, nonce=nonce or auth['nonce'], **claims)
        token_response = MagicMock(status_code=200)
        token_response.json.return_value = {'id_token': id_token}
        with patch('accounts.fanid_views.requests.post', return_value=token_response) as post:
            response = self.client.get(reverse('accounts:fanid_callback'),
                                       {'state': state or auth['state'], 'code': 'auth-code'})
        return response, post

    def _logged_in_user_id(self):
        return self.client.session.get('_auth_user_id')

    # ---------- خاموش بودن پیش‌فرض ----------

    @override_settings(FANID_LOGIN_ENABLED=False)
    def test_disabled_by_default_everything_404_and_no_button(self):
        for name in ('fanid_login', 'fanid_callback', 'fanid_verify'):
            self.assertEqual(self.client.get(reverse(f'accounts:{name}')).status_code, 404)
        self.assertEqual(self.client.post(reverse('accounts:fanid_resend')).status_code, 404)
        self.assertNotContains(self.client.get(reverse('accounts:phone_login')), 'fanid/login')

    def test_button_shown_when_enabled(self):
        self.assertContains(self.client.get(reverse('accounts:phone_login')), reverse('accounts:fanid_login'))

    # ---------- شروع ورود ----------

    def test_login_redirects_to_keycloak_with_pkce_state_and_nonce(self):
        response, auth = self._start()
        location = urlparse(response['Location'])
        params = {k: v[0] for k, v in parse_qs(location.query).items()}

        self.assertEqual(f'{location.scheme}://{location.netloc}{location.path}',
                         f'{ISSUER}/protocol/openid-connect/auth')
        self.assertEqual(params['client_id'], SITE_CLIENT)
        self.assertEqual(params['state'], auth['state'])
        self.assertEqual(params['nonce'], auth['nonce'])
        self.assertEqual(params['code_challenge_method'], 'S256')
        expected = base64.urlsafe_b64encode(hashlib.sha256(auth['verifier'].encode()).digest()).rstrip(b'=').decode()
        self.assertEqual(params['code_challenge'], expected)
        self.assertNotIn('verifier', location.query)

    def test_open_redirect_in_next_is_dropped(self):
        _, auth = self._start('https://evil.example/steal')
        self.assertIsNone(auth['next'])

    # ---------- رد شدن callback نامعتبر ----------

    def test_callback_with_wrong_state_is_rejected_before_token_call(self):
        response, post = self._callback(state='forged-state')
        post.assert_not_called()
        self.assertRedirects(response, reverse('accounts:phone_login'), fetch_redirect_response=False)
        self.assertIsNone(self._logged_in_user_id())

    def test_state_is_single_use(self):
        response, auth = self._start()
        self.client.get(reverse('accounts:fanid_callback'), {'state': auth['state'], 'error': 'access_denied'})
        self.assertNotIn('fanid_auth', self.client.session)

    def test_id_token_with_wrong_nonce_is_rejected(self):
        response, _ = self._callback(nonce='replayed-nonce')
        self.assertIsNone(self._logged_in_user_id())
        self.assertNotIn('fanid_pending', self.client.session)
        self.create_otp.assert_not_called()

    def test_id_token_for_another_client_is_rejected(self):
        response, _ = self._callback(aud=TRUSTED_CLIENT)
        self.assertIsNone(self._logged_in_user_id())
        self.create_otp.assert_not_called()

    # ---------- حساب از قبل متصل ----------

    def test_linked_user_logs_in_without_otp(self):
        linked = User.objects.create_user(
            username=NATIONAL_CODE, national_code=NATIONAL_CODE, phone_number=FANID_PHONE,
            user_type='normal', fan_id_subject=SUB)
        self._callback()
        self.assertEqual(self._logged_in_user_id(), str(linked.pk))
        self.create_otp.assert_not_called()

    # ---------- کاربر تازه ----------

    def test_new_user_is_created_only_after_otp_to_fan_id_phone(self):
        response, _ = self._callback(given_name='علی', family_name='رضایی')
        self.assertRedirects(response, reverse('accounts:fanid_verify'), fetch_redirect_response=False)
        self.create_otp.assert_called_once_with(FANID_PHONE)
        self.assertEqual(User.objects.count(), 0)

        self.client.post(reverse('accounts:fanid_verify'), {'otp_code': '1234'})

        user = User.objects.get(national_code=NATIONAL_CODE)
        self.assertEqual(user.fan_id_subject, SUB)
        self.assertEqual(user.phone_number, FANID_PHONE)
        self.assertEqual(user.get_full_name(), 'علی رضایی')
        self.assertTrue(user.is_phone_verified)
        self.assertEqual(user.user_type, 'normal')
        self.assertEqual(self._logged_in_user_id(), str(user.pk))

    # ---------- حساب موجود سایت ----------

    def test_existing_account_otp_goes_to_phone_on_file_not_token_phone(self):
        existing = User.objects.create_user(
            username=NATIONAL_CODE, national_code=NATIONAL_CODE, phone_number='09121111111',
            user_type='normal', is_phone_verified=True)
        self._callback(phone_number='09129999999')
        self.create_otp.assert_called_once_with('09121111111')

        self.client.post(reverse('accounts:fanid_verify'), {'otp_code': '1234'})
        existing.refresh_from_db()
        self.assertEqual(existing.fan_id_subject, SUB)
        self.assertEqual(existing.phone_number, '09121111111')
        self.assertEqual(self._logged_in_user_id(), str(existing.pk))

    def test_takeover_attempt_without_code_links_nothing(self):
        victim = User.objects.create_user(
            username=NATIONAL_CODE, national_code=NATIONAL_CODE, phone_number='09121111111',
            user_type='normal', is_phone_verified=True)
        self._callback(phone_number='09129999999')
        self.client.post(reverse('accounts:fanid_verify'), {'otp_code': '0000'})

        victim.refresh_from_db()
        self.assertIsNone(victim.fan_id_subject)
        self.assertIsNone(self._logged_in_user_id())

    def test_account_linked_to_another_fan_id_is_refused(self):
        User.objects.create_user(
            username=NATIONAL_CODE, national_code=NATIONAL_CODE, phone_number='09121111111',
            user_type='normal', fan_id_subject='22222222-2222-2222-2222-222222222222')
        self._callback()
        self.create_otp.assert_not_called()
        self.assertIsNone(self._logged_in_user_id())

    def test_vip_account_is_refused(self):
        User.objects.create_user(
            username=NATIONAL_CODE, national_code=NATIONAL_CODE, phone_number='09121111111', user_type='vip')
        self._callback()
        self.create_otp.assert_not_called()

    def test_phone_owned_by_other_national_code_is_refused(self):
        User.objects.create_user(
            username='0099999999', national_code='0099999999', phone_number=FANID_PHONE, user_type='normal')
        self._callback()
        self.create_otp.assert_not_called()
        self.assertEqual(User.objects.count(), 1)

    # ---------- next و ارسال مجدد ----------

    def test_safe_next_is_honoured_after_linking(self):
        _, auth = self._start('/wallet/')
        id_token = _make_token(azp=SITE_CLIENT, aud=SITE_CLIENT, nonce=auth['nonce'])
        token_response = MagicMock(status_code=200)
        token_response.json.return_value = {'id_token': id_token}
        with patch('accounts.fanid_views.requests.post', return_value=token_response):
            self.client.get(reverse('accounts:fanid_callback'), {'state': auth['state'], 'code': 'c'})
        response = self.client.post(reverse('accounts:fanid_verify'), {'otp_code': '1234'})
        self.assertRedirects(response, '/wallet/', fetch_redirect_response=False)

    def test_verify_without_pending_redirects_to_login(self):
        response = self.client.get(reverse('accounts:fanid_verify'))
        self.assertRedirects(response, reverse('accounts:phone_login'), fetch_redirect_response=False)

    def test_resend_sends_to_pending_phone_and_requires_post(self):
        self._callback()
        self.create_otp.reset_mock()
        self.assertEqual(self.client.get(reverse('accounts:fanid_resend')).status_code, 405)
        self.assertEqual(self.client.post(reverse('accounts:fanid_resend')).status_code, 200)
        self.create_otp.assert_called_once_with(FANID_PHONE)


class RegularOtpPageUnchangedTests(TestCase):
    """صفحه‌ی مشترک otp_verify.html برای ورود معمولی باید دقیقاً مثل قبل رندر شود."""

    def test_regular_otp_page_keeps_its_texts_and_resend_url(self):
        _allow_all_ips()
        session = self.client.session
        session['otp_phone'] = '09121111111'
        session.save()
        response = self.client.get(reverse('accounts:otp_verify'))
        self.assertContains(response, 'تأیید هویت')
        self.assertContains(response, 'تأیید و ورود')
        self.assertContains(response, 'تغییر شماره')
        self.assertContains(response, reverse('accounts:resend_otp'))
        self.assertNotContains(response, 'fanid')
