from django import forms
from django.db.models import Q
from matches.models import Event
from .models import SupportTicket


def available_events(user):
    return Event.objects.filter(category__in=['theater', 'concert', 'event']).filter(
        Q(is_active=True) | Q(organizer_submission__owner=user)).order_by('title')


class SupportCreateForm(forms.ModelForm):
    body = forms.CharField(label='شرح درخواست', max_length=8000,
        widget=forms.Textarea(attrs={'rows': 6, 'placeholder': 'موضوع را با جزئیات بنویسید تا بهتر راهنمایی‌تان کنیم.'}))

    class Meta:
        model = SupportTicket
        fields = ['category', 'event', 'subject']
        labels = {'category': 'نوع تیکت', 'event': 'برنامه مرتبط', 'subject': 'موضوع تیکت'}
        widgets = {'subject': forms.TextInput(attrs={'placeholder': 'مثلاً: پیگیری بلیط یا فروش یک سانس'})}

    def __init__(self, *args, user, change_program=None, education_course=None, studio=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.education_course = education_course
        self.studio = studio
        self.fields['event'].queryset = available_events(user)
        self.fields['event'].empty_label = 'برنامه را انتخاب کنید'
        self.fields['category'].help_text = 'درخواست درباره نمایش، کنسرت یا رویداد را در بخش برنامه‌ها ثبت کنید؛ مسائل حساب و کیف پول در پشتیبانی کاربران قرار می‌گیرد.'
        self.fields['event'].help_text = 'برای تیکت مربوط به برنامه انتخاب این مورد ضروری است.'
        self.fields['body'].help_text = 'اگر درخواست مربوط به سانس یا بلیط مشخصی است، تاریخ اجرا و شماره پیگیری را بنویسید.'
        if change_program:
            self.fields['category'].disabled = True
            self.fields['event'].disabled = True
            self.fields['body'].help_text = 'بخش موردنظر و مقدار فعلی و پیشنهادی را دقیق بنویسید؛ برای تغییر قیمت، سانس، ردیف و شماره صندلی‌ها را مشخص کنید. ادمین تغییر را بررسی و اعمال می‌کند.'
        if education_course or studio:
            self.fields['category'].disabled = True
            self.fields['event'].disabled = True
            self.fields['event'].widget = forms.HiddenInput()
            self.fields['body'].help_text = 'این تیکت به آموزش یا پلاتوی انتخاب‌شده متصل است؛ درخواست تغییر یا مشکل رزرو را با جزئیات بنویسید.'

    def clean(self):
        data = super().clean()
        if data.get('category') == 'program' and not data.get('event') and not self.education_course and not self.studio:
            self.add_error('event', 'برای این نوع تیکت، برنامه مرتبط را انتخاب کنید.')
        if data.get('category') == 'general' and data.get('event'):
            self.add_error('event', 'برای انتخاب برنامه، نوع تیکت را «مربوط به برنامه» قرار دهید.')
        return data


class SupportReplyForm(forms.Form):
    body = forms.CharField(label='پیام شما', max_length=8000,
        widget=forms.Textarea(attrs={'rows': 5, 'placeholder': 'پاسخ یا توضیحات تکمیلی را اینجا بنویسید.'}))
