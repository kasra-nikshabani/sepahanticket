# accounts/fanid_views.py
"""
ورود با Fan ID (حساب اپ سپاهان) روی خود سایت: OIDC Authorization Code + PKCE.

هر حساب Fan ID فقط بار اول یک OTP لازم دارد و بعد از آن هرگز:
  - اگر در این سایت حسابی با همان کد ملی هست، کد به شماره‌ای می‌رود که همین سایت
    از قبل برای آن حساب دارد -- نه شماره‌ی داخل توکن.
  - اگر حسابی نیست، کد به شماره‌ی Fan ID می‌رود و حساب بعد از تأیید ساخته می‌شود.
دلیل (ثبت‌نام Fan ID مالکیت شماره و کد ملی را تأیید نمی‌کند): keycloak_auth.py.

تا FANID_LOGIN_ENABLED روشن نشود، همه‌ی این مسیرها ۴۰۴ می‌دهند و دکمه‌ای هم در
صفحه‌ی ورود نمایش داده نمی‌شود. ارسال و بررسی کد از همان services.create_otp /
get_valid_otp ورود معمولی است (محدودیت زمانی، سقف تلاش، محدودیت اپراتور).
"""
import base64
import hashlib
import hmac
import logging
import secrets
from urllib.parse import urlencode

import jwt
import requests
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model, login
from django.db import IntegrityError, transaction
from django.http import Http404, JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST

from .forms import OTPVerifyForm
from .keycloak_auth import InvalidKeycloakToken, decode_fanid_id_token
from .models import OTP
from .services import OTPRateLimitError, SMSProviderBusyError, create_otp, get_valid_otp

logger = logging.getLogger(__name__)

User = get_user_model()

SESSION_AUTH = 'fanid_auth'
SESSION_PENDING = 'fanid_pending'

# هم‌دلیل services.SMS_TIMEOUT: این تماس داخل چرخه‌ی درخواست است و یک worker را
# تا پایانش قفل نگه می‌دارد.
TOKEN_TIMEOUT = 5


class LinkRefused(Exception):
    """اتصال این Fan ID به حساب سایت مجاز نیست؛ متن استثنا به کاربر نمایش داده می‌شود."""


def _require_enabled():
    if not settings.FANID_LOGIN_ENABLED:
        raise Http404


def _safe_next(request, url):
    if url and url_has_allowed_host_and_scheme(
        url, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        return url
    return None


def _pkce_challenge(verifier):
    digest = hashlib.sha256(verifier.encode('ascii')).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b'=').decode('ascii')


def _check_can_use_fanid(user):
    # هم‌الگوی PhoneBackend و phone_login: ورود بدون رمز فقط برای کاربر عادی.
    if user.user_type != 'normal' or not user.is_active:
        raise LinkRefused('این حساب نمی‌تواند با Fan ID وارد شود. لطفاً از ورود با رمز عبور استفاده کنید.')


def _login(request, user, next_url):
    # هم‌الگوی otp_verify در views.py
    user.backend = 'accounts.backends.PhoneBackend'
    login(request, user)
    request.session['user_type'] = user.user_type
    messages.success(request, f'خوش آمدید {user.get_full_name() or user.phone_number}!')
    response = redirect(next_url or 'matches:home')
    response['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    return response


@never_cache
def fanid_login(request):
    _require_enabled()
    if request.user.is_authenticated:
        return redirect('matches:home')

    state = secrets.token_urlsafe(32)
    nonce = secrets.token_urlsafe(32)
    verifier = secrets.token_urlsafe(64)
    request.session[SESSION_AUTH] = {
        'state': state,
        'nonce': nonce,
        'verifier': verifier,
        'next': _safe_next(request, request.GET.get('next')),
    }
    query = urlencode({
        'client_id': settings.FANID_CLIENT_ID,
        'response_type': 'code',
        'scope': 'openid',
        'redirect_uri': settings.FANID_REDIRECT_URI,
        'state': state,
        'nonce': nonce,
        'code_challenge': _pkce_challenge(verifier),
        'code_challenge_method': 'S256',
    })
    return redirect(f'{settings.KEYCLOAK_ISSUER}/protocol/openid-connect/auth?{query}')


def _exchange_code(code, verifier, nonce):
    response = requests.post(
        f'{settings.KEYCLOAK_ISSUER}/protocol/openid-connect/token',
        data={
            'grant_type': 'authorization_code',
            'code': code,
            'redirect_uri': settings.FANID_REDIRECT_URI,
            'client_id': settings.FANID_CLIENT_ID,
            'client_secret': settings.FANID_CLIENT_SECRET,
            'code_verifier': verifier,
        },
        timeout=TOKEN_TIMEOUT,
    )
    response.raise_for_status()
    id_token = response.json().get('id_token')
    if not id_token:
        raise InvalidKeycloakToken('پاسخ Token Endpoint بدون id_token')
    return decode_fanid_id_token(id_token, nonce)


@never_cache
def fanid_callback(request):
    _require_enabled()
    # یک‌بارمصرف: state/nonce/verifier همین‌جا از Session برداشته می‌شوند.
    auth = request.session.pop(SESSION_AUTH, None)
    state = request.GET.get('state', '')
    if not auth or not hmac.compare_digest(state, auth['state']):
        messages.error(request, 'درخواست ورود با Fan ID منقضی یا نامعتبر است. لطفاً دوباره تلاش کنید.')
        return redirect('accounts:phone_login')

    code = request.GET.get('code')
    if request.GET.get('error') or not code:
        messages.info(request, 'ورود با Fan ID انجام نشد.')
        return redirect('accounts:phone_login')

    try:
        claims = _exchange_code(code, auth['verifier'], auth['nonce'])
    except (requests.RequestException, ValueError, jwt.PyJWTError, jwt.PyJWKClientError,
            InvalidKeycloakToken) as exc:
        logger.warning('Fan ID callback rejected: %s', exc)
        messages.error(request, 'ورود با Fan ID ناموفق بود. لطفاً دوباره تلاش کنید.')
        return redirect('accounts:phone_login')

    try:
        return _login_or_start_linking(request, claims, auth.get('next'))
    except LinkRefused as exc:
        messages.error(request, str(exc))
        return redirect('accounts:phone_login')


def _link_target(claims):
    """حساب موجود این سایت که Fan ID به آن متصل می‌شود، یا None برای کاربر تازه."""
    target = User.objects.filter(national_code=claims['national_code']).first()
    if target is None:
        if User.objects.filter(phone_number=claims['phone_number']).exists():
            # شماره‌ی Fan ID این‌جا مال حسابی با کد ملی دیگر است -- حدس نمی‌زنیم کدام درست است.
            raise LinkRefused('شماره موبایل حساب Fan ID شما در سایت بلیط با کد ملی دیگری ثبت شده است. '
                              'لطفاً با پشتیبانی تماس بگیرید.')
        return None
    if target.fan_id_subject:
        raise LinkRefused('حساب سایت بلیط با این کد ملی قبلاً به حساب Fan ID دیگری متصل شده است. '
                          'لطفاً با پشتیبانی تماس بگیرید.')
    _check_can_use_fanid(target)
    if not target.phone_number:
        raise LinkRefused('برای حساب سایت بلیط با این کد ملی شماره موبایلی ثبت نشده است. '
                          'لطفاً با پشتیبانی تماس بگیرید.')
    return target


def _login_or_start_linking(request, claims, next_url):
    linked = User.objects.filter(fan_id_subject=claims['sub']).first()
    if linked is not None:
        _check_can_use_fanid(linked)
        return _login(request, linked, next_url)

    target = _link_target(claims)
    otp_phone = target.phone_number if target else claims['phone_number']
    request.session[SESSION_PENDING] = {
        'sub': claims['sub'],
        'national_code': claims['national_code'],
        'otp_phone': otp_phone,
        'target_id': target.pk if target else None,
        'first_name': claims.get('given_name', ''),
        'last_name': claims.get('family_name', ''),
        'next': next_url,
    }

    try:
        create_otp(otp_phone)
    except OTPRateLimitError as e:
        messages.info(request, f'کد قبلی هنوز معتبر است. {e.retry_after} ثانیه دیگر می‌توانید کد جدید بگیرید.')
    except SMSProviderBusyError as e:
        messages.error(request, e.message)
        return redirect('accounts:phone_login')
    except Exception as e:
        logger.error('Fan ID link OTP failed for %s***: %s', otp_phone[:6], e)
        messages.error(request, 'ارسال پیامک موقتاً ممکن نیست. چند لحظه دیگر دوباره تلاش کنید.')
        return redirect('accounts:phone_login')
    return redirect('accounts:fanid_verify')


def _link_or_create(pending):
    try:
        with transaction.atomic():
            if pending['target_id'] is None:
                return User.objects.create_user(
                    username=pending['national_code'],
                    national_code=pending['national_code'],
                    phone_number=pending['otp_phone'],
                    first_name=pending['first_name'],
                    last_name=pending['last_name'],
                    fan_id_subject=pending['sub'],
                    user_type='normal',
                    is_active=True,
                    is_phone_verified=True,  # همین الان با OTP تأیید شد
                    password=None,
                )

            user = User.objects.select_for_update().get(pk=pending['target_id'])
            if user.fan_id_subject == pending['sub']:
                return user  # دو ارسال هم‌زمان همان کد؛ اولی متصل کرده
            # بین شروع ورود و تأیید کد، حساب نباید تغییر کرده باشد.
            if (user.fan_id_subject or user.national_code != pending['national_code']
                    or user.phone_number != pending['otp_phone']):
                raise LinkRefused('اطلاعات حساب در این فاصله تغییر کرد. لطفاً دوباره با Fan ID وارد شوید.')
            _check_can_use_fanid(user)
            user.fan_id_subject = pending['sub']
            user.is_phone_verified = True
            user.save(update_fields=['fan_id_subject', 'is_phone_verified'])
            return user
    except (IntegrityError, User.DoesNotExist):
        raise LinkRefused('اتصال حساب انجام نشد. لطفاً دوباره با Fan ID وارد شوید.')


def _count_failed_attempt(request, phone):
    # هم‌الگوی otp_verify در views.py
    try:
        latest = OTP.objects.filter(phone_number=phone, is_used=False).latest('created_at')
        latest.increment_attempts()
        if latest.attempts >= 3:
            messages.error(request, '❌ تعداد تلاش‌های ناموفق بیش از حد مجاز.')
            return
    except OTP.DoesNotExist:
        pass
    messages.error(request, '❌ کد وارد شده صحیح نیست یا منقضی شده است.')


@never_cache
def fanid_verify(request):
    _require_enabled()
    pending = request.session.get(SESSION_PENDING)
    if not pending:
        messages.error(request, 'لطفاً دوباره از «ورود با Fan ID» شروع کنید.')
        return redirect('accounts:phone_login')

    phone = pending['otp_phone']
    form = OTPVerifyForm()
    if request.method == 'POST':
        form = OTPVerifyForm(request.POST)
        if form.is_valid():
            otp = get_valid_otp(phone, form.cleaned_data['otp_code'])
            if otp:
                otp.use()
                request.session.pop(SESSION_PENDING, None)
                try:
                    user = _link_or_create(pending)
                except LinkRefused as exc:
                    messages.error(request, str(exc))
                    return redirect('accounts:phone_login')
                return _login(request, user, pending.get('next'))
            _count_failed_attempt(request, phone)
        else:
            for errors in form.errors.values():
                for error in errors:
                    messages.error(request, error)

    try:
        latest = OTP.objects.filter(phone_number=phone, is_used=False).latest('created_at')
        remaining_time = max(0, int((latest.expires_at - timezone.now()).total_seconds()))
    except OTP.DoesNotExist:
        remaining_time = 0

    return render(request, 'accounts/otp_verify.html', {
        'form': form,
        'phone_number': phone,
        'phone_masked': f'{phone[:4]}****{phone[-4:]}',
        'remaining_time': remaining_time,
        'page_title': 'اتصال حساب Fan ID',
        'page_subtitle': 'فقط همین یک بار: کد ارسال‌شده به شماره‌ی زیر را وارد کنید',
        'submit_label': 'تأیید و اتصال',
        'resend_url': reverse('accounts:fanid_resend'),
        'cancel_url': reverse('accounts:phone_login'),
        'cancel_label': 'انصراف',
    })


@require_POST
def fanid_resend(request):
    _require_enabled()
    pending = request.session.get(SESSION_PENDING)
    if not pending:
        return JsonResponse(
            {'status': 'error', 'message': '❌ لطفاً دوباره از «ورود با Fan ID» شروع کنید.'}, status=400)

    phone = pending['otp_phone']
    # پاسخ‌ها هم‌شکل resend_otp در views.py -- اسکریپت صفحه‌ی otp_verify.html همین را می‌خواند.
    try:
        create_otp(phone)
        return JsonResponse({'status': 'success', 'message': '✅ کد جدید با موفقیت ارسال شد.'})
    except OTPRateLimitError as e:
        return JsonResponse(
            {'status': 'error', 'message': f'⏳ لطفاً {e.retry_after} ثانیه صبر کنید و دوباره تلاش کنید.',
             'retry_after': e.retry_after},
            status=429,
        )
    except SMSProviderBusyError as e:
        return JsonResponse(
            {'status': 'error', 'message': f'⏳ {e.message}', 'retry_after': e.retry_after}, status=429)
    except Exception as e:
        logger.error('fanid_resend failed for %s***: %s', phone[:6], e)
        return JsonResponse(
            {'status': 'error', 'message': '❌ ارسال پیامک موقتاً ممکن نیست. چند لحظه دیگر دوباره تلاش کنید.'},
            status=503,
        )
