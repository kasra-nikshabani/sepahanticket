from django import forms
from django.utils import timezone
from accounts.management_forms import SessionDate
from accounts.submission_forms import PersianInteger, image_size, MultiImageField
from education.forms import StyledFields
from .models import Studio


class StudioForm(StyledFields, forms.ModelForm):
    version = forms.CharField(required=False, widget=forms.HiddenInput)
    hourly_price = PersianInteger(min_value=1,max_value=100000000,label='هزینهٔ پایهٔ هر ساعت (تومان)',help_text='قیمت پیشنهادی برای ساخت ساعت‌های تازه؛ قیمت هر ساعت در تقویم جداگانه قابل تعیین است.')
    area = PersianInteger(min_value=1,max_value=10000,required=False,label='مساحت (متر مربع)')
    capacity = PersianInteger(min_value=1,max_value=1000,required=False,label='ظرفیت افراد')
    cover = forms.ImageField(required=False,label='عکس اصلی',validators=[image_size],widget=forms.FileInput(attrs={'accept':'image/jpeg,image/png,image/webp'}))
    gallery = MultiImageField(required=False,label='عکس‌های بیشتر',validators=[image_size],help_text='حداکثر ۱۰ عکس، هر عکس تا ۸ مگابایت؛ تصاویر واقعی فضا را انتخاب کنید.')

    class Meta:
        model=Studio
        fields=['title','city','district','address','description','amenities','rules','area','capacity','hourly_price','cover']
        widgets={key:forms.Textarea(attrs={'rows':3}) for key in ['description','amenities','rules']}
        help_texts={'amenities':'کف، آینه، سیستم صوت، نور، تهویه، رختکن و امکانات قابل استفاده را بنویسید.',
                    'rules':'قوانین ورود، تعداد نفرات، تأخیر، جابه‌جایی و لغو رزرو را روشن بنویسید.'}

    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs); self.style_fields()
        if self.instance.created_at: self.fields['version'].initial=self.instance.updated_at.isoformat()

    def clean_gallery(self):
        files=self.cleaned_data['gallery']
        existing=self.instance.photos.filter(is_active=True).count() if self.instance.created_at else 0
        if len(files)+existing>20:
            raise forms.ValidationError('گالری می‌تواند حداکثر ۲۰ عکس فعال داشته باشد.')
        return files


WEEKDAYS=[('5','شنبه'),('6','یکشنبه'),('0','دوشنبه'),('1','سه‌شنبه'),('2','چهارشنبه'),('3','پنجشنبه'),('4','جمعه')]


class ScheduleForm(StyledFields,forms.Form):
    start_date=SessionDate(label='از تاریخ (شمسی)')
    end_date=SessionDate(label='تا تاریخ (شمسی)',help_text='تا ۹۰ روز. ساعت‌های قبلی تغییر نمی‌کنند؛ تداخل‌ها کنار گذاشته می‌شوند.')
    weekdays=forms.MultipleChoiceField(choices=WEEKDAYS,label='روزهای هفته',widget=forms.CheckboxSelectMultiple)
    start_time=forms.TimeField(label='ساعت آغاز',widget=forms.TimeInput(attrs={'type':'time','step':'3600'}))
    end_time=forms.TimeField(label='ساعت پایان',widget=forms.TimeInput(attrs={'type':'time','step':'3600'}),help_text='سرِ ساعت، در همان روز؛ مثلاً ۱۰:۰۰ تا ۲۲:۰۰.')
    price=PersianInteger(min_value=1,max_value=100000000,label='هزینهٔ هر ساعت این بازه (تومان)')

    def __init__(self,*args,**kwargs): super().__init__(*args,**kwargs); self.style_fields()

    def clean(self):
        d=super().clean()
        if d.get('start_date') and d.get('end_date'):
            if d['start_date']<timezone.localdate() or not 0<=(d['end_date']-d['start_date']).days<=89:
                self.add_error('end_date','بازهٔ آیندهٔ حداکثر ۹۰ روز را انتخاب کنید.')
        if d.get('start_time') and d.get('end_time'):
            if d['start_time'].minute or d['end_time'].minute or d['start_time'].second or d['end_time'].second or d['end_time']<=d['start_time']:
                self.add_error('end_time','ساعت‌های کامل و پایانِ بعد از آغاز را انتخاب کنید.')
        return d


class SlotForm(StyledFields,forms.Form):
    state=forms.ChoiceField(choices=[('open','قابل رزرو'),('closed','بسته'),('blocked','رزرو خارج از سایت')],label='وضعیت ساعت')
    price=PersianInteger(min_value=1,max_value=100000000,label='قیمت این ساعت (تومان)')
    note=forms.CharField(required=False,max_length=300,label='یادداشت خصوصی',help_text='فقط خودتان و ادمین می‌بینید؛ مثلاً نام رزروکنندهٔ خارج از سایت.')
    def __init__(self,*args,**kwargs): super().__init__(*args,**kwargs); self.style_fields()


class BookingForm(StyledFields,forms.Form):
    token=forms.UUIDField(widget=forms.HiddenInput)
    total=PersianInteger(min_value=1,max_value=1200000000,widget=forms.HiddenInput)
    renter_name=forms.CharField(max_length=150,label='نام رزروکننده')
    accept_rules=forms.BooleanField(label='قوانین پلاتو و زمان و مبلغ رزرو را خوانده‌ام و می‌پذیرم.')
    def __init__(self,*args,**kwargs): super().__init__(*args,**kwargs); self.style_fields()
