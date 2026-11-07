"""Validated, organizer-facing five-step proposal forms."""
from datetime import date
import jdatetime
from django import forms
from django.core.exceptions import ValidationError
from matches.models import Stadium
from .venue_layout import validate_layout, layout_capacity
from .submission_schedule import validate_opening_sessions

CATEGORIES = [('theater', 'نمایش'), ('concert', 'کنسرت'), ('event', 'رویداد')]
ADMISSION_MODES = [('seated', 'انتخاب صندلی'), ('quantity', 'انتخاب تعداد بلیط')]
DIGITS = str.maketrans('۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩', '01234567890123456789')


class PersianInteger(forms.IntegerField):
    def to_python(self, value):
        return super().to_python(str(value).translate(DIGITS).replace('٬', '').replace(',', '') if value is not None else value)


class JalaliDate(forms.CharField):
    def to_python(self, value):
        value = super().to_python(value).translate(DIGITS)
        if not value:
            return ''
        try:
            year, month, day = map(int, value.replace('-', '/').split('/'))
            if not 1300 <= year <= 1600:
                raise ValueError
            return jdatetime.date(year, month, day).togregorian().isoformat()
        except (ValueError, TypeError):
            raise ValidationError('تاریخ شمسی معتبر وارد کن؛ برای مثال ۱۴۰۵/۰۸/۲۰.')

    def prepare_value(self, value):
        if value and '-' in str(value):
            try:
                return jdatetime.date.fromgregorian(date=date.fromisoformat(value)).strftime('%Y/%m/%d').translate(str.maketrans('0123456789', '۰۱۲۳۴۵۶۷۸۹'))
            except ValueError:
                pass
        return value


def image_size(upload):
    if upload.size > 8 * 1024 * 1024:
        raise ValidationError('حجم هر تصویر باید حداکثر ۸ مگابایت باشد.')


class MultiImageInput(forms.ClearableFileInput):
    allow_multiple_selected = True


class MultiImageField(forms.ImageField):
    widget = MultiImageInput

    def clean(self, data, initial=None):
        if not data:
            return []
        files = data if isinstance(data, (tuple, list)) else [data]
        if len(files) > 10:
            raise ValidationError('حداکثر ۱۰ عکس صحنه انتخاب کن.')
        return [super(MultiImageField, self).clean(item, None) for item in files]


class StepForm(forms.Form):
    def __init__(self, *args, **kwargs):
        self.partial = kwargs.pop('partial', False)
        lock_category = kwargs.pop('lock_category', False)
        super().__init__(*args, **kwargs)
        if lock_category and 'category' in self.fields:
            self.fields['category'].disabled = True
            self.fields['category'].help_text = 'نوع برنامه پس از اولین ارسال ثابت است؛ برای نوع دیگری، برنامه جدید بساز.'
        for name, field in self.fields.items():
            field.required_for_submission = field.required
            if self.partial and name != 'category':
                field.required = False
        self.configure_fields()
        for name, field in self.fields.items():
            field.widget.attrs['aria-describedby'] = f'{name}-help {name}-errors'
            field.widget.attrs.setdefault('class', 'wizard-input')
            if isinstance(field, PersianInteger):
                field.widget = forms.TextInput(attrs={**field.widget.attrs, 'inputmode': 'numeric', 'data-persian-number': '', 'dir': 'ltr'})
            if self.is_bound and name in self.errors:
                field.widget.attrs['aria-invalid'] = 'true'

    def configure_fields(self):
        pass


class VenueChoice(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        label = f'{obj.name} — {obj.city}' if obj.city else obj.name
        return label.translate(str.maketrans('0123456789', '۰۱۲۳۴۵۶۷۸۹'))


class SeatLayoutField(forms.CharField):
    def clean(self, value):
        return validate_layout(value)

    def prepare_value(self, value):
        import json
        return json.dumps(value, ensure_ascii=False) if isinstance(value, dict) else value


class BasicForm(StepForm):
    category = forms.ChoiceField(label='نوع برنامه', choices=CATEGORIES, widget=forms.RadioSelect, initial='theater')
    prefix = forms.CharField(label='پیشوند نام', max_length=50, initial='نمایش', help_text='مثلاً نمایش، کنسرت یا کارگاه؛ پیش از نام برنامه نمایش داده می‌شود.')
    title = forms.CharField(label='نام برنامه', max_length=200, help_text='نام اصلی را بدون تاریخ و نام سالن بنویس.')
    tagline = forms.CharField(label='عبارت معرفی', required=False, max_length=200, help_text='یک جمله کوتاه که حال‌وهوای برنامه را معرفی کند.')
    poster = forms.ImageField(label='پوستر برنامه', required=False, validators=[image_size], help_text='پیشنهاد: تصویر عمودی ۱۰۰۰ × ۱۳۰۰ پیکسل. JPG، PNG یا WebP؛ حداکثر ۸ مگابایت.', widget=forms.FileInput(attrs={'accept': 'image/jpeg,image/png,image/webp', 'data-upload-preview': ''}))
    cover = forms.ImageField(label='بنر افقی', required=False, validators=[image_size], help_text='پیشنهاد: ۲۰۰۰ × ۴۲۰ پیکسل. تصویر کامل در بالای صفحه برنامه قرار می‌گیرد.', widget=forms.FileInput(attrs={'accept': 'image/jpeg,image/png,image/webp', 'data-upload-preview': ''}))
    photos = MultiImageField(label='عکس‌های صحنه یا برنامه', required=False, validators=[image_size], help_text='تا ۱۰ عکس؛ حداکثر ۸ مگابایت برای هر عکس. عکس‌های جدید به مجموعه قبلی اضافه می‌شوند.', widget=MultiImageInput(attrs={'accept': 'image/jpeg,image/png,image/webp', 'data-upload-preview': ''}))
    teaser = forms.FileField(label='تیزر برنامه', required=False, help_text='اختیاری؛ MP4 یا WebM، حداکثر ۳۰ مگابایت.', widget=forms.FileInput(attrs={'accept': 'video/mp4,video/webm'}))
    is_online = forms.BooleanField(label='این برنامه آنلاین برگزار می‌شود', required=False, help_text='اگر اجرای زنده اینترنتی است، این گزینه را فعال کن.')

    def clean_teaser(self):
        upload = self.cleaned_data.get('teaser')
        if upload:
            if upload.size > 30 * 1024 * 1024:
                raise ValidationError('حجم تیزر باید حداکثر ۳۰ مگابایت باشد.')
            head = upload.read(16)
            upload.seek(0)
            name = upload.name.lower()
            if not ((name.endswith('.mp4') and head[4:8] == b'ftyp') or (name.endswith('.webm') and head[:4] == b'\x1aE\xdf\xa3')):
                raise ValidationError('یک فایل ویدئویی معتبر با فرمت MP4 یا WebM انتخاب کن.')
        return upload


class DetailsForm(StepForm):
    start_date = JalaliDate(label='تاریخ آغاز', max_length=10, help_text='تاریخ شمسی، مانند ۱۴۰۵/۰۸/۲۰.', widget=forms.TextInput(attrs={'placeholder': '۱۴۰۵/۰۸/۲۰', 'dir': 'ltr'}))
    end_date = JalaliDate(label='تاریخ پایان', max_length=10, help_text='برای اجرای یک‌روزه، تاریخ آغاز و پایان را یکسان وارد کن.', widget=forms.TextInput(attrs={'placeholder': '۱۴۰۵/۰۸/۲۰', 'dir': 'ltr'}))
    time = forms.TimeField(label='ساعت اجرا', widget=forms.TimeInput(format='%H:%M', attrs={'type': 'time'}))
    second_time = forms.TimeField(label='ساعت اجرای دوم', required=False, widget=forms.TimeInput(format='%H:%M', attrs={'type': 'time'}), help_text='فقط اگر در هر روز اجرای دیگری داری.')
    third_time = forms.TimeField(label='ساعت اجرای سوم', required=False, widget=forms.TimeInput(format='%H:%M', attrs={'type': 'time'}))
    opening_sessions = forms.JSONField(label='سانس‌های شروع فروش', required=False, initial=list, widget=forms.HiddenInput,
        help_text='فقط سانس‌هایی را انتخاب کنید که می‌خواهید پس از تأیید ادمین برای فروش باز شوند؛ بقیه بسته می‌مانند.')
    duration = PersianInteger(label='مدت اجرا (دقیقه)', min_value=1, max_value=1440, help_text='زمان تقریبی برنامه، با احتساب استراحت.')
    summary = forms.CharField(label='خلاصه برنامه', max_length=1000, widget=forms.Textarea(attrs={'rows': 3}), help_text='در چند جمله، مخاطب را با برنامه آشنا کن.')
    description = forms.CharField(label='توضیحات کامل', required=False, max_length=10000, widget=forms.Textarea(attrs={'rows': 5}), help_text='درباره محتوا، نکات حضور و تجربه‌ای که مخاطب خواهد داشت بنویس.')
    admission_mode = forms.ChoiceField(label='روش دریافت بلیط', choices=ADMISSION_MODES, initial='seated', required=False, widget=forms.RadioSelect)
    ticket_capacity = PersianInteger(label='ظرفیت بلیط هر اجرا', required=False, min_value=1, max_value=100000, help_text='تعداد کل بلیط قابل فروش برای هر نوبت اجرا؛ مثلاً ۲۰۰ نفر. شماره صندلی به بلیط اختصاص داده نمی‌شود.')
    venue_mode = forms.ChoiceField(label='انتخاب محل اجرا', choices=[('preset', 'سالن‌های آماده سامانه'), ('custom', 'سالن من در فهرست نیست')], initial='preset', widget=forms.RadioSelect)
    venue_preset = VenueChoice(label='سالن آماده', queryset=Stadium.objects.order_by('city', 'name', 'pk'), required=False, empty_label='یک سالن انتخاب کن', help_text='چیدمان سالن‌های آماده توسط ادمین تنظیم شده و در این فرم قابل تغییر نیست.')
    city = forms.CharField(label='شهر مخاطبان', max_length=100, help_text='برای برنامه حضوری، شهر محل اجرا را بنویس.')
    venue = forms.CharField(label='سالن یا محل اجرا', required=False, max_length=200, help_text='نام سالن یا، برای برنامه آنلاین، نام بستر برگزاری.')
    address = forms.CharField(label='نشانی محل اجرا', required=False, max_length=500, widget=forms.Textarea(attrs={'rows': 2}))
    seat_layout = SeatLayoutField(label='چیدمان صندلی‌های سالن جدید', required=False, widget=forms.HiddenInput, help_text='چیدمان را با طراح سالن تنظیم کن.')
    themes = forms.CharField(label='زمینه‌های مرتبط', max_length=300, help_text='مثلاً تئاتر، موسیقی یا آموزش؛ موارد را با ویرگول جدا کن.')
    styles = forms.CharField(label='سبک‌ها', max_length=300, help_text='مثلاً کمدی، درام، پاپ یا کلاسیک.')
    tags = forms.CharField(label='دسته‌بندی‌ها و برچسب‌ها', required=False, max_length=300, help_text='مثلاً خانوادگی، کودک یا اجرای تجربی.')
    minimum_age = PersianInteger(label='حداقل سن مخاطب', required=False, min_value=0, max_value=99, help_text='اگر محدودیت سنی ندارد، خالی بگذار.')
    women_only = forms.BooleanField(label='ویژه بانوان', required=False)

    def configure_fields(self):
        self.is_online = bool(self.initial.get('is_online'))
        self.is_quantity = ((self.data.get('admission_mode') if self.is_bound else None) or self.initial.get('admission_mode') or 'seated') == 'quantity'
        self.fields['ticket_capacity'].required = self.is_quantity and not self.partial
        self.fields['ticket_capacity'].required_for_submission = self.is_quantity
        mode = (self.data.get('venue_mode') if self.is_bound else self.initial.get('venue_mode')) or 'preset'
        if self.is_online or mode == 'preset':
            for name in ('city', 'venue', 'address'):
                self.fields[name].required = False
                self.fields[name].required_for_submission = False
        if self.is_online:
            self.initial['venue_mode'] = 'preset'
            for name in ('venue_mode', 'venue_preset', 'seat_layout'):
                self.fields[name].required = False
                self.fields[name].disabled = True
        elif mode == 'custom':
            for name in ('venue', 'address'):
                self.fields[name].required = not self.partial
                self.fields[name].required_for_submission = True

    def clean_seat_layout(self):
        return validate_layout(self.cleaned_data.get('seat_layout'))

    def clean(self):
        data = super().clean()
        data['admission_mode'] = data.get('admission_mode') or self.initial.get('admission_mode') or 'seated'
        if data.get('start_date') and data.get('end_date') and data['end_date'] < data['start_date']:
            self.add_error('end_date', 'تاریخ پایان نمی‌تواند قبل از تاریخ آغاز باشد.')
        if 'opening_sessions' in self.data or 'opening_sessions' in self.initial:
            try:
                schedule_data = {**self.initial, **{key: value for key, value in data.items() if value not in (None, '')}}
                data['opening_sessions'] = validate_opening_sessions(data.get('opening_sessions') if data.get('opening_sessions') is not None else [], schedule_data, self.partial)
            except ValidationError as error:
                self.add_error('opening_sessions', error)
        times = [data.get(key) for key in ('time', 'second_time', 'third_time') if data.get(key)]
        if len(times) != len(set(times)):
            self.add_error('time', 'ساعت اجراها باید متفاوت باشد.')
        mode = data.get('venue_mode') or self.initial.get('venue_mode') or 'preset'
        if self.is_online:
            data.update(venue_mode='online', venue_preset=None)
            # Retain an offline draft layout so switching back does not erase the work.
        elif mode == 'preset':
            venue = data.get('venue_preset')
            if self.partial and 'venue_preset' not in self.data and self.initial.get('venue_preset'):
                venue = self.fields['venue_preset'].queryset.filter(pk=self.initial['venue_preset']).first()
                data['venue_preset'] = venue
            if not venue and not self.partial:
                self.add_error('venue_preset', 'یک سالن آماده انتخاب کن یا گزینه سالن جدید را بزن.')
            if venue:
                data.update(venue=venue.name, city=venue.city, address=venue.address)
                capacity = data.get('ticket_capacity')
                if self.is_quantity and capacity and venue.capacity > 0 and capacity > venue.capacity:
                    self.add_error('ticket_capacity', 'ظرفیت بلیط نمی‌تواند بیشتر از ظرفیت ثبت‌شده سالن باشد.')
        elif mode == 'custom':
            data['venue_preset'] = None
            if not self.partial and not self.is_quantity and layout_capacity(data.get('seat_layout') or {}) < 1:
                self.add_error('seat_layout', 'برای سالن جدید، حداقل یک صندلی در چیدمان قرار بده.')
        data['venue_mode'] = mode if not self.is_online else 'online'
        return data


class CreditsForm(StepForm):
    credits = forms.CharField(label='عوامل و هنرمندان', max_length=5000, widget=forms.Textarea(attrs={'rows': 8}), help_text='هر نقش و نام را در یک سطر بنویس؛ مثلاً کارگردان: مریم احمدی یا خواننده: علی رضایی.')
    related_pages = forms.CharField(label='برگه‌ها و پیوندهای مرتبط', required=False, max_length=2000, widget=forms.Textarea(attrs={'rows': 3}), help_text='نشانی وب‌سایت یا صفحه رسمی گروه؛ هر مورد در یک سطر.')


class SalesForm(StepForm):
    ticket_price = PersianInteger(label='قیمت هر بلیط (تومان)', required=False, min_value=0, max_value=1000000000, help_text='یک قیمت برای هر بلیط بدون شماره صندلی؛ برای برنامه رایگان، صفر وارد کن.')
    prices = forms.CharField(label='بها یا قیمت‌های بلیط (تومان)', max_length=2000, widget=forms.Textarea(attrs={'rows': 3}), help_text='قیمت پایه و استثناها را مشخص کن؛ مثلاً قیمت پایه: ۲۵۰٬۰۰۰ تومان، ردیف اول: ۳۵۰٬۰۰۰ تومان، صندلی‌های ۳ تا ۶ ردیف دوم: ۴۰۰٬۰۰۰ تومان. پس از انتشار و تعریف سانس‌ها، در «برنامه‌های من» قیمت هر ردیف و صندلی را تنظیم کن. این بخش برای بررسی اولیه است.')
    general_discount = forms.BooleanField(label='تخفیف عمومی', required=False)
    general_percent = PersianInteger(label='درصد تخفیف عمومی', required=False, min_value=1, max_value=100)
    group_discount = forms.BooleanField(label='تخفیف گروهی', required=False)
    group_percent = PersianInteger(label='درصد تخفیف گروهی', required=False, min_value=1, max_value=100)
    group_minimum = PersianInteger(label='حداقل تعداد بلیط گروهی', required=False, min_value=2, max_value=1000)
    loyalty_discount = forms.BooleanField(label='تخفیف وفاداری', required=False)
    loyalty_percent = PersianInteger(label='درصد تخفیف وفاداری', required=False, min_value=1, max_value=100)
    student_discount = forms.BooleanField(label='تخفیف دانشجویی', required=False)
    student_percent = PersianInteger(label='درصد تخفیف دانشجویی', required=False, min_value=1, max_value=100)
    discount_notes = forms.CharField(label='شرایط تخفیف‌ها', required=False, max_length=2000, widget=forms.Textarea(attrs={'rows': 3}), help_text='شرایط استفاده و مدارک لازم را توضیح بده؛ مثلاً ارائه کارت دانشجویی معتبر.')
    license_image = forms.ImageField(label='تصویر مجوز ارشاد', required=False, validators=[image_size], widget=forms.FileInput(attrs={'accept': 'image/jpeg,image/png,image/webp', 'data-upload-preview': ''}), help_text='برای نمایش و کنسرت، مجوز ارشاد الزامی است. می‌توانی پیش‌نویس را بدون مجوز ذخیره کنی؛ پیش از ارسال برای تأیید، تصویر خوانای مجوز را بارگذاری کن. حداکثر ۸ مگابایت؛ فقط خودت و ادمین به آن دسترسی دارند.')

    def configure_fields(self):
        requires_license = self.initial.get('category') in ('theater', 'concert')
        self.fields['license_image'].required = requires_license and not self.partial
        self.fields['license_image'].required_for_submission = requires_license
        self.fields['license_image'].error_messages['required'] = 'برای ارسال نمایش یا کنسرت، تصویر مجوز ارشاد را بارگذاری کن.'
        self.is_quantity = self.initial.get('admission_mode') == 'quantity'
        self.fields['ticket_price'].required = self.is_quantity and not self.partial
        self.fields['ticket_price'].required_for_submission = self.is_quantity
        self.fields['prices'].required = not self.is_quantity and not self.partial
        self.fields['prices'].required_for_submission = not self.is_quantity

    def clean(self):
        data = super().clean()
        for kind in ('general', 'group', 'loyalty', 'student'):
            key = kind + '_percent'
            if not self.partial and data.get(kind + '_discount') and not data.get(key):
                self.add_error(key, 'درصد این تخفیف را مشخص کن.')
            if not data.get(kind + '_discount'):
                data[key] = None
        if not self.partial and data.get('group_discount') and not data.get('group_minimum'):
            self.add_error('group_minimum', 'حداقل تعداد بلیط را مشخص کن.')
        if not data.get('group_discount'):
            data['group_minimum'] = None
        return data


class FinalForm(StepForm):
    organizer_role = forms.CharField(label='نقش من در برنامه', max_length=200, help_text='مثلاً تهیه‌کننده، مدیر گروه یا مسئول برگزاری.')
    reviewer_notes = forms.CharField(label='توضیحات برای تیم دیدآور', required=False, max_length=3000, widget=forms.Textarea(attrs={'rows': 4}), help_text='اطلاعاتی که لازم است هنگام بررسی درخواست بدانیم؛ این متن عمومی نیست.')
    confirm = forms.BooleanField(label='اطلاعات را بازبینی کرده‌ام و مسئولیت صحت آن‌ها را می‌پذیرم.', required=False, help_text='برای ارسال نهایی، تأیید صحت اطلاعات ضروری است. انتشار و شروع فروش نیازمند تأیید و تنظیم اجراهاست.')

FORMS = {1: BasicForm, 2: DetailsForm, 3: CreditsForm, 4: SalesForm, 5: FinalForm}
STEPS = ['اطلاعات پایه', 'جزئیات اجرا', 'عوامل و پیوندها', 'بها و فروش', 'بازبینی و ارسال']
