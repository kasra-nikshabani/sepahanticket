# accounts/forms.py
from django import forms
from django.contrib.auth.forms import UserCreationForm, AuthenticationForm
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.utils import timezone
import re
from .models import OTP

User = get_user_model()


# ==========================================
#  فرم‌های ثبت‌نام و ورود معمولی
# ==========================================

class RegisterForm(UserCreationForm):
    """فرم ثبت‌نام کاربر جدید"""
    full_name = forms.CharField(
        max_length=200,
        required=True,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'نام و نام خانوادگی'}),
        label="نام و نام خانوادگی"
    )
    national_code = forms.CharField(
        max_length=10,
        min_length=10,
        required=True,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'کد ملی (۱۰ رقم)'}),
        label="کد ملی",
        help_text="کد ملی باید ۱۰ رقم باشد."
    )
    phone_number = forms.CharField(
        max_length=11,
        min_length=11,
        required=True,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'شماره موبایل (۰۹۱۲۳۴۵۶۷۸۹)'}),
        label="شماره موبایل"
    )
    username = forms.CharField(
        max_length=150,
        required=True,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'نام کاربری'}),
        label="نام کاربری"
    )
    password1 = forms.CharField(
        widget=forms.PasswordInput(attrs={'class': 'form-control', 'placeholder': 'رمز عبور'}),
        label="رمز عبور"
    )
    password2 = forms.CharField(
        widget=forms.PasswordInput(attrs={'class': 'form-control', 'placeholder': 'تکرار رمز عبور'}),
        label="تکرار رمز عبور"
    )

    class Meta:
        model = User
        fields = ('username', 'full_name', 'national_code', 'phone_number', 'password1', 'password2')

    def clean_national_code(self):
        national_code = self.cleaned_data.get('national_code')
        if not re.match(r'^\d{10}$', national_code):
            raise ValidationError('کد ملی باید ۱۰ رقم باشد.')
        if User.objects.filter(national_code=national_code).exists():
            raise ValidationError('این کد ملی قبلاً ثبت شده است.')
        return national_code

    def clean_phone_number(self):
        phone = self.cleaned_data.get('phone_number')
        if not re.match(r'^09\d{9}$', phone):
            raise ValidationError('شماره موبایل باید با ۰۹ شروع شود و ۱۱ رقم باشد.')
        if User.objects.filter(phone_number=phone).exists():
            raise ValidationError('این شماره موبایل قبلاً ثبت شده است.')
        return phone

    def save(self, commit=True):
        user = super().save(commit=False)
        user.first_name = self.cleaned_data.get('full_name')
        user.national_code = self.cleaned_data.get('national_code')
        user.phone_number = self.cleaned_data.get('phone_number')
        user.user_type = 'normal'  # کاربر معمولی
        if commit:
            user.save()
        return user


class LoginForm(AuthenticationForm):
    """فرم ورود کاربر با نام کاربری و رمز عبور"""
    username = forms.CharField(
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'نام کاربری'}),
        label="نام کاربری"
    )
    password = forms.CharField(
        widget=forms.PasswordInput(attrs={'class': 'form-control', 'placeholder': 'رمز عبور'}),
        label="رمز عبور"
    )
    error_messages = {
        'invalid_login': 'نام کاربری یا رمز عبور اشتباه است.',
        'inactive': 'حساب کاربری شما غیرفعال است.',
    }


# ==========================================
#  فرم‌های ورود با شماره تلفن و OTP
# ==========================================

class PhoneLoginForm(forms.Form):
    """فرم ورود شماره تلفن (مرحله اول)"""
    phone_number = forms.CharField(
        max_length=11,
        min_length=11,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'شماره موبایل را وارد کنید (مثلاً 09123456789)',
            'dir': 'ltr',
            'inputmode': 'numeric'
        }),
        label="شماره موبایل"
    )

    def clean_phone_number(self):
        phone = self.cleaned_data.get('phone_number')
        phone = phone.replace(' ', '').replace('-', '')
        if not phone.isdigit():
            raise ValidationError('شماره موبایل باید فقط شامل اعداد باشد.')
        if len(phone) != 11:
            raise ValidationError('شماره موبایل باید ۱۱ رقم باشد.')
        if not phone.startswith('09'):
            raise ValidationError('شماره موبایل باید با ۰۹ شروع شود.')
        return phone


# accounts/forms.py
class OTPVerifyForm(forms.Form):
    otp_code = forms.CharField(
        max_length=4,
        min_length=4,
        label='کد تأیید',
        widget=forms.HiddenInput(attrs={
            'id': 'id_otp_code',
            'autocomplete': 'one-time-code',
            'inputmode': 'numeric',
        })
    )

    def clean_otp_code(self):
        code = self.cleaned_data['otp_code']
        if not code.isdigit():
            raise ValidationError('کد باید عددی باشد.')
        if len(code) != 4:
            raise ValidationError('کد باید دقیقاً ۴ رقم باشد.')
        return code


PERSIAN_NAME_RE = re.compile(r'^[؀-ۿ‌ ]+$')


def is_valid_iranian_national_code(code):
    """اعتبارسنجی واقعی کد ملی ایران (رقم کنترلی)، نه فقط چک ۱۰ رقمی بودن."""
    if not re.match(r'^\d{10}$', code):
        return False
    if len(set(code)) == 1:  # مثل 0000000000 یا 1111111111
        return False
    check_digit = int(code[9])
    total = sum(int(code[i]) * (10 - i) for i in range(9))
    remainder = total % 11
    return check_digit == remainder if remainder < 2 else check_digit == 11 - remainder


class PhoneRegisterForm(forms.Form):
    """فرم ثبت‌نام با شماره تلفن"""
    first_name = forms.CharField(
        max_length=100,
        required=True,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'نام'}),
        label="نام"
    )
    last_name = forms.CharField(
        max_length=100,
        required=True,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'نام خانوادگی'}),
        label="نام خانوادگی"
    )
    phone_number = forms.CharField(
        max_length=11,
        required=True,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'شماره موبایل را وارد کنید',
            'dir': 'ltr',
            'inputmode': 'numeric'
        }),
        label="شماره موبایل"
    )
    national_code = forms.CharField(
        max_length=10,
        min_length=10,
        required=True,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'کد ملی (۱۰ رقم)',
            'dir': 'ltr',
            'inputmode': 'numeric',
        }),
        label="کد ملی"
    )
    gender = forms.ChoiceField(
        choices=User.GENDER_CHOICES,
        required=True,
        widget=forms.RadioSelect(attrs={'class': 'form-check-input'}),
        label="جنسیت"
    )

    def _clean_persian_name(self, field_name, label):
        value = (self.cleaned_data.get(field_name) or '').strip()
        if not value:
            raise ValidationError(f'{label} را وارد کنید.')
        if not PERSIAN_NAME_RE.match(value):
            raise ValidationError(f'{label} باید فقط با حروف فارسی نوشته شود.')
        return value

    def clean_first_name(self):
        return self._clean_persian_name('first_name', 'نام')

    def clean_last_name(self):
        return self._clean_persian_name('last_name', 'نام خانوادگی')

    def clean_phone_number(self):
        phone = self.cleaned_data.get('phone_number')
        phone = phone.replace(' ', '').replace('-', '')
        if not phone.isdigit() or len(phone) != 11 or not phone.startswith('09'):
            raise ValidationError('شماره موبایل معتبر نیست (۱۱ رقم و با ۰۹ شروع شود).')
        if User.objects.filter(phone_number=phone).exists():
            raise ValidationError('این شماره موبایل قبلاً ثبت شده است.')
        return phone

    def clean_national_code(self):
        code = (self.cleaned_data.get('national_code') or '').strip()
        if not code.isdigit() or not is_valid_iranian_national_code(code):
            raise ValidationError('کد ملی وارد شده معتبر نیست.')
        if User.objects.filter(national_code=code).exists():
            raise ValidationError('این کد ملی قبلاً ثبت شده است.')
        return code
