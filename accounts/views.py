# accounts/views.py
from datetime import timezone

from django.shortcuts import render, redirect
from django.contrib.auth import login, authenticate, logout
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required

from football_tickets import settings
from .forms import RegisterForm, LoginForm, PhoneLoginForm, OTPVerifyForm, PhoneRegisterForm
from .models import OTP
from .services import create_otp
from django.contrib.auth import get_user_model

User = get_user_model()


# ==========================================
#  ویوهای ورود با OTP
# ==========================================

def phone_login(request):
    """مرحله اول: وارد کردن شماره تلفن"""
    """مرحله اول: وارد کردن شماره تلفن"""

    # ===== اگر OTP غیرفعال است =====
    if not getattr(settings, 'OTP_ENABLED', False):
        messages.error(request, 'ورود با شماره تلفن در حال حاضر غیرفعال است. لطفاً از روش ورود معمولی استفاده کنید.')
        return redirect('accounts:login')
    if request.user.is_authenticated:
        return redirect('matches:home')

    if request.method == 'POST':
        form = PhoneLoginForm(request.POST)
        if form.is_valid():
            phone_number = form.cleaned_data['phone_number']

            # بررسی وجود کاربر با این شماره
            try:
                user = User.objects.get(phone_number=phone_number)
            except User.DoesNotExist:
                messages.error(request, 'کاربری با این شماره تلفن یافت نشد. لطفاً ابتدا ثبت‌نام کنید.')
                return redirect('accounts:register')

            # فقط کاربران معمولی مجاز به ورود با OTP هستند
            if user.user_type != 'normal':
                messages.error(request,
                               'این روش ورود فقط برای کاربران معمولی است. لطفاً از روش ورود با رمز عبور استفاده کنید.')
                return redirect('accounts:login')

            # ایجاد و ارسال کد OTP
            try:
                create_otp(phone_number)
                # ذخیره شماره در session برای مرحله بعد
                request.session['otp_phone'] = phone_number
                messages.success(request, 'کد تأیید به شماره شما ارسال شد.')
                return redirect('accounts:otp_verify')
            except Exception as e:
                messages.error(request, f'خطا در ارسال پیامک: {str(e)}')
                return render(request, 'accounts/phone_login.html', {'form': form})

    else:
        form = PhoneLoginForm()

    return render(request, 'accounts/phone_login.html', {'form': form})


def otp_verify(request):
    """مرحله دوم: تأیید کد OTP"""
    if not getattr(settings, 'OTP_ENABLED', False):
        messages.error(request, 'ورود با شماره تلفن در حال حاضر غیرفعال است.')
        return redirect('accounts:login')
    if request.user.is_authenticated:
        return redirect('matches:home')

    phone_number = request.session.get('otp_phone')
    if not phone_number:
        messages.error(request, 'لطفاً ابتدا شماره تلفن را وارد کنید.')
        return redirect('accounts:phone_login')

    if request.method == 'POST':
        form = OTPVerifyForm(request.POST)
        if form.is_valid():
            # ورود کاربر
            try:
                user = User.objects.get(phone_number=phone_number)
                login(request, user)

                # پاک کردن OTP استفاده شده
                OTP.objects.filter(phone_number=phone_number).delete()

                # پاک کردن session
                request.session.pop('otp_phone', None)

                messages.success(request, f'خوش آمدید {user.first_name}!')
                next_url = request.GET.get('next', 'matches:home')
                return redirect(next_url)

            except User.DoesNotExist:
                messages.error(request, 'کاربری با این شماره وجود ندارد.')
                return redirect('accounts:phone_login')
        else:
            # نمایش خطاهای فرم
            for field, errors in form.errors.items():
                for error in errors:
                    messages.error(request, error)
    else:
        form = OTPVerifyForm(initial={'phone_number': phone_number})

    # محاسبه زمان باقی‌مانده برای نمایش در صفحه
    try:
        latest_otp = OTP.objects.filter(phone_number=phone_number).latest('created_at')
        remaining_time = int((latest_otp.expires_at - timezone.now()).total_seconds())
        if remaining_time < 0:
            remaining_time = 0
    except OTP.DoesNotExist:
        remaining_time = 0

    return render(request, 'accounts/otp_verify.html', {
        'form': form,
        'phone_number': phone_number,
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

    # حذف کدهای قبلی
    OTP.objects.filter(phone_number=phone_number).delete()

    # ایجاد کد جدید
    try:
        create_otp(phone_number)
        messages.success(request, 'کد جدید به شماره شما ارسال شد.')
    except Exception as e:
        messages.error(request, f'خطا در ارسال پیامک: {str(e)}')

    return redirect('accounts:otp_verify')


# ==========================================
#  ویوهای ثبت‌نام و ورود معمولی (قبلی)
# ==========================================

def register_view(request):
    """صفحه ثبت‌نام کاربر جدید"""
    if request.user.is_authenticated:
        return redirect('matches:home')

    if request.method == 'POST':
        form = RegisterForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            messages.success(request, f'خوش آمدید {user.first_name}! ثبت‌نام شما با موفقیت انجام شد.')
            return redirect('matches:home')
        else:
            for field, errors in form.errors.items():
                for error in errors:
                    messages.error(request, f'{form.fields[field].label}: {error}')
    else:
        form = RegisterForm()

    return render(request, 'accounts/register.html', {'form': form})


def login_view(request):
    """صفحه ورود کاربر با نام کاربری و رمز عبور"""
    if request.user.is_authenticated:
        return redirect('matches:home')

    if request.method == 'POST':
        form = LoginForm(request, data=request.POST)
        if form.is_valid():
            username = form.cleaned_data.get('username')
            password = form.cleaned_data.get('password')
            user = authenticate(request, username=username, password=password)
            if user is not None:
                login(request, user)
                messages.success(request, f'خوش آمدید {user.first_name}!')
                next_url = request.GET.get('next', 'matches:home')
                return redirect(next_url)
        else:
            messages.error(request, 'نام کاربری یا رمز عبور اشتباه است.')

    form = LoginForm()
    return render(request, 'accounts/login.html', {'form': form})


@login_required
def logout_view(request):
    """خروج کاربر"""
    logout(request)
    messages.info(request, 'شما از حساب کاربری خود خارج شدید.')
    return redirect('matches:home')


@login_required
def profile_view(request):
    """نمایش پروفایل کاربر"""
    return render(request, 'accounts/profile.html', {'user': request.user})


@login_required
def edit_profile_view(request):
    """ویرایش پروفایل کاربر"""
    if request.method == 'POST':
        user = request.user
        user.first_name = request.POST.get('full_name', user.first_name)
        user.email = request.POST.get('email', user.email)
        user.phone_number = request.POST.get('phone_number', user.phone_number)
        user.save()
        messages.success(request, 'اطلاعات شما با موفقیت به‌روزرسانی شد.')
        return redirect('accounts:profile')
    return render(request, 'accounts/edit_profile.html', {'user': request.user})



@login_required
def dashboard_redirect(request):
    if request.user.user_type == 'admin':
        return redirect('admin_dashboard')      # نام URL پیشخوان ادمین
    elif request.user.user_type == 'vip':
        return redirect('tickets:vip_dashboard')  # نام URL پیشخوان VIP
    else:
        return redirect('matches:home')         # کاربر معمولی به همان صفحه خانه