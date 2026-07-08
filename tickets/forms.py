# tickets/forms.py
from django import forms
from django.contrib.auth import get_user_model
from matches.models import Match, Block, Row, MatchSeat
from tickets.models import VIPQuota, DiscountCode

User = get_user_model()


class BulkTicketForm(forms.Form):
    match = forms.ModelChoiceField(
        queryset=Match.objects.filter(is_active=True),
        label='مسابقه',
        widget=forms.Select(attrs={'class': 'form-control-custom'})
    )

    users = forms.ModelMultipleChoiceField(
        queryset=User.objects.filter(user_type='vip'),
        label='کاربران ویژه',
        widget=forms.SelectMultiple(attrs={'class': 'form-control-custom', 'size': '8'})
    )

    # ===== تغییر: به‌جای row، block =====
    block = forms.ModelChoiceField(
        queryset=Block.objects.all(),  # ← حذف فیلتر is_active
        label='بلوک (جایگاه)',
        widget=forms.Select(attrs={'class': 'form-control-custom'})
    )

    seat_count_per_user = forms.IntegerField(
        min_value=1,
        initial=1,
        label='تعداد بلیط برای هر کاربر',
        widget=forms.NumberInput(attrs={'class': 'form-control-custom'})
    )

    def clean(self):
        cleaned_data = super().clean()
        match = cleaned_data.get('match')
        block = cleaned_data.get('block')
        users = cleaned_data.get('users')
        count_per_user = cleaned_data.get('seat_count_per_user')

        if match and block and users and count_per_user:
            # محاسبه تعداد صندلی‌های خالی در کل بلوک
            total_needed = users.count() * count_per_user
            available_seats = MatchSeat.objects.filter(
                match=match,
                seat__row__block=block,
                is_available=True
            ).count()

            if available_seats < total_needed:
                raise forms.ValidationError(
                    f'تعداد صندلی‌های موجود در بلوک "{block.name}" ({available_seats}) کافی نیست. '
                    f'به {total_needed} صندلی نیاز است.'
                )
        return cleaned_data


class VIPQuotaForm(forms.ModelForm):
    class Meta:
        model = VIPQuota
        fields = ['user', 'match', 'quota']
        widgets = {
            'user': forms.Select(attrs={'class': 'form-select'}),
            'match': forms.Select(attrs={'class': 'form-select'}),
            'quota': forms.NumberInput(attrs={'class': 'form-control', 'min': 0}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # فقط کاربران VIP را نمایش بده
        self.fields['user'].queryset = User.objects.filter(user_type='vip')
        # فقط مسابقات فعال را نمایش بده
        self.fields['match'].queryset = Match.objects.filter(is_active=True)


class DiscountCodeForm(forms.ModelForm):
    class Meta:
        model = DiscountCode
        fields = ['code', 'match', 'block', 'discount_percent', 'max_uses', 'is_active', 'expires_at']
        widgets = {
            'code': forms.TextInput(attrs={'class': 'form-control', 'dir': 'ltr', 'placeholder': 'SUMMER20'}),
            'match': forms.Select(attrs={'class': 'form-select', 'id': 'id_match'}),
            'block': forms.Select(attrs={'class': 'form-select', 'id': 'id_block'}),
            'discount_percent': forms.NumberInput(attrs={'class': 'form-control', 'min': 0, 'max': 100}),
            'max_uses': forms.NumberInput(attrs={'class': 'form-control', 'min': 1}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'expires_at': forms.DateTimeInput(attrs={'class': 'form-control', 'type': 'datetime-local'}),
        }
        labels = {
            'code': 'کد تخفیف',
            'match': 'مسابقه',
            'block': 'بلوک (اختیاری)',
            'discount_percent': 'درصد تخفیف',
            'max_uses': 'حداکثر استفاده',
            'is_active': 'فعال',
            'expires_at': 'تاریخ انقضا (اختیاری)',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # فقط مسابقات فعال را نمایش بده
        self.fields['match'].queryset = Match.objects.filter(is_active=True).order_by('-date_time')
        self.fields['block'].queryset = Block.objects.filter(is_active=True)
        self.fields['block'].required = False
        self.fields['expires_at'].required = False

        # اگر مسابقه‌ای وجود نداشت، پیام مناسب نمایش بده
        if not self.fields['match'].queryset.exists():
            self.fields['match'].empty_label = "هیچ مسابقه‌ای یافت نشد. ابتدا یک مسابقه ایجاد کنید."
        else:
            self.fields['match'].empty_label = "یک مسابقه انتخاب کنید..."
