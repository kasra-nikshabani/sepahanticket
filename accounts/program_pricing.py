"""Staff tariff helpers and protected legacy organizer pricing routes."""
import re
from django import forms
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import transaction
from django.http import Http404
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods
from matches.models import (Match, MatchSeat, Row, Seat, MatchBlockPrice, MatchRowPrice,
                            MatchSeatPrice)
from payments.models import Payment
from tickets.models import Ticket
from tickets.reservation import SeatReservation
from .models import EventSubmission
from .submission_forms import PersianInteger, DIGITS
from .publication_policy import published_change_response


class PricingRowChoice(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        return f'{obj.block.name} · ردیف {obj.number}'.translate(str.maketrans('0123456789', '۰۱۲۳۴۵۶۷۸۹'))


class PricingForm(forms.Form):
    scope = forms.ChoiceField(label='اعمال روی', choices=[('session', 'فقط همین سانس'),
        ('future', 'همه سانس‌های آینده همین سالن')])
    target = forms.ChoiceField(label='نوع قیمت', choices=[('base', 'قیمت پایه سانس'),
        ('row', 'یک ردیف کامل'), ('seats', 'چند صندلی از یک ردیف')])
    row = PricingRowChoice(label='ردیف سالن', queryset=Row.objects.none(), required=False)
    seat_numbers = forms.CharField(label='شماره صندلی‌ها', required=False, max_length=1000,
        help_text='شماره‌ها را با ویرگول جدا کن؛ مثلاً ۲، ۴، ۶ یا بازه ۳-۸.')
    price = PersianInteger(label='قیمت (تومان)', required=False, min_value=0, max_value=999999999,
        help_text='برای بلیط رایگان، صفر وارد کن. قیمت صندلی اختصاصی بر قیمت ردیف اولویت دارد.')

    def __init__(self, *args, session, **kwargs):
        self.session = session
        super().__init__(*args, **kwargs)
        self.fields['row'].queryset = Row.objects.filter(block__stadium=session.stadium,
            seats__match_seats__match=session).select_related('block').distinct().order_by('block__order', 'block_id', 'number')
        for field in self.fields.values():
            field.widget.attrs['class'] = 'pricing-input'
        self.fields['price'].widget = forms.TextInput(attrs={'class': 'pricing-input', 'inputmode': 'numeric', 'dir': 'ltr'})
        self.fields['seat_numbers'].widget.attrs['placeholder'] = '۲، ۴، ۶ یا ۳-۸'

    def clean(self):
        data = super().clean()
        target, row = data.get('target'), data.get('row')
        if self.data.get('action') not in ('apply', 'reset'):
            raise ValidationError('نوع تغییر معتبر نیست.')
        if self.data.get('action') != 'reset' and data.get('price') is None and 'price' not in self.errors:
            self.add_error('price', 'قیمت را وارد کن؛ صفر به معنی رایگان است.')
        if target in ('row', 'seats') and row is None:
            self.add_error('row', 'ردیف مورد نظر را انتخاب کن.')
        if target == 'seats' and row:
            raw = data.get('seat_numbers', '').translate(DIGITS).replace('،', ',').replace('–', '-').replace('−', '-')
            numbers = set()
            try:
                for part in raw.split(','):
                    part = part.strip()
                    if not re.fullmatch(r'\d+(?:\s*-\s*\d+)?', part):
                        raise ValueError
                    bounds = [int(n.strip()) for n in part.split('-')]
                    start, end = bounds[0], bounds[-1]
                    if not 1 <= start <= end <= 9999 or end - start > 1000:
                        raise ValueError
                    numbers.update(range(start, end + 1))
                seats = list(Seat.objects.filter(row=row, number__in=numbers, match_seats__match=self.session))
                if not numbers or len(numbers) > 1000 or {seat.number for seat in seats} != numbers:
                    raise ValueError
                data['seats'] = seats
            except ValueError:
                self.add_error('seat_numbers', 'شماره‌ها باید متعلق به همین ردیف باشند؛ مثلاً ۲، ۴ یا ۳-۸. حداکثر ۱۰۰۰ صندلی.')
        return data


def change_prices(program, session, data, reset):
    """Serialize with reservation and issuance before changing any targeted tariff."""
    now = timezone.now()
    candidates = Match.objects.filter(event=program.published_event, pk=session.pk)
    if data['scope'] == 'future':
        candidates = Match.objects.filter(event=program.published_event, stadium=session.stadium,
            date_time__gt=now, is_cancelled=False)
    with transaction.atomic():
        sessions = list(candidates.select_for_update().order_by('pk'))
        if not sessions or any(item.date_time <= now or item.is_cancelled for item in sessions):
            raise ValidationError('برای سانس پایان‌یافته یا لغوشده نمی‌توان قیمت فروش را تغییر داد.')
        ids = [item.pk for item in sessions]
        inventory = MatchSeat.objects.filter(match_id__in=ids)
        if data['target'] == 'row':
            inventory = inventory.filter(seat__row=data['row'])
        elif data['target'] == 'seats':
            inventory = inventory.filter(seat_id__in=[seat.pk for seat in data['seats']])
        locked = list(inventory.select_for_update().order_by('pk'))
        reserved = SeatReservation.get_reserved_map([item.pk for item in locked])
        if any((item.reserved_until and item.reserved_until > now) or reserved.get(item.pk) for item in locked):
            raise ValidationError('بعضی از صندلی‌های این محدوده رزرو موقت دارند. پس از پایان رزرو یا تکمیل خرید دوباره تلاش کن.')
        if (Payment.objects.filter(match_id__in=ids, purpose='ticket_purchase', status='pending').exists()
                or Ticket.objects.filter(match_id__in=ids, status='pending').exists()):
            raise ValidationError('این سانس پرداخت در حال انجام دارد؛ قیمت پس از تعیین تکلیف پرداخت قابل تغییر است.')
        price = data.get('price')
        for item in sessions:
            if data['target'] == 'base':
                model, field, targets = MatchBlockPrice, 'block_id', list(item.stadium.blocks.values_list('pk', flat=True))
            elif data['target'] == 'row':
                model, field, targets = MatchRowPrice, 'row_id', [data['row'].pk]
            else:
                model, field, targets = MatchSeatPrice, 'seat_id', [seat.pk for seat in data['seats']]
            for pk in targets:
                key = {'match': item, field: pk}
                if reset:
                    model.objects.filter(**key).delete()
                else:
                    model.objects.update_or_create(**key, defaults={'price': price * 10})
        return len(sessions)


@login_required
@never_cache
@require_http_methods(['GET', 'POST'])
def program_pricing(request, submission_id, session_id=None):
    program = get_object_or_404(EventSubmission.objects.select_related('published_event'), pk=submission_id, owner=request.user)
    if not program.published_event_id or program.published_event.category == 'sport':
        raise Http404
    if session_id is not None and not program.published_event.sessions.filter(pk=session_id).exists():
        raise Http404
    return published_change_response(request, program)
