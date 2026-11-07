from django import forms
from django.core.exceptions import ValidationError
from django.core.validators import FileExtensionValidator
from accounts.submission_forms import image_size
from matches.models import Event
from .models import ArtistProfile, ArtistCredit


class ArtistProfileForm(forms.ModelForm):
    class Meta:
        model = ArtistProfile
        fields = ['display_name', 'discipline', 'specialty', 'city', 'biography', 'avatar', 'cover', 'website', 'portfolio_url',
            'skills', 'experience', 'preferred_role', 'looking_for_work']
        widgets = {'biography': forms.Textarea(attrs={'rows': 6}),
            'skills': forms.Textarea(attrs={'rows': 3}), 'experience': forms.Textarea(attrs={'rows': 4}),
            'avatar': forms.ClearableFileInput(attrs={'accept': 'image/jpeg,image/png,image/webp'}),
            'cover': forms.ClearableFileInput(attrs={'accept': 'image/jpeg,image/png,image/webp'})}
        help_texts = {'display_name': 'نامی که مخاطبان شما را با آن می‌شناسند. تغییر این نام پس از تأیید، نیاز به بررسی دوباره دارد.',
            'specialty': 'مثلاً بازیگر تئاتر و مدرس بیان؛ حداکثر ۱۶۰ نویسه.',
            'biography': 'از تجربه‌ها، مسیر هنری و کارهایی که دوست دارید بنویسید. این متن عمومی است.',
            'avatar': 'عکس مربع؛ JPG، PNG یا WebP، حداکثر ۸ مگابایت.',
            'cover': 'تصویر افقی؛ پیشنهاد ۱۶۰۰ × ۵۰۰ پیکسل، حداکثر ۸ مگابایت.',
            'website': 'نشانی کامل با https://؛ فقط پیوندی را بنویسید که می‌خواهید عمومی باشد.',
            'portfolio_url': 'پیوند صفحهٔ نمونه‌کار یا ویدئوهای شما.',
            'skills': 'مهارت‌های حرفه‌ای خود را بنویسید؛ این بخش در پروفایل عمومی دیده می‌شود.',
            'experience': 'نام پروژه‌ها، نقش و مدت همکاری‌های قبلی؛ از درج اطلاعات تماس خصوصی خودداری کنید.',
            'preferred_role': 'برای پیشنهاد فرصت‌های مرتبط با تخصص شما استفاده می‌شود.',
            'looking_for_work': 'این وضعیت در صفحهٔ عمومی شما نمایش داده می‌شود.'}

    def __init__(self, *args, **kwargs):
        self.submit_review = kwargs.pop('submit_review', False)
        super().__init__(*args, **kwargs)
        for name, field in self.fields.items():
            field.widget.attrs.update({'class': 'artist-input', 'aria-describedby': f'{name}-help {name}-errors'})
            if name == 'looking_for_work':
                field.widget.attrs['class'] = 'artist-work-checkbox'
            if name in ('avatar', 'cover'):
                field.validators += [image_size, FileExtensionValidator(['jpg', 'jpeg', 'png', 'webp'])]

    def clean_display_name(self):
        name = self.cleaned_data['display_name'].strip()
        if len(name) < 2:
            raise ValidationError('نام هنری را با حداقل ۲ نویسه وارد کنید.')
        return name

    def clean_website(self):
        return self._public_link('website')

    def clean_portfolio_url(self):
        return self._public_link('portfolio_url')

    def _public_link(self, name):
        from urllib.parse import urlsplit
        value = self.cleaned_data[name]
        if value and urlsplit(value).scheme not in ('http', 'https'):
            raise ValidationError('نشانی وب با http:// یا https:// وارد کنید.')
        return value

    def clean(self):
        cleaned = super().clean()
        if self.submit_review and len(cleaned.get('biography', '').strip()) < 20:
            self.add_error('biography', 'برای بررسی پروفایل، معرفی کوتاهی از فعالیت هنری خود بنویسید؛ حداقل ۲۰ نویسه.')
        return cleaned


class CreditForm(forms.ModelForm):
    class Meta:
        model = ArtistCredit
        fields = ['event', 'role']
        labels = {'event': 'برنامه', 'role': 'نقش هنرمند'}
        help_texts = {'role': 'مثلاً بازیگر، کارگردان، خواننده یا نوازنده. ارتباط برای تأیید به هنرمند ارسال می‌شود.'}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['event'].queryset = Event.objects.filter(category__in=['theater', 'concert', 'event']).order_by('-created_at')


class ArtistReviewForm(forms.Form):
    note = forms.CharField(label='پیام برای هنرمند', required=False, max_length=2000,
        widget=forms.Textarea(attrs={'rows': 3}), help_text='برای درخواست اصلاح، دقیق بنویسید چه اطلاعاتی نیاز به تکمیل دارد.')
