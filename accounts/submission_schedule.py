"""Bounded, local-time session plans for initial publication."""
from datetime import date, datetime, time, timedelta
import jdatetime
from django.core.exceptions import ValidationError
from django.utils import timezone

MAX_DAYS = 90


def session_plan(data):
    try:
        start = date.fromisoformat(str(data.get('start_date', '')))
        end = date.fromisoformat(str(data.get('end_date', '')))
        times = sorted({time.fromisoformat(str(data[key])) for key in ('time', 'second_time', 'third_time') if data.get(key)})
    except (ValueError, TypeError):
        raise ValidationError('تاریخ آغاز، پایان و ساعت اجرا را مشخص کنید.')
    if any(hour.second or hour.microsecond for hour in times):
        raise ValidationError('ساعت اجرا را با دقت ساعت و دقیقه وارد کنید.')
    if not times:
        raise ValidationError('حداقل یک ساعت اجرا را مشخص کنید.')
    if end < start or (end - start).days >= MAX_DAYS:
        raise ValidationError('بازه برنامه باید بین ۱ تا ۹۰ روز باشد.')
    result = []
    for offset in range((end - start).days + 1):
        day = start + timedelta(days=offset)
        for hour in times:
            moment = datetime.combine(day, hour)
            key = moment.isoformat(timespec='minutes')
            label = jdatetime.date.fromgregorian(date=day).strftime('%Y/%m/%d') + ' · ساعت ' + hour.strftime('%H:%M')
            result.append({'key': key, 'label': label, 'day': day.isoformat(),
                'day_label': jdatetime.date.fromgregorian(date=day).strftime('%Y/%m/%d'), 'time': hour.strftime('%H:%M'),
                'date_time': timezone.make_aware(moment, timezone.get_current_timezone())})
    return result


def validate_opening_sessions(value, data, partial=False):
    if not isinstance(value, list) or len(value) > MAX_DAYS * 3 or any(not isinstance(item, str) for item in value):
        raise ValidationError('سانس‌های انتخاب‌شده معتبر نیستند.')
    if partial and not value:
        return []
    allowed = {item['key'] for item in session_plan(data)}
    if any(item not in allowed for item in value):
        raise ValidationError('سانس‌های شروع فروش باید داخل بازه تاریخ و ساعت‌های همین برنامه باشند؛ انتخاب‌ها را بازبینی کنید.')
    return sorted(set(value))
