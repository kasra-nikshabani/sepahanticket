# accounts/views.py
from django.http import JsonResponse
from django.shortcuts import render, redirect
from django.contrib.auth import login, authenticate, logout
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.conf import settings
from django.utils import timezone
from django.contrib.auth import get_user_model

from .forms import RegisterForm, LoginForm, PhoneLoginForm, OTPVerifyForm, PhoneRegisterForm
from .models import OTP
from .services import create_otp, get_valid_otp

User = get_user_model()

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
            except Exception as e:
                messages.error(request, f'خطا در ارسال پیامک: {str(e)}')
        else:
            for error in form.errors.values():
                messages.error(request, error)
    else:
        form = PhoneLoginForm()

    return render(request, 'accounts/phone_login.html', {'form': form})


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

    form = OTPVerifyForm()  # مقداردهی اولیه برای نمایش در صورت GET

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

                    # تنظیم backend قبل از login
                    user.backend = 'accounts.backends.PhoneBackend'
                    login(request, user)

                    request.session.pop('otp_phone', None)
                    messages.success(request, f'خوش آمدید {user.get_full_name() or user.phone_number}!')
                    return redirect(request.GET.get('next', 'matches:home'))
                except User.DoesNotExist:
                    messages.error(request, 'کاربری با این شماره وجود ندارد.')
            else:
                # کد نامعتبر یا منقضی
                try:
                    latest_otp = OTP.objects.filter(phone_number=phone_number, is_used=False).latest('created_at')
                    latest_otp.increment_attempts()
                    if latest_otp.attempts >= 3:
                        messages.error(request, '❌ تعداد تلاش‌های ناموفق بیش از حد مجاز. کد جدید دریافت کنید.')
                    else:
                        messages.error(request, '❌ کد وارد شده صحیح نیست یا منقضی شده است.')
                except OTP.DoesNotExist:
                    messages.error(request, '❌ کد وارد شده صحیح نیست یا منقضی شده است.')
        else:
            # خطاهای فرم
            for field, errors in form.errors.items():
                for error in errors:
                    messages.error(request, f'{field}: {error}')

    # محاسبه زمان باقی‌مانده
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

    # ===== محدودیت درخواست مجدد (هر ۲ دقیقه) =====
    last_request = request.session.get('last_otp_request_time')
    if last_request:
        import time
        if time.time() - last_request < 120:  # ۲ دقیقه
            return JsonResponse({'status': 'error', 'message': '⏳ لطفاً ۲ دقیقه صبر کنید و دوباره تلاش کنید.'},
                                status=429)

    # حذف کدهای قبلی
    OTP.objects.filter(phone_number=phone_number).delete()

    # ایجاد کد جدید
    try:
        create_otp(phone_number)
        request.session['last_otp_request_time'] = time.time()
        return JsonResponse({'status': 'success', 'message': '✅ کد جدید با موفقیت ارسال شد.'})
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': f'❌ خطا در ارسال پیامک: {str(e)}'}, status=500)


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
            full_name = form.cleaned_data['full_name']

            if User.objects.filter(phone_number=phone_number).exists():
                messages.error(request, 'این شماره تلفن قبلاً ثبت شده است.')
                return render(request, 'accounts/phone_register.html', {'form': form})

            try:
                # ایجاد کاربر معمولی با شماره تلفن (بدون رمز عبور)
                user = User.objects.create_user(
                    username=phone_number,
                    phone_number=phone_number,
                    first_name=full_name,
                    is_active=False,
                    user_type='normal',
                    password=None  # بدون رمز عبور
                )
                create_otp(phone_number)
                request.session['otp_phone'] = phone_number
                messages.success(request, f'✅ کد تأیید به شماره {phone_number} ارسال شد.')
                return redirect('accounts:otp_verify')
            except Exception as e:
                messages.error(request, f'❌ خطا در ثبت‌نام: {str(e)}')
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


def login_view(request):
    """ورود با نام کاربری و رمز عبور (ادمین و VIP)"""
    if request.user.is_authenticated:
        return redirect('matches:home')

    if request.method == 'POST':
        form = LoginForm(request, data=request.POST)
        if form.is_valid():
            username = form.cleaned_data.get('username')
            password = form.cleaned_data.get('password')
            user = authenticate(request, username=username, password=password)
            if user is not None:
                # فقط ادمین و VIP اجازه ورود با رمز دارند
                if user.user_type in ['admin', 'vip']:
                    login(request, user)
                    messages.success(request, f'خوش آمدید {user.get_full_name() or user.username}!')
                    return redirect(request.GET.get('next', 'matches:home'))
                else:
                    messages.error(request,
                                   'این روش ورود فقط برای مدیران و کاربران ویژه است. لطفاً از ورود با شماره تلفن استفاده کنید.')
                    return redirect('accounts:phone_login')
            else:
                messages.error(request, 'نام کاربری یا رمز عبور اشتباه است.')
        else:
            messages.error(request, 'لطفاً اطلاعات را به درستی وارد کنید.')
    else:
        form = LoginForm()

    return render(request, 'accounts/login_password.html', {'form': form})


def logout_view(request):
    logout(request)
    messages.info(request, 'شما از حساب خود خارج شدید.')
    return redirect('matches:home')


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
