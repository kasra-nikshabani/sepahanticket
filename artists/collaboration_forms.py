from urllib.parse import urlsplit
from django import forms
from django.utils import timezone
from accounts.management_forms import SessionDate
from accounts.submission_forms import PersianInteger
from matches.models import Event
from .models import CollaborationOpportunity, CollaborationApplication, CollaborationMessage, CollaborationReport


def owned_events(user):
    rows = Event.objects.filter(category__in=['theater', 'concert', 'event'])
    return rows if user.is_staff else rows.filter(organizer_submission__owner=user)


class PersianNumberInput(forms.TextInput):
    def format_value(self, value):
        result = super().format_value(value)
        return result.translate(str.maketrans('0123456789', '۰۱۲۳۴۵۶۷۸۹')) if result is not None else result


class AccessibleFormMixin:
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name, field in self.fields.items():
            field.widget.attrs['aria-describedby'] = f'{name}-help {name}-errors'


class OpportunityForm(forms.ModelForm):
    deadline = SessionDate(label='مهلت درخواست (شمسی)', widget=forms.TextInput(attrs={'placeholder': '۱۴۰۵/۰۸/۲۰', 'dir': 'ltr'}))
    positions = PersianInteger(label='تعداد افراد موردنیاز', min_value=1, max_value=100,
        widget=PersianNumberInput(attrs={'inputmode': 'numeric'}))
    pay_min = PersianInteger(label='حداقل دستمزد (تومان)', required=False, min_value=1, max_value=999999999999,
        widget=PersianNumberInput(attrs={'inputmode': 'numeric'}))
    pay_max = PersianInteger(label='حداکثر دستمزد (تومان)', required=False, min_value=1, max_value=999999999999,
        widget=PersianNumberInput(attrs={'inputmode': 'numeric'}))
    version = forms.CharField(required=False, widget=forms.HiddenInput)

    class Meta:
        model = CollaborationOpportunity
        fields = ['title', 'project_name', 'organizer_name', 'event', 'role', 'city', 'location', 'positions',
            'description', 'requirements', 'schedule', 'deadline', 'pay_type', 'pay_min', 'pay_max', 'pay_details']
        widgets = {name: forms.Textarea(attrs={'rows': 4}) for name in ('description', 'requirements', 'schedule')}
        labels = {'event': 'برنامهٔ مرتبط در دیدآور (اختیاری)'}
        help_texts = {
            'title': 'مثلاً «دستیار صحنه برای یک نمایش در اصفهان».',
            'organizer_name': 'این نام عمومی است؛ شمارهٔ تماس حسابتان منتشر نمی‌شود.',
            'event': 'فقط برنامه‌های متعلق به شما قابل انتخاب‌اند. پروژه می‌تواند هنوز به مرحلهٔ فروش نرسیده باشد.',
            'description': 'وظایف، فضای پروژه و انتظارات را روشن توضیح دهید؛ حداقل ۲۰ نویسه.',
            'requirements': 'مهارت‌ها، تجربه و نمونه‌کار موردنیاز؛ پذیرش افراد تازه‌کار را هم مشخص کنید.',
            'schedule': 'روزها و ساعت‌های تمرین، زمان آغاز و پایان همکاری را بنویسید.',
            'pay_details': 'مثلاً مبلغ برای کل پروژه یا هر اجرا، زمان پرداخت و نوع همکاری. در همکاری بدون دستمزد، شرایط را شفاف بنویسید.'}

    def __init__(self, *args, user, partial=False, **kwargs):
        self.partial = partial
        super().__init__(*args, **kwargs)
        self.fields['event'].queryset = owned_events(user).order_by('-created_at')
        if not self.instance._state.adding:
            self.fields['version'].initial = self.instance.updated_at.isoformat()
        for name, field in self.fields.items():
            if partial and name != 'title':
                field.required = False
            field.widget.attrs.update({'class': 'artist-input', 'aria-describedby': f'{name}-help {name}-errors'})

    def clean_deadline(self):
        value = self.cleaned_data['deadline']
        if value and value < timezone.localdate():
            raise forms.ValidationError('مهلت ارسال درخواست باید امروز یا پس از امروز باشد.')
        return value

    def clean_description(self):
        value = self.cleaned_data['description'].strip()
        if not self.partial and len(value) < 20:
            raise forms.ValidationError('شرح همکاری را با حداقل ۲۰ نویسه بنویسید.')
        return value

    def clean(self):
        data = super().clean()
        if self.partial:
            data['positions'] = data.get('positions') or 1
            data['role'] = data.get('role') or 'other'
            data['pay_type'] = data.get('pay_type') or 'negotiable'
        if not self.instance._state.adding and data.get('positions') is not None:
            occupied = self.instance.applications.filter(status__in=['selected', 'accepted']).count()
            if data['positions'] < occupied:
                self.add_error('positions', 'تعداد همکاران نمی‌تواند کمتر از افراد منتخب و تأییدشدهٔ فعلی باشد.')
        if data.get('pay_type') == CollaborationOpportunity.Pay.RANGE:
            for name in ('pay_min', 'pay_max'):
                if data.get(name) is None and not self.partial:
                    self.add_error(name, 'برای دستمزد مشخص، این مبلغ را وارد کنید.')
            if data.get('pay_min') and data.get('pay_max') and data['pay_max'] < data['pay_min']:
                self.add_error('pay_max', 'حداکثر مبلغ نباید کمتر از حداقل باشد.')
        else:
            data['pay_min'] = data['pay_max'] = None
        return data


class ApplicationForm(AccessibleFormMixin, forms.ModelForm):
    class Meta:
        model = CollaborationApplication
        fields = ['introduction', 'availability', 'portfolio_url']
        widgets = {'introduction': forms.Textarea(attrs={'rows': 5})}
        help_texts = {'introduction': 'تجربهٔ مرتبط و انگیزهٔ همکاری را بنویسید؛ حداقل ۲۰ نویسه.',
            'portfolio_url': 'نشانی کامل با https://. پروفایل هنری شما نیز همراه درخواست ارسال می‌شود.',
            'availability': 'مثلاً عصرهای شنبه تا چهارشنبه؛ زمان‌بندی پروژه را بررسی کنید.'}

    def clean_introduction(self):
        value = self.cleaned_data['introduction'].strip()
        if len(value) < 20:
            raise forms.ValidationError('معرفی را با حداقل ۲۰ نویسه بنویسید.')
        return value

    def clean_portfolio_url(self):
        value = self.cleaned_data['portfolio_url']
        if value and urlsplit(value).scheme not in ('http', 'https'):
            raise forms.ValidationError('پیوند نمونه‌کار باید با http:// یا https:// آغاز شود.')
        return value


class CollaborationMessageForm(AccessibleFormMixin, forms.ModelForm):
    class Meta:
        model = CollaborationMessage
        fields = ['body']
        widgets = {'body': forms.Textarea(attrs={'rows': 3, 'placeholder': 'دربارهٔ همین فرصت همکاری گفت‌وگو کنید…'})}


class ReportForm(AccessibleFormMixin, forms.ModelForm):
    class Meta:
        model = CollaborationReport
        fields = ['reason']
        widgets = {'reason': forms.Textarea(attrs={'rows': 3})}


class OpportunityReviewForm(forms.Form):
    note = forms.CharField(label='پیام بررسی / نتیجهٔ رسیدگی', required=False, max_length=2000,
        widget=forms.Textarea(attrs={'rows': 3}))
