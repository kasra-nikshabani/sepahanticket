from datetime import datetime, timedelta
from django.db import transaction
from django.db.models import F
from django.urls import reverse
from django.utils import timezone
from accounts.notifications import notify
from wallet.models import Wallet, is_wallet_enabled
from .models import Booking, Studio, StudioSlot


def public_studios():
    return Studio.objects.filter(status='published', owner__is_active=True)


def lock_studio(studio_id):
    # Start with a write: serializes schedule/payment changes on SQLite too.
    Studio.objects.filter(pk=studio_id).update(schedule_version=F('schedule_version') + 1)
    return Studio.objects.select_for_update().select_related('owner').get(pk=studio_id)


def publication_errors(studio):
    errors = []
    for field, label in [('title', 'نام پلاتو'), ('city', 'شهر'), ('address', 'نشانی'), ('description', 'معرفی'), ('amenities', 'امکانات'), ('rules', 'قوانین')]:
        if not getattr(studio, field).strip(): errors.append(f'{label} را کامل کنید.')
    if not studio.cover: errors.append('عکس اصلی پلاتو را اضافه کنید.')
    if not studio.area or not studio.capacity: errors.append('مساحت و ظرفیت را مشخص کنید.')
    if not studio.hourly_price: errors.append('هزینهٔ هر ساعت باید بیشتر از صفر باشد.')
    if not studio.slots.filter(starts_at__gt=timezone.now(), state='open', booking__isnull=True).exists():
        errors.append('حداقل یک ساعت قابل رزرو در آینده بسازید.')
    return errors


@transaction.atomic
def build_schedule(studio_id, start_date, end_date, start_time, end_time, weekdays, price):
    studio = lock_studio(studio_id)
    if start_date < timezone.localdate() or end_date < start_date or (end_date-start_date).days > 89:
        raise ValueError('بازهٔ تاریخ باید از امروز به بعد و حداکثر ۹۰ روز باشد.')
    if start_time.minute or end_time.minute or start_time.second or end_time.second or end_time <= start_time:
        raise ValueError('ساعت آغاز و پایان را سرِ ساعت و در یک روز انتخاب کنید.')
    if not weekdays or not set(weekdays) <= set(range(7)) or not 1 <= price <= 100000000:
        raise ValueError('روزهای هفته و هزینهٔ معتبر را انتخاب کنید.')
    requested = []
    for offset in range((end_date-start_date).days+1):
        day = start_date+timedelta(days=offset)
        if day.weekday() not in weekdays: continue
        cursor = timezone.make_aware(datetime.combine(day, start_time))
        until = timezone.make_aware(datetime.combine(day, end_time))
        while cursor < until:
            if cursor > timezone.now(): requested.append((cursor, cursor+timedelta(hours=1)))
            cursor += timedelta(hours=1)
    if not requested or len(requested)>1000: raise ValueError('بازه باید بین ۱ تا ۱۰۰۰ ساعتِ آینده داشته باشد.')
    existing = list(studio.slots.filter(starts_at__lt=requested[-1][1], ends_at__gt=requested[0][0]).values_list('starts_at', 'ends_at'))
    new_slots = [StudioSlot(studio=studio, starts_at=start, ends_at=end, price_toman=price)
                 for start, end in requested if not any(old_start < end and old_end > start for old_start, old_end in existing)]
    StudioSlot.objects.bulk_create(new_slots)
    if new_slots: Studio.objects.filter(pk=studio.pk).update(updated_at=timezone.now())
    return len(new_slots), len(requested)-len(new_slots)



@transaction.atomic
def change_slot(studio_id, slot_id, state, price, note=''):
    studio = lock_studio(studio_id)
    slot = StudioSlot.objects.select_for_update().get(pk=slot_id, studio=studio)
    if slot.booking_id or slot.starts_at <= timezone.now(): raise ValueError('ساعت رزروشده یا گذشته قابل تغییر نیست.')
    if state not in ('open', 'closed', 'blocked') or not 1 <= price <= 100000000: raise ValueError('وضعیت یا قیمت نامعتبر است.')
    slot.state, slot.price_toman, slot.private_note = state, price, note[:300]
    slot.save(update_fields=['state', 'price_toman', 'private_note'])
    Studio.objects.filter(pk=studio.pk).update(updated_at=timezone.now())
    return slot


@transaction.atomic
def book_slots(user, studio_id, slot_ids, expected_total, renter_name, booking_id):
    studio = lock_studio(studio_id)
    existing = Booking.objects.filter(pk=booking_id).first()
    if existing:
        if existing.renter_id != user.pk or existing.studio_id != studio.pk:
            raise ValueError('شناسهٔ رزرو معتبر نیست؛ دوباره انتخاب کنید.')
        if existing.status != 'confirmed': raise ValueError('این رزرو قبلاً لغو شده است؛ دوباره ساعت انتخاب کنید.')
        if set(existing.slots.values_list('pk', flat=True)) != set(slot_ids) or existing.paid_rial != expected_total*10:
            raise ValueError('جزئیات درخواست با رزرو قبلی یکسان نیست.')
        return existing, False
    if not user.is_active or studio.owner_id==user.pk: raise ValueError('برای رزرو از حساب هنرمند استفاده کنید؛ رزرو خارج از سایت را در تقویم پلاتو ثبت کنید.')
    if studio.status!='published' or not studio.owner.is_active or not studio.booking_open: raise ValueError('رزرو این پلاتو در دسترس نیست.')
    if not slot_ids or len(slot_ids)>12 or len(slot_ids)!=len(set(slot_ids)): raise ValueError('بین ۱ تا ۱۲ ساعت پشت‌سرهم انتخاب کنید.')
    slots = list(studio.slots.select_for_update().filter(pk__in=slot_ids).order_by('starts_at'))
    if len(slots)!=len(slot_ids) or any(s.state!='open' or s.booking_id or s.starts_at<=timezone.now() or s.ends_at-s.starts_at!=timedelta(hours=1) for s in slots):
        raise ValueError('یکی از ساعت‌ها دیگر قابل رزرو نیست؛ تقویم را تازه‌سازی کنید.')
    if timezone.localtime(slots[0].starts_at).date()!=timezone.localtime(slots[-1].starts_at).date() or any(a.ends_at!=b.starts_at for a,b in zip(slots,slots[1:])):
        raise ValueError('ساعت‌ها باید پشت‌سرهم و در یک روز باشند.')
    total = sum(s.price_toman for s in slots)
    if total!=expected_total: raise ValueError('قیمت یا ساعت‌های انتخابی تغییر کرده‌اند؛ مبلغ جدید را دوباره تأیید کنید.')
    if not renter_name.strip() or len(renter_name)>150: raise ValueError('نام رزروکننده را کامل کنید.')
    if not is_wallet_enabled(): raise ValueError('پرداخت از کیف پول موقتاً غیرفعال است.')
    wallet, _ = Wallet.objects.get_or_create(user=user)
    if not wallet.deduct_balance(total*10, f'اجارهٔ پلاتو: {studio.title}', f'studio-{booking_id}', tx_type='studio_rental'):
        raise ValueError('موجودی کیف پول کافی نیست؛ ابتدا کیف پول را شارژ کنید.')
    booking = Booking.objects.create(id=booking_id, studio=studio, renter=user, renter_name=renter_name.strip(), studio_title=studio.title,
        starts_at=slots[0].starts_at, ends_at=slots[-1].ends_at, hours=len(slots), paid_rial=total*10)
    changed = studio.slots.filter(pk__in=slot_ids, state='open', booking__isnull=True).update(booking=booking)
    if changed!=len(slots): raise ValueError('یکی از ساعت‌ها رزرو شده است؛ دوباره انتخاب کنید.')
    when = timezone.localtime(booking.starts_at).strftime('%H:%M')
    notify(user,'purchase','زمان تمرینت رزرو شد',f'رزرو «{studio.title}» از ساعت {when} قطعی شد.',reverse('studios:my_bookings'),f'studio-booking:{booking.pk}')
    notify(studio.owner,'purchase','رزرو تازه برای پلاتوی شما',f'{booking.hours} ساعت در «{studio.title}» رزرو شد.',reverse('studios:manage',args=[studio.pk]),f'studio-booking:{booking.pk}')
    return booking, True


@transaction.atomic
def cancel_booking(booking_id, note):
    if not note.strip(): raise ValueError('علت لغو را بنویسید.')
    studio_id = Booking.objects.values_list('studio_id',flat=True).get(pk=booking_id)
    lock_studio(studio_id)
    booking = Booking.objects.select_for_update().select_related('renter','studio').get(pk=booking_id)
    if booking.status!='confirmed': raise ValueError('این رزرو قبلاً لغو و بازپرداخت شده است.')
    wallet,_=Wallet.objects.get_or_create(user=booking.renter)
    wallet.add_balance(booking.paid_rial,f'بازپرداخت پلاتو: {booking.studio_title}',f'refund-studio-{booking.pk}',tx_type='refund')
    booking.status='cancelled'; booking.cancelled_at=timezone.now(); booking.cancellation_note=note[:2000]
    booking.save(update_fields=['status','cancelled_at','cancellation_note'])
    booking.slots.update(booking=None)
    for person,url in [(booking.renter,reverse('studios:my_bookings')),(booking.studio.owner,reverse('studios:manage',args=[studio_id]))]:
        notify(person,'payment','لغو رزرو پلاتو',f'«{booking.studio_title}»؛ {note}',url,f'studio-cancel:{booking.pk}')
    return booking
