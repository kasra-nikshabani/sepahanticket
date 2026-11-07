"""Bounded physical seat proposals. Never mutates live seat or ticket records."""
import json
import re
from math import atan, degrees, ceil
from django.core.exceptions import ValidationError

MAX_POSITIONS = 5000
MAX_SECTIONS = 8
MAX_ROWS = 60
MAX_COLUMNS = 80
MAX_JSON_LENGTH = 150000


def curve_point(curvature, index, count):
    if count <= 2:
        return {'y': 0, 'angle': 0}
    height = curvature * .48
    x = 2 * index / (count - 1) - 1
    return {'y': round(height * (1 - x * x)),
            'angle': max(-30, min(30, round(degrees(atan(-4 * height * x / ((count - 1) * 36))))))}


def curve_padding(curvature, count):
    height = ceil(abs(curvature) * .48) if count > 2 else 0
    return {'top': height if curvature < 0 else 0, 'bottom': height if curvature > 0 else 0}


def validate_layout(value):
    if value in (None, '', {}):
        return {}
    if isinstance(value, str):
        if len(value) > MAX_JSON_LENGTH:
            raise ValidationError('حجم نقشه سالن بیش از حد مجاز است.')
        try:
            value = json.loads(value)
        except (ValueError, RecursionError):
            raise ValidationError('نقشه سالن معتبر نیست؛ چیدمان را دوباره ذخیره کن.')
    if value == {}:
        return {}
    if not isinstance(value, dict) or type(value.get('version')) is not int or value.get('version') != 1:
        raise ValidationError('نسخه نقشه سالن معتبر نیست.')
    if value.get('stage') not in ('top', 'bottom') or value.get('direction') not in ('rtl', 'ltr'):
        raise ValidationError('جهت صحنه یا شماره‌گذاری سالن معتبر نیست.')
    sections = value.get('sections')
    if not isinstance(sections, list) or len(sections) > MAX_SECTIONS:
        raise ValidationError('هر سالن می‌تواند حداکثر ۸ بخش داشته باشد.')
    result = {'version': 1, 'stage': value['stage'], 'direction': value['direction'], 'sections': []}
    ids, names = set(), set()
    position_count = 0
    for section in sections:
        if not isinstance(section, dict):
            raise ValidationError('اطلاعات بخش سالن معتبر نیست.')
        key, name, rows = section.get('id'), section.get('name'), section.get('rows')
        if not isinstance(key, str) or not re.fullmatch(r'[a-zA-Z0-9_-]{1,40}', key) or key in ids:
            raise ValidationError('شناسه بخش‌های سالن باید معتبر و یکتا باشد.')
        if not isinstance(name, str) or not name.strip() or len(name.strip()) > 50 or name.strip() in names:
            raise ValidationError('نام هر بخش باید یکتا و حداکثر ۵۰ نویسه باشد.')
        if not isinstance(rows, list) or len(rows) > MAX_ROWS:
            raise ValidationError('هر بخش می‌تواند حداکثر ۶۰ ردیف داشته باشد.')
        ids.add(key); names.add(name.strip())
        new_section = {'id': key, 'name': name.strip(), 'rows': []}
        numbers = set()
        for row in rows:
            if not isinstance(row, dict):
                raise ValidationError('اطلاعات ردیف معتبر نیست.')
            number, offset, seats = row.get('number'), row.get('offset', 0), row.get('seats')
            alignment = row.get('alignment', 'start')
            curvature = row.get('curvature', 0)
            if type(curvature) is not int or not -100 <= curvature <= 100:
                raise ValidationError('انحنای ردیف باید عدد صحیح بین منفی ۱۰۰ و ۱۰۰ باشد.')
            if alignment not in ('start', 'center', 'end'):
                raise ValidationError('چینش ردیف باید ابتدا، وسط یا انتها باشد.')
            if type(number) is not int or not 1 <= number <= 999 or number in numbers:
                raise ValidationError('شماره ردیف‌ها در هر بخش باید مثبت و یکتا باشد.')
            if type(offset) is not int or not 0 <= offset <= 20:
                raise ValidationError('فاصله ردیف از لبه باید بین صفر و ۲۰ باشد.')
            if not isinstance(seats, list) or not 1 <= len(seats) <= MAX_COLUMNS:
                raise ValidationError('هر ردیف باید بین ۱ تا ۸۰ جایگاه صندلی یا راهرو داشته باشد.')
            used = set()
            for seat in seats:
                if seat is None:
                    continue
                if type(seat) is not int or not 1 <= seat <= 999 or seat in used:
                    raise ValidationError('شماره صندلی‌ها در هر ردیف باید مثبت و یکتا باشد.')
                used.add(seat)
            position_count += len(seats)
            if position_count > MAX_POSITIONS:
                raise ValidationError('مجموع جایگاه‌های نقشه باید حداکثر ۵۰۰۰ باشد.')
            numbers.add(number)
            new_row = {'number': number, 'offset': offset, 'seats': seats}
            if 'alignment' in row:
                new_row['alignment'] = alignment
            if 'curvature' in row:
                new_row['curvature'] = curvature
            new_section['rows'].append(new_row)
        result['sections'].append(new_section)
    return result


def layout_capacity(layout):
    return sum(seat is not None for section in layout.get('sections', [])
               for row in section['rows'] for seat in row['seats'])
