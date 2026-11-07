"""Staff-confirmed initial sessions; no organizer mutations after publication."""
from django import forms
from django.core.exceptions import ValidationError
from django.utils import timezone
from matches.models import Match, MatchBlockPrice, Seat
from .submission_forms import PersianInteger
from .submission_schedule import session_plan, validate_opening_sessions


class InitialSalesApprovalForm(forms.Form):
    approve_opening_sales = forms.BooleanField(label='فروش سانس‌های انتخاب‌شده توسط برگزارکننده را هم فعال کن', required=False)
    opening_base_price = PersianInteger(label='قیمت پایه هر بلیط (تومان)', required=False, min_value=0, max_value=999999999,
        widget=forms.TextInput(attrs={'inputmode': 'numeric', 'dir': 'ltr', 'placeholder': 'مثلاً ۳۰۰۰۰۰'}),
        help_text='برای شروع فروش، قیمت عددی را مشخص کنید؛ صفر یعنی رایگان. قیمت سالن‌های دیگر تغییر نمی‌کند.')

    def clean(self):
        data = super().clean()
        if data.get('approve_opening_sales') and data.get('opening_base_price') is None:
            self.add_error('opening_base_price', 'برای باز کردن فروش، قیمت پایه بلیط را وارد کنید.')
        return data


def checked_schedule(submission, request):
    if 'opening_sessions' not in submission.data:
        return None
    data = submission.data
    plan = session_plan(data)
    selected = set(validate_opening_sessions(data['opening_sessions'], data))
    form = InitialSalesApprovalForm(request.POST)
    if not form.is_valid():
        raise ValidationError(next(iter(form.errors.values()))[0])
    approved = form.cleaned_data['approve_opening_sales']
    if approved and selected:
        if data.get('admission_mode') == 'quantity' or data.get('is_online'):
            raise ValidationError('شروع فروش این برنامه نیاز به آماده‌سازی فروش تعدادی یا آنلاین دارد؛ فعلاً فروش را بسته نگه دارید.')
        if any(item['date_time'] <= timezone.now() for item in plan if item['key'] in selected):
            raise ValidationError('فروش سانس گذشته را نمی‌توان باز کرد؛ انتخاب برگزارکننده را بازبینی کنید.')
        if submission.venue_id:
            available = Seat.objects.filter(row__block__stadium=submission.venue, is_available=True,
                row__is_active=True, row__block__is_active=True).exists()
            if not available:
                raise ValidationError('برای شروع فروش، سالن باید صندلی فعال و قابل فروش داشته باشد.')
        elif data.get('venue_mode') != 'custom':
            raise ValidationError('برای شروع فروش، سالن برنامه باید مشخص باشد.')
    # Each Match's creation signal creates its own seat inventory. Bound the batch.
    seat_count = (Seat.objects.filter(row__block__stadium=submission.venue).count() if submission.venue_id else
                  sum(number is not None for section in data.get('seat_layout', {}).get('sections', [])
                      for row in section.get('rows', []) for number in row.get('seats', [])))
    if seat_count * len(plan) > 300000:
        raise ValidationError('تعداد سانس‌ها و صندلی‌ها برای ساخت یک‌جای این بازه زیاد است؛ بازه را کوتاه‌تر کنید.')
    return {'plan': plan, 'selected': selected, 'approved': approved,
            'base_price': form.cleaned_data.get('opening_base_price')}


def create_initial_sessions(request, submission, schedule):
    if schedule is None or not submission.venue_id:
        return []
    result = []
    for item in schedule['plan']:
        selling = schedule['approved'] and item['key'] in schedule['selected']
        session = Match.objects.create(event=submission.published_event, stadium=submission.venue,
            date_time=item['date_time'], ticket_sales_enabled=selling, is_active=True, created_by=request.user)
        if schedule['base_price'] is not None:
            MatchBlockPrice.objects.bulk_create([MatchBlockPrice(match=session, block=block,
                price=schedule['base_price'] * 10) for block in submission.venue.blocks.all()])
        result.append(session)
    return result
