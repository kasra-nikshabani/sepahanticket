"""نقشهٔ محل صدور شناسنامه (۳ رقم اول کد ملی) به شهرهای استان اصفهان.

کاربران فیلد «شهر» ندارند؛ نزدیک‌ترین سیگنال جغرافیاییِ ذخیره‌شده روی بلیط
همان ۳ رقم اول کد ملی خریدار است که محل صدور شناسنامه را نشان می‌دهد -- نه
محل سکونت فعلی. این نگاشت فقط شهرستان‌های استان اصفهان را پوشش می‌دهد؛ بقیه
در سطل «خارج از استان اصفهان» می‌افتند.
"""

# هر شهر: نام، مختصات تقریبی مرکز برای نشان روی نقشه، و پیشوندهای کد ملی
ISFAHAN_CITIES = {
    'isfahan': {
        'name': 'اصفهان',
        'lat': 32.6546,
        'lng': 51.6680,
        'prefixes': (
            '127', '128', '129', '136', '137', '138',
            '149', '150', '151', '152', '153',
        ),
    },
    'khomeinishahr': {
        'name': 'خمینی‌شهر',
        'lat': 32.6856,
        'lng': 51.5361,
        'prefixes': ('154', '155', '158'),
    },
    'najafabad': {
        'name': 'نجف‌آباد',
        'lat': 32.6342,
        'lng': 51.3668,
        'prefixes': ('168', '169'),
    },
    'tiran': {
        'name': 'تیران و کرون',
        'lat': 32.7026,
        'lng': 51.1528,
        'prefixes': ('184',),
    },
    'chadegan': {
        'name': 'چادگان',
        'lat': 32.7683,
        'lng': 50.6287,
        'prefixes': ('193',),
    },
    'dehaghan': {
        'name': 'دهاقان',
        'lat': 31.9361,
        'lng': 51.6478,
        'prefixes': ('195',),
    },
    'fereydan': {
        'name': 'فریدن',
        'lat': 33.0176,
        'lng': 50.4069,
        'prefixes': ('196', '197'),
    },
    'fereydunshahr': {
        'name': 'فریدون‌شهر',
        'lat': 32.9410,
        'lng': 50.1210,
        'prefixes': ('198',),
    },
    'falavarjan': {
        'name': 'فلاورجان',
        'lat': 32.5553,
        'lng': 51.5097,
        'prefixes': ('199',),
    },
    'kashan': {
        'name': 'کاشان',
        'lat': 33.9850,
        'lng': 51.4100,
        'prefixes': ('208', '209'),
    },
    'golpayegan': {
        'name': 'گلپایگان',
        'lat': 33.4537,
        'lng': 50.2884,
        'prefixes': ('221', '223'),
    },
    'lenjan': {
        'name': 'لنجان',
        'lat': 32.3894,
        'lng': 51.3767,
        'prefixes': ('226',),
    },
    'mobarakeh': {
        'name': 'مبارکه',
        'lat': 32.3465,
        'lng': 51.5045,
        'prefixes': ('230',),
    },
    'naeen': {
        'name': 'نائین',
        'lat': 32.8601,
        'lng': 53.0876,
        'prefixes': ('233',),
    },
    'natanz': {
        'name': 'نطنز',
        'lat': 33.5134,
        'lng': 51.9165,
        'prefixes': ('234',),
    },
    'shahreza': {
        'name': 'شهرضا',
        'lat': 32.0111,
        'lng': 51.8639,
        'prefixes': ('257', '258'),
    },
    'semirom': {
        'name': 'سمیرم',
        'lat': 31.4164,
        'lng': 51.5694,
        'prefixes': ('267',),
    },
    'ardestan': {
        'name': 'اردستان',
        'lat': 33.3761,
        'lng': 52.3694,
        'prefixes': ('274',),
    },
    'borkhar': {
        'name': 'برخوار',
        'lat': 32.8075,
        'lng': 51.6958,
        'prefixes': ('275',),
    },
    'khansar': {
        'name': 'خوانسار',
        'lat': 33.2206,
        'lng': 50.3150,
        'prefixes': ('276',),
    },
    'shahinshahr': {
        'name': 'شاهین‌شهر و میمه',
        'lat': 32.8639,
        'lng': 51.5528,
        'prefixes': ('277', '278'),
    },
    'aranbidgol': {
        'name': 'آران و بیدگل',
        'lat': 34.0576,
        'lng': 51.4842,
        'prefixes': ('279',),
    },
    'buinmiandasht': {
        'name': 'بوئین و میاندشت',
        'lat': 33.0740,
        'lng': 50.1630,
        'prefixes': ('281',),
    },
}

OUTSIDE = {
    'key': 'outside',
    'name': 'خارج از استان اصفهان',
    'lat': None,
    'lng': None,
}

UNKNOWN = {
    'key': 'unknown',
    'name': 'نامشخص',
    'lat': None,
    'lng': None,
}

_PREFIX_INDEX = {
    prefix: key
    for key, city in ISFAHAN_CITIES.items()
    for prefix in city['prefixes']
}


def city_for_national_code(national_code):
    """برگرداندن شهر محل صدور شناسنامه از روی کد ملی، یا outside/unknown."""
    code = (national_code or '').strip()
    if len(code) < 3 or not code[:3].isdigit():
        return dict(UNKNOWN)
    key = _PREFIX_INDEX.get(code[:3])
    if not key:
        return dict(OUTSIDE)
    city = ISFAHAN_CITIES[key]
    return {
        'key': key,
        'name': city['name'],
        'lat': city['lat'],
        'lng': city['lng'],
    }
