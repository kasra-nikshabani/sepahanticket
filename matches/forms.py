from django import forms
from .models import Block
from .models import Match, Stadium
from .models import MatchCost, MatchRevenue


class BlockForm(forms.ModelForm):
    class Meta:
        model = Block
        fields = ['name', 'order', 'floor', 'zone_type', 'price', 'is_vip', 'is_class1', 'is_active']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'order': forms.NumberInput(attrs={'class': 'form-control'}),
            'floor': forms.Select(attrs={'class': 'form-select'}),
            'zone_type': forms.Select(attrs={'class': 'form-select'}),
            'price': forms.NumberInput(attrs={'class': 'form-control'}),
            'is_vip': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'is_class1': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }


class MatchForm(forms.ModelForm):
    """
    تاریخ و ساعت به دو ورودی جدا شکسته شده‌اند: تاریخ اجباری است ولی ساعت
    می‌تواند خالی بماند (وقتی هنوز اعلام نشده). چون مدل یک فیلد واحد
    date_time دارد، این دو در clean() به هم چسبانده می‌شوند و فلگ has_time
    مشخص می‌کند ساعتِ ذخیره‌شده واقعی است یا فقط جای‌پرکن.
    """
    match_date = forms.DateField(
        label='تاریخ برگزاری',
        widget=forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
        error_messages={'required': 'تاریخ مسابقه را وارد کنید.',
                        'invalid': 'فرمت تاریخ نامعتبر است.'},
    )
    match_time = forms.TimeField(
        label='ساعت برگزاری',
        required=False,
        widget=forms.TimeInput(attrs={'class': 'form-control', 'type': 'time'}),
        help_text='اختیاری — اگر خالی بماند، ساعت بازی هیچ‌جا نمایش داده نمی‌شود.',
        error_messages={'invalid': 'فرمت ساعت نامعتبر است.'},
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # فیلد اصلی مدل از فرم برداشته می‌شود؛ مقدارش را خودمان در clean می‌سازیم
        self.fields.pop('date_time', None)
        inst = kwargs.get('instance') or getattr(self, 'instance', None)
        if inst and inst.pk and inst.date_time:
            from django.utils import timezone as _tz
            local = _tz.localtime(inst.date_time)
            self.fields['match_date'].initial = local.date()
            # ساعتِ جای‌پرکن را در فرم نشان نمی‌دهیم تا ادمین فکر نکند واقعی است
            self.fields['match_time'].initial = local.time() if inst.has_time else None

    def clean(self):
        cleaned = super().clean()
        d = cleaned.get('match_date')
        t = cleaned.get('match_time')
        if d:
            from datetime import datetime, time as _time
            from django.utils import timezone as _tz
            # ساعت نامشخص -> ۱۲ ظهر ذخیره می‌شود (نه نیمه‌شب) تا پنجره‌ی
            # ±۱۲ ساعتِ گیت همان یک روز تقویمی را بپوشاند.
            naive = datetime.combine(d, t if t else _time(12, 0))
            cleaned['date_time'] = _tz.make_aware(naive, _tz.get_current_timezone())
            cleaned['has_time'] = t is not None
        return cleaned

    def save(self, commit=True):
        obj = super().save(commit=False)
        obj.date_time = self.cleaned_data['date_time']
        obj.has_time = self.cleaned_data['has_time']
        if commit:
            obj.save()
        return obj

    class Meta:
        model = Match
        fields = [
            'sport_type',
            'home_team', 'away_team',
            'home_team_logo', 'away_team_logo',
            'stadium', 'date_time', 'is_active', 'ticket_sales_enabled'
        ]
        widgets = {
            'sport_type': forms.Select(attrs={'class': 'form-select'}),
            'home_team': forms.TextInput(attrs={'class': 'form-control'}),
            'away_team': forms.TextInput(attrs={'class': 'form-control'}),
            'home_team_logo': forms.FileInput(attrs={'class': 'form-control'}),
            'away_team_logo': forms.FileInput(attrs={'class': 'form-control'}),
            'stadium': forms.Select(attrs={'class': 'form-select'}),
            'date_time': forms.DateTimeInput(attrs={'class': 'form-control', 'type': 'datetime-local'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'ticket_sales_enabled': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }
        # چون سایت به‌جای i18n جنگو (که LANGUAGE_CODE روی 'en-us' مونده) با
        # متن فارسیِ مستقیم کار می‌کنه، پیام‌های پیش‌فرض جنگو (مثل "This field
        # is required") انگلیسی می‌مونن مگر این‌که اینجا صریحاً فارسی بشن.
        labels = {
            'sport_type': 'رشته ورزشی',
            'home_team': 'تیم میزبان',
            'away_team': 'تیم میهمان',
            'home_team_logo': 'لوگوی تیم میزبان',
            'away_team_logo': 'لوگوی تیم میهمان',
            'stadium': 'ورزشگاه',
            'date_time': 'تاریخ و ساعت برگزاری',
            'is_active': 'فعال',
            'ticket_sales_enabled': 'فروش بلیط فعال',
        }
        error_messages = {
            'sport_type': {'required': 'رشته ورزشی را انتخاب کنید.'},
            'home_team': {'required': 'نام تیم میزبان را وارد کنید.'},
            'away_team': {'required': 'نام تیم میهمان را وارد کنید.'},
            'home_team_logo': {
                'invalid_image': 'فایل انتخاب‌شده یک تصویر معتبر نیست یا خراب است. لطفاً یک فایل JPG یا PNG آپلود کنید (فایل‌های HEIC از آیفون پشتیبانی نمی‌شوند).',
            },
            'away_team_logo': {
                'invalid_image': 'فایل انتخاب‌شده یک تصویر معتبر نیست یا خراب است. لطفاً یک فایل JPG یا PNG آپلود کنید (فایل‌های HEIC از آیفون پشتیبانی نمی‌شوند).',
            },
            'stadium': {'required': 'ورزشگاه را انتخاب کنید.'},
            'date_time': {
                'required': 'تاریخ و ساعت مسابقه را وارد کنید.',
                'invalid': 'فرمت تاریخ و ساعت نامعتبر است.',
            },
        }


from django import forms
from .models import Stadium


# matches/forms.py
class StadiumForm(forms.ModelForm):
    class Meta:
        model = Stadium
        fields = ['name', 'capacity', 'image']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'capacity': forms.NumberInput(attrs={'class': 'form-control', 'min': 0}),
            'image': forms.FileInput(attrs={'class': 'form-control'}),
        }
        labels = {
            'image': 'تصویر ورزشگاه',
        }


class MatchCostForm(forms.ModelForm):
    class Meta:
        model = MatchCost
        fields = ['description', 'amount']
        widgets = {
            'description': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'توضیح هزینه'
            }),
            'amount': forms.NumberInput(attrs={
                'class': 'form-control',
                'placeholder': 'مبلغ به ریال'
            }),
        }


class MatchRevenueForm(forms.ModelForm):
    class Meta:
        model = MatchRevenue
        fields = ['description', 'amount']
        widgets = {
            'description': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'توضیح درآمد'
            }),
            'amount': forms.NumberInput(attrs={
                'class': 'form-control',
                'placeholder': 'مبلغ به ریال'
            }),
        }
