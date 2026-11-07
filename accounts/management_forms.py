from datetime import date
from django import forms
from django.utils import timezone
from matches.forms import EventForm, MatchForm
from matches.models import Stadium, Event, HomeBanner
from .models import SiteSettings, User
from .submission_forms import JalaliDate, PersianInteger, SeatLayoutField, CATEGORIES, image_size


class ManagedEventForm(EventForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['category'].choices = CATEGORIES


class SessionDate(JalaliDate):
    def to_python(self, value):
        result = super().to_python(value)
        return date.fromisoformat(result) if result else None

    def prepare_value(self, value):
        return super().prepare_value(value.isoformat() if isinstance(value, date) else value)


class ManagedSessionForm(MatchForm):
    match_date = SessionDate(label='تاریخ برگزاری (شمسی)', help_text='مثلاً ۱۴۰۵/۰۸/۲۰', widget=forms.TextInput(attrs={'placeholder': '۱۴۰۵/۰۸/۲۰'}))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['event'].queryset = Event.objects.exclude(category='sport')
        self.fields['stadium'].label = 'سالن یا محل اجرا'
        self.fields['ticket_sales_enabled'].initial = False
        if self.instance.pk:
            self.fields['match_date'].initial = timezone.localtime(self.instance.date_time).date().isoformat()

    def clean(self):
        cleaned = super().clean()
        if cleaned.get('ticket_sales_enabled'):
            if cleaned.get('date_time') and cleaned['date_time'] <= timezone.now():
                self.add_error('ticket_sales_enabled', 'فروش سانس گذشته را نمی‌توان فعال کرد.')
            elif self.instance.is_cancelled or not cleaned.get('is_active') or not getattr(cleaned.get('event'), 'is_active', False):
                self.add_error('ticket_sales_enabled', 'برای شروع فروش، برنامه و سانس باید فعال و لغونشده باشند.')
        return cleaned

class VenueForm(forms.ModelForm):
    capacity = PersianInteger(label='ظرفیت اعلام‌شده', min_value=1, max_value=100000)
    base_price = PersianInteger(label='قیمت پایه صندلی (تومان)', min_value=0, max_value=999999999, initial=0)
    seat_layout = SeatLayoutField(label='چیدمان سالن', required=False, widget=forms.Textarea())

    class Meta:
        model = Stadium
        fields = ['name', 'city', 'address', 'capacity', 'image']
        labels = {'name': 'نام سالن', 'capacity': 'ظرفیت اعلام‌شده'}
        widgets = {'address': forms.Textarea(attrs={'rows': 3})}


class ManagedUserForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ['first_name', 'last_name', 'phone_number', 'email', 'is_active', 'is_phone_verified']
        labels = {'is_active': 'حساب فعال است', 'is_phone_verified': 'شماره موبایل تأیید شده است'}


class ManagedSettingsForm(forms.ModelForm):
    class Meta:
        model = SiteSettings
        fields = ['block_foreign_ips', 'wallet_enabled', 'wallet_charge_enabled', 'withdrawal_enabled']


class SalesFilterForm(forms.Form):
    q = forms.CharField(label='جست‌وجو', required=False, max_length=100,
                        widget=forms.TextInput(attrs={'placeholder': 'نام، شماره موبایل یا شماره بلیط'}))
    status = forms.ChoiceField(label='وضعیت بلیط', required=False, choices=[
        ('all', 'همه وضعیت‌ها'), ('paid', 'پرداخت‌شده'), ('pending', 'در انتظار پرداخت'),
        ('cancelled', 'لغوشده'), ('admin_assigned', 'تخصیص مدیریت')])
    event = forms.ModelChoiceField(label='برنامه', required=False,
        queryset=Event.objects.exclude(category='sport').order_by('title'), empty_label='همه برنامه‌ها')
    start = SessionDate(label='تاریخ خرید از', required=False,
        widget=forms.TextInput(attrs={'placeholder': '۱۴۰۵/۰۸/۰۱', 'dir': 'ltr'}))
    end = SessionDate(label='تاریخ خرید تا', required=False,
        widget=forms.TextInput(attrs={'placeholder': '۱۴۰۵/۰۸/۳۰', 'dir': 'ltr'}))

    def clean(self):
        cleaned = super().clean()
        if cleaned.get('start') and cleaned.get('end') and cleaned['start'] > cleaned['end']:
            self.add_error('end', 'تاریخ پایان باید برابر یا پس از تاریخ آغاز باشد.')
        return cleaned


class HomeBannerForm(forms.ModelForm):
    image = forms.ImageField(label='تصویر بنر', validators=[image_size],
        error_messages={'required': 'تصویر بنر را انتخاب کن.', 'invalid_image': 'فایل انتخاب‌شده تصویر معتبری نیست.'},
        help_text='تصویر افقی، پیشنهاد: ۲۰۰۰ × ۴۲۰ پیکسل. JPG، PNG یا WebP؛ حداکثر ۸ مگابایت.',
        widget=forms.ClearableFileInput(attrs={'accept': 'image/jpeg,image/png,image/webp', 'data-banner-upload': ''}))
    order = PersianInteger(label='ترتیب نمایش', min_value=0, max_value=9999, initial=0,
        help_text='عدد کوچک‌تر زودتر نمایش داده می‌شود؛ مثلاً ۱، ۲ و ۳.')

    class Meta:
        model = HomeBanner
        fields = ['title', 'image', 'event', 'order', 'is_active']
        help_texts = {'title': 'نام برای شناسایی و متن جایگزین تصویر؛ روی عکس نوشته‌ای اضافه نمی‌شود.',
            'event': 'اختیاری؛ با کلیک روی بنر، صفحه این برنامه باز می‌شود.',
            'is_active': 'با غیرفعال‌کردن، بنر از اسلایدر پنهان می‌شود و قابل فعال‌سازی دوباره است.'}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['event'].queryset = Event.objects.exclude(category='sport').order_by('title')
        self.fields['event'].empty_label = 'بدون لینک به برنامه'

    def clean_image(self):
        image = self.cleaned_data['image']
        if getattr(image, 'image', None) and image.image.format not in ('JPEG', 'PNG', 'WEBP'):
            raise forms.ValidationError('تصویر باید در قالب JPG، PNG یا WebP باشد.')
        return image
