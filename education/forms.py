from pathlib import Path

from django import forms
from django.conf import settings
from django.core.files.uploadedfile import UploadedFile
from django.utils import timezone

from accounts.management_forms import SessionDate
from accounts.submission_forms import PersianInteger, image_size
from .models import Course, Lesson


class StyledFields:
    def style_fields(self):
        for name, field in self.fields.items():
            if not field.widget.is_hidden:
                field.widget.attrs.update({'class': 'edu-input', 'aria-describedby': f'id_{name}_help id_{name}_errors'})


class CourseForm(StyledFields, forms.ModelForm):
    version = forms.CharField(required=False, widget=forms.HiddenInput)
    price_toman = PersianInteger(min_value=0, max_value=1000000000, label='قیمت کل آموزش (تومان)', initial=0, help_text='قیمت کل دوره یا همهٔ جلسات کلاس؛ برای آموزش رایگان صفر بنویسید.')
    capacity = PersianInteger(min_value=1, max_value=10000, required=False, label='ظرفیت کلاس', help_text='هر ثبت‌نام یک جای کلاس را رزرو می‌کند.')
    start_date = SessionDate(required=False, label='روز آغاز (شمسی)', widget=forms.TextInput(attrs={'placeholder': '۱۴۰۵/۰۸/۲۰'}))
    end_date = SessionDate(required=False, label='روز پایان (شمسی)', widget=forms.TextInput(attrs={'placeholder': '۱۴۰۵/۰۹/۲۰'}))
    registration_deadline = SessionDate(required=False, label='آخرین روز ثبت‌نام (شمسی)')
    poster = forms.ImageField(required=False, label='تصویر معرفی', validators=[image_size], widget=forms.FileInput(attrs={'accept': 'image/jpeg,image/png,image/webp'}))

    class Meta:
        model = Course
        fields = ['kind', 'title', 'teacher_name', 'academy', 'subject', 'level', 'summary', 'description', 'outcomes', 'prerequisites', 'poster', 'price_toman',
                  'city', 'address', 'schedule', 'start_date', 'start_time', 'end_date', 'end_time', 'registration_deadline', 'capacity']
        labels = {'kind': 'نوع آموزش', 'teacher_name': 'نام مدرس برای نمایش عمومی'}
        widgets = {'description': forms.Textarea(attrs={'rows': 6}), 'summary': forms.Textarea(attrs={'rows': 2}),
                   'outcomes': forms.Textarea(attrs={'rows': 4}), 'prerequisites': forms.Textarea(attrs={'rows': 3}),
                   'schedule': forms.Textarea(attrs={'rows': 3}), 'start_time': forms.TimeInput(format='%H:%M', attrs={'type': 'time'}),
                   'end_time': forms.TimeInput(format='%H:%M', attrs={'type': 'time'})}
        help_texts = {'kind': 'دورهٔ ضبط‌شده برای تماشای داخل سایت؛ کلاس حضوری برای ثبت‌نام با ظرفیت محدود.',
                      'teacher_name': 'فقط این نام به هنرجوها نمایش داده می‌شود؛ نام حساب شما خودکار منتشر نمی‌شود.',
                      'outcomes': 'سرفصل‌ها و مهارت‌هایی که هنرجو در پایان به دست می‌آورد.',
                      'prerequisites': 'دانش، تجربه یا وسایل موردنیاز؛ اگر ندارد، بنویسید «بدون پیش‌نیاز».',
                      'schedule': 'مثلاً هشت جلسه، شنبه‌ها و دوشنبه‌ها، ساعت ۱۸ تا ۲۰.'}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.style_fields()
        if not self.instance._state.adding:
            self.initial['version'] = self.instance.updated_at.isoformat()
        if self.instance.submitted_at:
            self.fields['kind'].disabled = True
        self.fields['kind'].initial = self.instance.kind or 'recorded'

    def clean(self):
        cleaned = super().clean()
        if cleaned.get('kind') == 'class':
            start, end = cleaned.get('start_date'), cleaned.get('end_date')
            if start and end and end < start:
                self.add_error('end_date', 'روز پایان نمی‌تواند پیش از آغاز باشد.')
            if start and end == start and cleaned.get('start_time') and cleaned.get('end_time') and cleaned['end_time'] <= cleaned['start_time']:
                self.add_error('end_time', 'ساعت پایان باید پس از ساعت آغاز باشد.')
            if start and cleaned.get('registration_deadline') and cleaned['registration_deadline'] > start:
                self.add_error('registration_deadline', 'مهلت ثبت‌نام باید تا روز آغاز کلاس باشد.')
            if cleaned.get('capacity') and self.instance.pk and not self.instance._state.adding:
                if cleaned['capacity'] < self.instance.enrollments.filter(status='active').count():
                    self.add_error('capacity', 'ظرفیت نمی‌تواند کمتر از ثبت‌نام‌های فعال باشد.')
        else:
            for key in ('city', 'address', 'schedule'):
                cleaned[key] = ''
            for key in ('start_date', 'start_time', 'end_date', 'end_time', 'registration_deadline', 'capacity'):
                cleaned[key] = None
        return cleaned


class LessonForm(StyledFields, forms.ModelForm):
    source = forms.FileField(required=False, label='ویدئوی درس', widget=forms.FileInput(attrs={'accept': 'video/mp4,video/webm'}),
                             help_text='MP4 یا WebM؛ فایل خصوصی می‌ماند و پس از آماده‌سازی داخل سایت پخش می‌شود.')
    order = PersianInteger(min_value=0, max_value=9999, label='ترتیب درس', initial=1)

    class Meta:
        model = Lesson
        fields = ['chapter', 'title', 'description', 'order', 'is_preview', 'is_active', 'source']
        widgets = {'description': forms.Textarea(attrs={'rows': 4})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['source'].required = self.instance._state.adding
        self.style_fields()

    def clean_source(self):
        source = self.cleaned_data.get('source')
        if not isinstance(source, UploadedFile):
            return source
        maximum = getattr(settings, 'EDUCATION_MAX_VIDEO_BYTES', 1024 * 1024 * 1024)
        if source.size > maximum:
            raise forms.ValidationError(f'حجم ویدئو نباید بیشتر از {maximum // (1024*1024)} مگابایت باشد.')
        extension = Path(source.name).suffix.lower()
        header = source.read(16); source.seek(0)
        if not ((extension == '.mp4' and header[4:8] == b'ftyp') or (extension == '.webm' and header[:4] == b'\x1aE\xdf\xa3')):
            raise forms.ValidationError('یک فایل ویدئوی MP4 یا WebM معتبر انتخاب کنید.')
        return source


class EnrollmentForm(StyledFields, forms.Form):
    learner_name = forms.CharField(max_length=150, min_length=3, label='نام و نام خانوادگی هنرجو', help_text='این نام در فهرست هنرجویان به مدرس نمایش داده می‌شود.')
    price = forms.CharField(widget=forms.HiddenInput)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.style_fields()


class ReviewForm(StyledFields, forms.Form):
    version = forms.CharField(widget=forms.HiddenInput)
    note = forms.CharField(required=False, max_length=2000, label='پیام به مدرس', widget=forms.Textarea(attrs={'rows': 4}))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.style_fields()
