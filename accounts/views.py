# accounts/views.py
from django.http import JsonResponse, HttpResponseRedirect
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import login, authenticate, logout
from django.contrib.auth.decorators import login_required
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib import messages
from django.conf import settings
from django.utils import timezone
from django.contrib.auth import get_user_model
from django.views.decorators.cache import never_cache
from django.core.paginator import Paginator
from django.core.cache import cache
from django.db.models import Q
from django.utils.http import url_has_allowed_host_and_scheme

from .forms import RegisterForm, LoginForm, PhoneLoginForm, OTPVerifyForm, PhoneRegisterForm
from .models import OTP
from .services import create_otp, get_valid_otp, OTPRateLimitError, SMSProviderBusyError

User = get_user_model()

# ===== محدودیت تلاش ناموفقِ ورود با رمز =====
# هم‌الگوی همان چیزی که برای گیت (tickets/api.py) استفاده می‌شود.
LOGIN_MAX_ATTEMPTS = 5           # به‌ازای هر نام کاربری
LOGIN_MAX_ATTEMPTS_PER_IP = 20   # به‌ازای هر آی‌پی -- بالاتر، چون کاربران
                                 # ایرانی پشت NAT اپراتور آی‌پی مشترک دارند
LOGIN_LOCKOUT_SECONDS = 300      # ۵ دقیقه


def _client_ip(request):
    """آی‌پی واقعی کاربر از پشت nginx."""
    fwd = request.META.get('HTTP_X_FORWARDED_FOR', '')
    if fwd:
        return fwd.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR', '')

import logging

logger = logging.getLogger(__name__)


def choose_login(request):
    """صفحه انتخاب روش ورود (اختیاری)"""
    if request.user.is_authenticated:
        return redirect('matches:home')
    return render(request, 'accounts/choose_login.html')


# ==========================================
#  ویوهای ورود با OTP
# ==========================================

def phone_login(request):
    """ورود با شماره تلفن (فقط کاربران معمولی)"""
    if not getattr(settings, 'OTP_ENABLED', False):
        messages.error(request, 'ورود با شماره تلفن در حال حاضر غیرفعال است.')
        return redirect('accounts:login_password')

    if request.user.is_authenticated:
        return redirect('matches:home')

    if request.method == 'POST':
        form = PhoneLoginForm(request.POST)
        if form.is_valid():
            phone_number = form.cleaned_data['phone_number']

            try:
                user = User.objects.get(phone_number=phone_number)
            except User.DoesNotExist:
                messages.error(request, 'کاربری با این شماره تلفن یافت نشد. لطفاً ثبت‌نام کنید.')
                return redirect('accounts:phone_register')

            # فقط کاربران معمولی اجازه ورود با OTP دارند
            if user.user_type != 'normal':
                messages.error(request,
                               'این روش ورود فقط برای کاربران معمولی است. لطفاً از ورود با رمز عبور استفاده کنید.')
                return redirect('accounts:login_password')

            try:
                create_otp(phone_number)
                request.session['otp_phone'] = phone_number
                messages.success(request, 'کد تأیید به شماره شما ارسال شد.')
                return redirect('accounts:otp_verify')
            except OTPRateLimitError as e:
                # کد قبلی هنوز معتبر است؛ کاربر را همان‌جا به صفحه‌ی تأیید می‌فرستیم
                request.session['otp_phone'] = phone_number
                messages.info(request, f'کد قبلی هنوز معتبر است. {e.retry_after} ثانیه دیگر می‌توانید کد جدید بگیرید.')
                return redirect('accounts:otp_verify')
            except SMSProviderBusyError as e:
                messages.error(request, e.message)
            except Exception as e:
                logger.error("create_otp failed for %s***: %s", phone_number[:6], e)
                messages.error(request, 'ارسال پیامک موقتاً ممکن نیست. چند لحظه دیگر دوباره تلاش کنید.')
        else:
            for error in form.errors.values():
                messages.error(request, error)
    else:
        form = PhoneLoginForm()

    return render(request, 'accounts/phone_login.html', {'form': form})


@never_cache
def otp_verify(request):
    """تأیید کد OTP برای ورود/ثبت‌نام"""
    if not getattr(settings, 'OTP_ENABLED', False):
        messages.error(request, 'این قابلیت غیرفعال است.')
        return redirect('accounts:login_password')

    if request.user.is_authenticated:
        return redirect('matches:home')

    phone_number = request.session.get('otp_phone')
    if not phone_number:
        messages.error(request, 'لطفاً ابتدا شماره تلفن را وارد کنید.')
        return redirect('accounts:phone_login')

    form = OTPVerifyForm()

    if request.method == 'POST':
        form = OTPVerifyForm(request.POST)
        if form.is_valid():
            code = form.cleaned_data['otp_code']
            otp = get_valid_otp(phone_number, code)

            if otp:
                try:
                    user = User.objects.get(phone_number=phone_number)
                    otp.use()
                    user.is_active = True
                    user.is_phone_verified = True
                    user.save()

                    user.backend = 'accounts.backends.PhoneBackend'
                    login(request, user)

                    # ===== به‌روزرسانی سشن =====
                    request.session['user_type'] = user.user_type

                    request.session.pop('otp_phone', None)
                    messages.success(request, f'خوش آمدید {user.get_full_name() or user.phone_number}!')

                    # ===== جلوگیری از کش =====
                    response = redirect(request.GET.get('next', 'matches:home'))
                    response['Cache-Control'] = 'no-cache, no-store, must-revalidate'
                    return response

                except User.DoesNotExist:
                    pending = request.session.get('pending_registration')
                    if pending and pending.get('phone_number') == phone_number:
                        user = User.objects.create_user(
                            username=pending['national_code'],
                            phone_number=phone_number,
                            national_code=pending['national_code'],
                            first_name=pending['first_name'],
                            last_name=pending['last_name'],
                            gender=pending.get('gender'),
                            is_active=True,
                            user_type='normal',
                            password=None,
                        )
                        user.is_phone_verified = True
                        user.save(update_fields=['is_phone_verified'])
                        otp.use()

                        user.backend = 'accounts.backends.PhoneBackend'
                        login(request, user)

                        request.session['user_type'] = user.user_type
                        request.session.pop('otp_phone', None)
                        request.session.pop('pending_registration', None)
                        messages.success(request, f'خوش آمدید {user.get_full_name()}!')

                        response = redirect(request.GET.get('next', 'matches:home'))
                        response['Cache-Control'] = 'no-cache, no-store, must-revalidate'
                        return response
                    messages.error(request, 'کاربری با این شماره وجود ندارد.')
            else:
                try:
                    latest_otp = OTP.objects.filter(phone_number=phone_number, is_used=False).latest('created_at')
                    latest_otp.increment_attempts()
                    if latest_otp.attempts >= 3:
                        messages.error(request, '❌ تعداد تلاش‌های ناموفق بیش از حد مجاز.')
                    else:
                        messages.error(request, '❌ کد وارد شده صحیح نیست یا منقضی شده است.')
                except OTP.DoesNotExist:
                    messages.error(request, '❌ کد وارد شده صحیح نیست یا منقضی شده است.')
        else:
            for field, errors in form.errors.items():
                for error in errors:
                    messages.error(request, f'{field}: {error}')

    try:
        latest_otp = OTP.objects.filter(phone_number=phone_number, is_used=False).latest('created_at')
        remaining_time = max(0, int((latest_otp.expires_at - timezone.now()).total_seconds()))
    except OTP.DoesNotExist:
        remaining_time = 0

    masked_phone = f"{phone_number[:4]}****{phone_number[-4:]}"
    return render(request, 'accounts/otp_verify.html', {
        'form': form,
        'phone_number': phone_number,
        'phone_masked': masked_phone,
        'remaining_time': remaining_time,
    })


def resend_otp(request):
    """ارسال مجدد کد OTP"""
    if not getattr(settings, 'OTP_ENABLED', False):
        messages.error(request, 'این قابلیت در حال حاضر غیرفعال است.')
        return redirect('accounts:login')

    if request.user.is_authenticated:
        return redirect('matches:home')

    phone_number = request.session.get('otp_phone')
    if not phone_number:
        messages.error(request, 'لطفاً ابتدا شماره تلفن را وارد کنید.')
        return redirect('accounts:phone_login')

    # ===== محدودیت واقعی درخواست مجدد -- سمت بک‌اند، مستقل از session =====
    # (پیاده‌سازی داخل create_otp؛ اینجا فقط خطای آن را به فرانت‌اند برمی‌گردانیم)
    try:
        create_otp(phone_number)
        return JsonResponse({'status': 'success', 'message': '✅ کد جدید با موفقیت ارسال شد.'})
    except OTPRateLimitError as e:
        return JsonResponse(
            {'status': 'error', 'message': f'⏳ لطفاً {e.retry_after} ثانیه صبر کنید و دوباره تلاش کنید.',
             'retry_after': e.retry_after},
            status=429,
        )
    except SMSProviderBusyError as e:
        # سرویس پیامک خودش ما را محدود کرده -- خرابی سرور نیست، پس ۵۰۰ نمی‌دهیم
        return JsonResponse(
            {'status': 'error', 'message': f'⏳ {e.message}', 'retry_after': e.retry_after},
            status=429,
        )
    except Exception as e:
        logger.error("resend_otp failed for %s***: %s", (phone_number or '')[:6], e)
        return JsonResponse(
            {'status': 'error',
             'message': '❌ ارسال پیامک موقتاً ممکن نیست. چند لحظه دیگر دوباره تلاش کنید.'},
            status=503,
        )


# ==========================================
#  ویوهای ثبت‌نام و ورود معمولی (قبلی)
# ==========================================

def phone_register(request):
    """ثبت‌نام با شماره تلفن (فقط کاربران معمولی)"""
    if not getattr(settings, 'OTP_ENABLED', False):
        messages.error(request, 'ثبت‌نام با شماره تلفن در حال حاضر غیرفعال است.')
        return redirect('accounts:register_password')

    if request.user.is_authenticated:
        return redirect('matches:home')

    form = PhoneRegisterForm()

    if request.method == 'POST':
        form = PhoneRegisterForm(request.POST)
        if form.is_valid():
            phone_number = form.cleaned_data['phone_number']
            first_name = form.cleaned_data['first_name']
            last_name = form.cleaned_data['last_name']
            national_code = form.cleaned_data['national_code']
            gender = form.cleaned_data['gender']

            if User.objects.filter(phone_number=phone_number).exists():
                messages.error(request, 'این شماره تلفن قبلاً ثبت شده است.')
                return render(request, 'accounts/phone_register.html', {'form': form})

            if User.objects.filter(national_code=national_code).exists():
                messages.error(request, 'این کد ملی قبلاً ثبت شده است.')
                return render(request, 'accounts/phone_register.html', {'form': form})

            pending_data = {
                'phone_number': phone_number,
                'first_name': first_name,
                'last_name': last_name,
                'national_code': national_code,
                'gender': gender,
            }
            try:
                # حساب کاربری فقط بعد از تأیید موفق کد OTP ساخته می‌شود
                # (تا کاربرِ ثبت‌نامِ ناتمام در دیتابیس باقی نماند)
                create_otp(phone_number)
                request.session['otp_phone'] = phone_number
                request.session['pending_registration'] = pending_data
                messages.success(request, f'✅ کد تأیید به شماره {phone_number} ارسال شد.')
                return redirect('accounts:otp_verify')
            except OTPRateLimitError as e:
                # کد قبلی هنوز معتبر است؛ کاربر را همان‌جا به صفحه‌ی تأیید می‌فرستیم
                request.session['otp_phone'] = phone_number
                request.session['pending_registration'] = pending_data
                messages.info(request, f'کد قبلی هنوز معتبر است. {e.retry_after} ثانیه دیگر می‌توانید کد جدید بگیرید.')
                return redirect('accounts:otp_verify')
            except SMSProviderBusyError as e:
                # ===== خرابیِ سرویس پیامک، نه خطای کاربر =====
                # قبلاً این استثنا به except عمومیِ پایین می‌افتاد و متن خامِ
                # سرویس پیامک («تعداد درخواست بیشتر از حد مجاز است - N ثانیه
                # دیگر تلاش نمایید») مستقیم به کاربر نشان داده می‌شد، آن هم با
                # پیشوند «خطا در ثبت‌نام» -- که کاربر را به این نتیجه می‌رساند
                # که اطلاعاتش ایراد دارد، در حالی که ثبت‌نامش کاملاً درست بوده
                # و فقط پیامک ارسال نشده.
                logger.error("phone_register: SMS provider busy for %s***: %s",
                             phone_number[:6], e.message)
                messages.error(request, e.message)
            except Exception as e:
                logger.error("phone_register failed for %s***: %s", phone_number[:6], e)
                messages.error(request, '❌ ارسال کد تأیید موقتاً ممکن نیست. چند لحظه دیگر دوباره تلاش کنید.')
        else:
            # نمایش خطاهای فرم
            for field, errors in form.errors.items():
                for error in errors:
                    messages.error(request, f'{field}: {error}')

    return render(request, 'accounts/phone_register.html', {'form': form})


def register_view(request):
    """ثبت‌نام با نام کاربری و رمز عبور (برای ادمین و VIP - معمولاً توسط ادمین انجام می‌شود)"""
    # اگر می‌خواهید کاربران عادی نتوانند ثبت‌نام کنند، می‌توانید این ویو را محدود کنید
    if request.user.is_authenticated:
        return redirect('matches:home')

    # فقط کاربرانی که مجوز دارند (مثلاً ادمین) می‌توانند ثبت‌نام کنند
    # برای سادگی، فعلاً غیرفعال می‌کنیم
    messages.warning(request, 'ثبت‌نام با رمز عبور فقط توسط مدیر انجام می‌شود.')
    return redirect('accounts:login_password')


@never_cache
def login_view(request):
    """ورود با نام کاربری و رمز عبور (ادمین و VIP)"""
    if request.user.is_authenticated:
        return redirect('matches:home')

    if request.method == 'POST':
        # ===== محدودیت تلاش ناموفق =====
        # این تنها مسیر ورود با رمز است و حساب‌های مدیر از همین‌جا وارد
        # می‌شوند؛ بدون این محدودیت، حدس زدن رمز مدیر فقط به سرعت شبکه
        # محدود بود. هم روی نام کاربری قفل می‌شود (جلوی حمله به یک حساب)
        # و هم روی آی‌پی (جلوی امتحان‌کردن رمز مشترک روی حساب‌های زیاد).
        #
        # نکته: این چک عمداً *قبل* از form.is_valid() است. LoginForm از روی
        # AuthenticationForm ساخته شده و خودش داخل is_valid() احراز هویت
        # می‌کند؛ یعنی با رمز اشتباه is_valid() مقدار False برمی‌گرداند و
        # هر شمارنده‌ای که داخل شاخه‌ی موفق باشد هیچ‌وقت اجرا نمی‌شود.
        ip = _client_ip(request)
        attempted_username = (request.POST.get('username') or '').strip()
        u_key = f'login_fail:u:{attempted_username}'
        ip_key = f'login_fail:ip:{ip}'

        if (cache.get(u_key, 0) >= LOGIN_MAX_ATTEMPTS
                or cache.get(ip_key, 0) >= LOGIN_MAX_ATTEMPTS_PER_IP):
            logger.warning("ورود مسدود شد (تلاش زیاد) username=%s ip=%s", attempted_username, ip)
            messages.error(
                request,
                'به دلیل تلاش‌های ناموفق زیاد، ورود موقتاً مسدود شده است. '
                'چند دقیقه دیگر دوباره تلاش کنید.'
            )
            return render(request, 'accounts/login_password.html', {'form': LoginForm()})

        form = LoginForm(request, data=request.POST)
        if not form.is_valid():
            # رمز اشتباه، کاربر ناموجود، یا فرم ناقص -- همه تلاش ناموفق‌اند
            cache.set(u_key, cache.get(u_key, 0) + 1, timeout=LOGIN_LOCKOUT_SECONDS)
            cache.set(ip_key, cache.get(ip_key, 0) + 1, timeout=LOGIN_LOCKOUT_SECONDS)

        if form.is_valid():
            username = form.cleaned_data.get('username')
            password = form.cleaned_data.get('password')

            user = authenticate(request, username=username, password=password)
            if user is None:
                cache.set(u_key, cache.get(u_key, 0) + 1, timeout=LOGIN_LOCKOUT_SECONDS)
                cache.set(ip_key, cache.get(ip_key, 0) + 1, timeout=LOGIN_LOCKOUT_SECONDS)
            else:
                cache.delete(u_key)
                cache.delete(ip_key)

            if user is not None:
                if user.user_type in ['admin', 'vip']:
                    login(request, user)

                    # ===== به‌روزرسانی سشن =====
                    request.session['user_type'] = user.user_type

                    messages.success(request, f'خوش آمدید {user.get_full_name() or user.username}!')

                    # ===== بازگشت به صفحه قبلی =====
                    # next از URL می‌آید؛ بدون اعتبارسنجی، لینکی مثل
                    # /accounts/login-password/?next=https://evil.com مدیر را
                    # بعد از ورود به سایت مهاجم می‌برد (فیشینگِ مؤثر، چون
                    # کاربر همین الان با موفقیت وارد شده و اعتماد دارد).
                    next_url = request.GET.get('next') or ''
                    if not url_has_allowed_host_and_scheme(
                        next_url, allowed_hosts={request.get_host()},
                        require_https=request.is_secure(),
                    ):
                        if next_url:
                            logger.warning("next نامعتبر در ورود رد شد: %r", next_url[:120])
                        next_url = 'matches:home'

                    response = redirect(next_url)
                    response["Cache-Control"] = "no-cache, no-store, must-revalidate"
                    response["Pragma"] = "no-cache"
                    response["Expires"] = "0"

                    return response
                else:
                    messages.error(request, 'این روش ورود فقط برای مدیران و کاربران ویژه است.')
                    return redirect('accounts:phone_login')
            else:
                messages.error(request, 'نام کاربری یا رمز عبور اشتباه است.')
        else:
            messages.error(request, 'لطفاً اطلاعات را به درستی وارد کنید.')
    else:
        form = LoginForm()

    return render(request, 'accounts/login_password.html', {'form': form})


@never_cache
def logout_view(request):
    """خروج از حساب کاربری"""
    # ===== خروج =====
    logout(request)
    request.session.flush()

    messages.info(request, 'شما از حساب خود خارج شدید.')

    response = redirect('matches:home')
    response["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response["Pragma"] = "no-cache"
    response["Expires"] = "0"

    return response


@login_required
def profile_view(request):
    return render(request, 'accounts/profile.html', {'user': request.user})


@login_required
def edit_profile_view(request):
    if request.method == 'POST':
        user = request.user
        user.first_name = request.POST.get('full_name', user.first_name)
        user.email = request.POST.get('email', user.email)
        user.save()
        messages.success(request, 'اطلاعات شما با موفقیت به‌روزرسانی شد.')
        return redirect('accounts:profile')
    return render(request, 'accounts/edit_profile.html', {'user': request.user})


@login_required
def dashboard_redirect(request):
    if request.user.user_type == 'admin':
        return redirect('admin_dashboard')
    elif request.user.user_type == 'vip':
        return redirect('tickets:vip_dashboard')
    else:
        return redirect('matches:home')


@login_required
@staff_member_required
def admin_user_list(request):
    """لیست کاربران عادی (غیر VIP/ادمین) برای پنل ادمین اختصاصی سایت -- با جستجو و صفحه‌بندی"""
    search = request.GET.get('q', '').strip()

    users_qs = User.objects.filter(user_type='normal').order_by('-date_joined')
    if search:
        users_qs = users_qs.filter(
            Q(phone_number__icontains=search) |
            Q(national_code__icontains=search) |
            Q(first_name__icontains=search) |
            Q(last_name__icontains=search) |
            Q(username__icontains=search)
        )

    paginator = Paginator(users_qs, 25)
    page_obj = paginator.get_page(request.GET.get('page', 1))

    context = {
        'page_obj': page_obj,
        'search': search,
        'total_users': paginator.count,
    }
    return render(request, 'accounts/admin_user_list.html', context)


@login_required
@staff_member_required
def admin_user_detail(request, user_id):
    """اطلاعات کامل یک کاربر عادی + تاریخچه بلیط‌ها و کیف پول -- برای پنل ادمین"""
    from tickets.models import Ticket

    target_user = get_object_or_404(User, id=user_id, user_type='normal')

    tickets_qs = Ticket.objects.filter(user=target_user).select_related(
        'match', 'seat__row__block'
    ).order_by('-purchase_date')

    paginator = Paginator(tickets_qs, 20)
    page_obj = paginator.get_page(request.GET.get('page', 1))

    wallet = getattr(target_user, 'wallet', None)
    recent_transactions = target_user.transactions.all()[:10] if hasattr(target_user, 'transactions') else []

    context = {
        'target_user': target_user,
        'page_obj': page_obj,
        'total_tickets': tickets_qs.count(),
        'used_tickets': tickets_qs.filter(is_used=True).count(),
        'wallet': wallet,
        'recent_transactions': recent_transactions,
    }
    return render(request, 'accounts/admin_user_detail.html', context)


@login_required
@staff_member_required
def admin_emergency_settings(request):
    """
    کلید اضطراری برای زمانی که سرویس استعلام ثبت‌احوال قطع/خراب است -- با
    فعال‌سازی، فرم اطلاعات خریدار بدون تماس با آن سرویس (فقط با اعتبارسنجی
    فرمت) پذیرفته می‌شود. عمداً یک صفحه‌ی جدا و واضح است، نه یک فیلد
    گمشده در فرم تنظیمات عمومی، چون قرار است در لحظه‌ی نیاز واقعی سریع پیدا شود.
    """
    from .models import SiteSettings

    settings_obj = SiteSettings.get_solo()

    if request.method == 'POST':
        new_value = 'bypass_inquiry' in request.POST
        settings_obj.bypass_civil_registry_inquiry = new_value
        settings_obj.save()
        if new_value:
            messages.warning(
                request,
                '⚠️ حالت اضطراری فعال شد: استعلام ثبت‌احوال دیگر برای خرید بلیط لازم نیست. '
                'به محض رفع مشکل سرویس ثبت‌احوال، حتماً این گزینه را دوباره خاموش کنید.'
            )
        else:
            messages.success(request, '✅ استعلام ثبت‌احوال دوباره برای خرید بلیط الزامی شد.')
        return redirect('accounts:admin_emergency_settings')

    context = {'settings_obj': settings_obj}
    return render(request, 'accounts/admin_emergency_settings.html', context)


@login_required
@staff_member_required
def admin_site_settings(request):
    """
    تنظیمات عمومی سایت (کیف پول، رایگان بودن زیر ۱۵ سال، ...).

    عمداً از «تنظیمات اضطراری» جداست: آن صفحه یک کلید بحرانی و موقتی است،
    این‌جا تنظیماتی است که ممکن است مدت‌ها در یک حالت بماند.

    هر کارت فرم مستقل خودش را دارد و با فیلد مخفیِ `setting` مشخص می‌کند کدام
    گزینه را عوض می‌کند -- تا زدن یکی، بقیه را بی‌صدا خاموش نکند.
    """
    from .models import SiteSettings
    from django.db.models import Sum, Count
    from wallet.models import Wallet
    from tickets.models import Ticket, FREE_AGE_LIMIT

    settings_obj = SiteSettings.get_solo()

    TOGGLES = {
        'wallet_enabled': {
            'on': 'کیف پول فعال شد: کاربران می‌توانند از موجودی کیف پولشان برای خرید '
                  'بلیط استفاده کنند. (شارژ کیف پول کلید جداگانه‌ی خودش را دارد.)',
            'off': 'کیف پول غیرفعال شد: از این پس نه شارژ ممکن است و نه پرداخت از کیف پول. '
                   'موجودی کاربران دست‌نخورده باقی می‌ماند و با فعال کردن دوباره، قابل استفاده می‌شود.',
        },
        'wallet_charge_enabled': {
            'on': 'شارژ کیف پول فعال شد: کاربران می‌توانند از درگاه، کیف پولشان را شارژ کنند.',
            'off': 'شارژ کیف پول غیرفعال شد: کاربر نمی‌تواند پول تازه‌ای وارد کیف پول کند، '
                   'ولی موجودی فعلی‌اش همچنان برای خرید بلیط قابل استفاده است.',
        },
        'free_under_15': {
            'on': f'بلیط زیر {FREE_AGE_LIMIT} سال دوباره رایگان شد.',
            'off': f'رایگان بودن بلیط زیر {FREE_AGE_LIMIT} سال غیرفعال شد: از این پس '
                   'زیر ۱۵ ساله‌ها هم قیمت کامل بلوک را می‌پردازند. بلیط‌هایی که '
                   'قبلاً رایگان صادر شده‌اند تغییر نمی‌کنند.',
        },
    }

    if request.method == 'POST':
        field = request.POST.get('setting')
        if field not in TOGGLES:
            messages.error(request, 'درخواست نامعتبر است.')
            return redirect('accounts:admin_site_settings')

        new_value = request.POST.get('value') == 'on'
        if new_value != getattr(settings_obj, field):
            setattr(settings_obj, field, new_value)
            settings_obj.save()
            msg = TOGGLES[field]['on' if new_value else 'off']
            (messages.success if new_value else messages.warning)(request, msg)
        return redirect('accounts:admin_site_settings')

    # آماری که تصمیم‌گیری را برای ادمین روشن می‌کند: خاموش کردن کیف پول یعنی
    # این مقدار پول تا اطلاع ثانوی بلااستفاده می‌ماند.
    agg = Wallet.objects.filter(balance__gt=0).aggregate(total=Sum('balance'), cnt=Count('id'))
    # چند بلیط تا امروز به‌خاطر سن رایگان شده -- تا ادمین بداند این گزینه
    # روی چه حجمی اثر می‌گذارد.
    free_tickets = Ticket.objects.filter(
        price=0, age__isnull=False, age__lt=FREE_AGE_LIMIT,
        status__in=['paid', 'admin_assigned', 'vip_issued'],
    ).count()

    # اعداد نمایشی با رقم فارسی، هم‌شکل با بقیه‌ی سایت
    def _fa(n):
        return f'{n:,}'.translate(str.maketrans('0123456789,', '۰۱۲۳۴۵۶۷۸۹٬'))

    context = {
        'settings_obj': settings_obj,
        'wallets_with_balance': agg['cnt'] or 0,
        'total_wallet_balance': agg['total'] or 0,
        'free_age_limit': _fa(FREE_AGE_LIMIT),
        'free_tickets_so_far': _fa(free_tickets),
    }
    return render(request, 'accounts/admin_site_settings.html', context)
