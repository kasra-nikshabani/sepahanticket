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
