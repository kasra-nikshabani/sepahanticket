"""استعلام نام صاحب حساب از روی شماره شبا (وب‌سرویس زیبال).

چرا لازم است
------------
تا امروز تنها کنترلِ «این حساب مالِ خودِ کاربر است؟» مقایسه‌ی چشمیِ
خزانه‌دار بود؛ سیستم فقط رقم کنترلیِ شبا را چک می‌کرد که صرفاً می‌گوید
«چنین شماره‌ای می‌تواند وجود داشته باشد»، نه اینکه مالِ کیست. با روشن شدن
برداشت برای ۴۲۰ نفر، اتکا به دقتِ یک اپراتور کافی نیست.

اصل طراحی: **هیچ‌وقت به‌خاطر خرابیِ این سرویس، پول کسی گیر نکند.**
اگر توکن تنظیم نشده باشد، سرویس قطع باشد، یا پاسخ نامفهوم باشد، نتیجه
«نامعلوم» است و درخواست مثل قبل وارد صف بررسیِ دستی می‌شود. فقط وقتی
سرویس *با اطمینان* می‌گوید نام فرق دارد، مسیر عوض می‌شود.
"""
import logging
import re

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

INQUIRY_URL = 'https://api.zibal.ir/v1/facility/ibanInquiry'
MATCH_URL = 'https://api.zibal.ir/v1/facility/checkIbanWithNationalCode'
TIMEOUT = 8

# تاریخ تولدی که وقتی تاریخ واقعیِ کاربر را نداریم فرستاده می‌شود.
# مستندات زیبال صریح گفته این پارامتر در تطبیق دخالت داده نمی‌شود
# («ممکن است این سرویس با تاریخ تولد اشتباه هم پاسخ را به درستی برگرداند»)،
# ولی چون پارامتر اجباری است چیزی باید فرستاده شود. هر جا تاریخ واقعی را
# داشته باشیم همان می‌رود، تا اگر روزی زیبال سخت‌گیر شد این مسیر نشکند.
FALLBACK_BIRTH_DATE = '1370/01/01'

# کدهای پاسخ زیبال: ۱ موفق است. ۶ و ۲۱ یعنی خودِ شبا ایراد دارد؛ بقیه
# (۲ و ۳ توکن، ۴ دسترسی، ۷ آی‌پی، ۲۹ موجودی) مشکل *ما*ست نه کاربر، و
# نباید به پای او نوشته شود.
RESULT_OK = 1
# ۶ ورودی نامعتبر، ۲۱ شبا از نظر شکلی غلط، ۴۴ شبا یافت نشد.
# هر سه حرفی درباره‌ی *ورودیِ کاربر*اند، پس باید به او برگردند تا اصلاح کند.
RESULT_BAD_IBAN = (6, 21, 44)
# ۴۵ = «سرویس‌دهنده‌ای برای استعلام در دسترس نیست». این جمله درباره‌ی
# زیرساختِ استعلام است، نه درباره‌ی شبای کاربر -- پس «نامعلوم» است نه
# «مغایر». اشتباه گرفتنش یعنی متوقف‌کردن درخواست‌های درست به‌خاطر قطعیِ
# موقتِ سمتِ بانک.
RESULT_NO_PROVIDER = 45

# وضعیت‌های خروجی
OK = 'ok'                   # نام گرفته شد
BAD_IBAN = 'invalid'        # شبا نزد بانک وجود ندارد
UNAVAILABLE = 'unavailable'  # نتوانستیم بپرسیم -- تصمیم با اپراتور


def is_configured():
    return bool(getattr(settings, 'ZIBAL_FACILITY_TOKEN', ''))


# ------------------------------------------------------------------
_ARABIC = str.maketrans({'ي': 'ی', 'ك': 'ک', 'ة': 'ه', 'أ': 'ا', 'إ': 'ا',
                         'آ': 'ا', 'ؤ': 'و', 'ئ': 'ی'})


def normalize_name(value):
    """نام را به شکلی درمی‌آورد که املاهای رایج فارسی یکی شوند.

    بانک ممکن است «نیک شبانی» برگرداند و کاربر «نیک‌شبانی» نوشته باشد؛ یا
    یکی «ي» عربی داشته باشد و دیگری «ی» فارسی. اینها یک نام‌اند و نباید
    باعث رد شدن یک درخواست درست شوند. پس نیم‌فاصله و فاصله کاملاً حذف
    می‌شوند و حروف هم‌ارز یکی می‌گردند.
    """
    if not value:
        return ''
    s = str(value).translate(_ARABIC)
    s = s.replace('‌', '').replace('‏', '').replace('‎', '')
    s = re.sub(r'[ً-ْ]', '', s)      # اعراب
    s = re.sub(r'\s+', '', s)
    return s.strip()


def names_match(bank_name, *candidates):
    """آیا نامی که بانک برگردانده با یکی از نام‌های کاربر یکی است؟

    عمداً سخت‌گیر نیست: اگر یکی زیرمجموعه‌ی دیگری باشد (نام میانی، پیشوند،
    نام پدر) هم قبول می‌شود. سخت‌گیریِ بیش از حد یعنی بیرون‌انداختنِ آدمِ
    درست، و آن هزینه‌اش از یک بررسی دستیِ اضافه بیشتر است.
    """
    b = normalize_name(bank_name)
    if not b:
        return False
    for cand in candidates:
        c = normalize_name(cand)
        if not c:
            continue
        if b == c or b in c or c in b:
            return True
    return False


# ------------------------------------------------------------------
def _extract_name(data):
    """نام را از پاسخ بیرون می‌کشد.

    طبق مدلِ «صاحب حساب» در مستندات زیبال، کلید اصلی `name` است (کنار
    IBAN و bankName و bankAccount). حالت `separated: true` نام و نام
    خانوادگی را جدا می‌کند، پس firstName/lastName هم پوشش داده شده.

    بقیه‌ی حالت‌ها از سر احتیاط‌اند: مستندات نمونه‌ی JSON پاسخِ ibanInquiry
    را نیاورده و اگر شکلی غیر از این‌ها بیاید، نتیجه «نامعلوم» می‌شود نه
    «مغایر» -- یعنی هیچ درخواستِ درستی به‌خاطر ناشناخته بودنِ ساختار رد
    نمی‌شود.
    """
    if not isinstance(data, dict):
        return ''
    for key in ('name', 'ownerName', 'owner', 'fullName', 'depositOwner'):
        if data.get(key):
            return str(data[key])

    first = data.get('firstName') or data.get('first_name') or ''
    last = data.get('lastName') or data.get('last_name') or ''
    if first or last:
        return f'{first} {last}'.strip()

    owners = data.get('depositOwners') or data.get('owners')
    if isinstance(owners, list) and owners:
        head = owners[0]
        if isinstance(head, dict):
            return str(head.get('fullName') or head.get('name')
                       or f"{head.get('firstName', '')} {head.get('lastName', '')}".strip())
        return str(head)
    return ''


def inquire_iban(iban):
    """نام صاحب حساب را از زیبال می‌پرسد.

    خروجی: dict با کلیدهای status (ok/invalid/unavailable)، name و detail.
    هیچ استثنایی به بیرون پرت نمی‌شود -- این تابع در مسیر ثبت درخواستِ
    کاربر صدا زده می‌شود و نباید بتواند آن مسیر را بشکند.
    """
    if not is_configured():
        return {'status': UNAVAILABLE, 'name': '', 'detail': 'توکن استعلام تنظیم نشده'}

    try:
        resp = requests.post(
            INQUIRY_URL,
            json={'IBAN': iban},
            headers={'Authorization': f'Bearer {settings.ZIBAL_FACILITY_TOKEN}'},
            timeout=TIMEOUT,
        )
        payload = resp.json()
    except Exception as exc:                            # noqa: BLE001
        logger.warning('IBAN inquiry failed for %s: %s', iban[-6:], exc)
        return {'status': UNAVAILABLE, 'name': '', 'detail': f'خطای ارتباط: {exc}'}

    result = payload.get('result')
    message = payload.get('message') or ''

    if result == RESULT_OK:
        name = _extract_name(payload.get('data'))
        if not name:
            # پاسخ موفق بود ولی نامی پیدا نکردیم -- یعنی شکل پاسخ با آنچه
            # انتظار داشتیم فرق دارد. لاگ می‌کنیم تا اصلاحش کنیم، و تا آن
            # موقع مثل «نامعلوم» رفتار می‌کنیم نه «مغایر».
            logger.error('IBAN inquiry succeeded but no name found. payload=%s', payload)
            return {'status': UNAVAILABLE, 'name': '', 'detail': 'ساختار پاسخ ناشناخته'}
        logger.info('IBAN inquiry ok for %s', iban[-6:])
        return {'status': OK, 'name': name, 'detail': message}

    if result in RESULT_BAD_IBAN:
        return {'status': BAD_IBAN, 'name': '', 'detail': message or 'شبا نزد بانک یافت نشد'}

    if result == RESULT_NO_PROVIDER:
        logger.warning('IBAN inquiry: no provider available for %s', iban[-6:])
        return {'status': UNAVAILABLE, 'name': '', 'detail': message}

    # ۲/۳ توکن، ۴ دسترسی، ۷ آی‌پی، ۲۹ موجودی -- همه مشکل پیکربندیِ ماست.
    logger.error('IBAN inquiry misconfigured: result=%s message=%s errorCode=%s',
                 result, message, payload.get('errorCode'))
    return {'status': UNAVAILABLE, 'name': '', 'detail': f'کد {result}: {message}'}


# ------------------------------------------------------------------
#  تطابق شبا با کد ملی -- کنترل قطعی
# ------------------------------------------------------------------
# مقایسه‌ی نام همیشه حدسی است: دو نفر می‌توانند هم‌نام باشند، و یک نفر
# می‌تواند نامش را جور دیگری بنویسد. این سرویس به‌جای شباهت، هویت را
# می‌سنجد -- «آیا این حساب متعلق به دارنده‌ی این کد ملی است؟» -- و جوابش
# بله/خیر است.

def find_birth_date(user):
    """تاریخ تولد کاربر را از خریدهای قبلی خودش پیدا می‌کند.

    روی مدل User ذخیره نمی‌شود، ولی موقع خرید بلیط برای هر صندلی گرفته
    شده. دنبال همان ردیفی می‌گردیم که کد ملی‌اش با کد ملی خودِ کاربر یکی
    باشد -- نه بلیطی که برای شخص دیگری خریده.
    """
    national_code = (getattr(user, 'national_code', '') or '').strip()
    if not national_code:
        return ''
    try:
        from payments.models import Payment
        rows = (Payment.objects.filter(user=user, purpose='ticket_purchase')
                .order_by('-created_at').values_list('buyer_info', flat=True)[:20])
    except Exception:                                   # noqa: BLE001
        return ''
    for info in rows:
        if not isinstance(info, dict):
            continue
        for key, value in info.items():
            if key.startswith('national_code_') and str(value).strip() == national_code:
                seat = key[len('national_code_'):]
                birth = info.get(f'tarikhe_tavallod_{seat}')
                if birth:
                    return str(birth).strip()
    return ''


def _read_matched(data):
    """مقدار بولیِ تطابق را از پاسخ بیرون می‌کشد.

    مستندات فقط می‌گوید «نشان دهنده تطابق و عدم تطابق»؛ نام دقیق کلید را
    نیاورده. اگر هیچ‌کدام را نشناسیم None برمی‌گردانیم -- یعنی «نمی‌دانیم»،
    که به بررسی دستی می‌رسد، نه «مغایرت».
    """
    if not isinstance(data, dict):
        return None
    for key in ('matched', 'isMatched', 'match', 'result', 'status', 'isValid'):
        if key in data and isinstance(data[key], bool):
            return data[key]
    return None


def check_iban_owner(iban, national_code, birth_date=''):
    """آیا این شبا متعلق به دارنده‌ی این کد ملی است؟

    خروجی: True (هست) / False (نیست) / None (نتوانستیم بفهمیم).
    """
    if not is_configured() or not national_code:
        return None, 'تطبیق کد ملی انجام نشد'
    try:
        resp = requests.post(
            MATCH_URL,
            json={'nationalCode': national_code,
                  'birthDate': birth_date or FALLBACK_BIRTH_DATE,
                  'IBAN': iban},
            headers={'Authorization': f'Bearer {settings.ZIBAL_FACILITY_TOKEN}'},
            timeout=TIMEOUT,
        )
        payload = resp.json()
    except Exception as exc:                            # noqa: BLE001
        logger.warning('IBAN/nationalCode match failed for %s: %s', iban[-6:], exc)
        return None, f'خطای ارتباط: {exc}'

    result = payload.get('result')
    message = payload.get('message') or ''

    if result == RESULT_OK:
        matched = _read_matched(payload.get('data'))
        if matched is None:
            logger.error('IBAN match: unknown response shape. payload=%s', payload)
            return None, 'ساختار پاسخ ناشناخته'
        return matched, message

    if result in RESULT_BAD_IBAN:
        return False, message or 'شبا یافت نشد'

    logger.warning('IBAN match unavailable: result=%s message=%s errorCode=%s',
                   result, message, payload.get('errorCode'))
    return None, f'کد {result}: {message}'


def verify_iban_ownership(iban, user):
    """کنترل کاملِ مالکیت شبا -- همان چیزی که مسیر برداشت صدا می‌زند.

    ترتیب عمداً این‌طور است تا هم قوی‌ترین جواب گرفته شود و هم کمترین
    هزینه: اول تطابق کد ملی (یک استعلام، جواب قطعی). فقط اگر نتیجه منفی
    بود سراغ استعلام نام می‌رویم -- چون آن‌وقت باید به کاربر بگوییم حساب
    به نام چه کسی است. در مسیر عادی که همه‌چیز درست است، فقط یک استعلام
    هزینه می‌شود.

    اگر کاربر کد ملی نداشته باشد یا سرویس تطابق در دسترس نباشد، به همان
    روش قبلی (استعلام نام + مقایسه) برمی‌گردیم.
    """
    national_code = (getattr(user, 'national_code', '') or '').strip()
    matched, detail = check_iban_owner(iban, national_code, find_birth_date(user))

    if matched is True:
        return {'status': OK, 'name': '', 'ownership': True,
                'detail': 'تطابق با کد ملی تأیید شد'}

    if matched is False:
        # حالا که می‌دانیم مالِ او نیست، نامِ صاحب واقعی را می‌گیریم تا در
        # پیامِ اصلاح به کاربر بگوییم حساب به نام چه کسی است.
        named = inquire_iban(iban)
        return {'status': named.get('status', OK) if named.get('name') else OK,
                'name': named.get('name', ''), 'ownership': False,
                'detail': detail}

    # نامعلوم -- به روش قبلی برمی‌گردیم.
    fallback = inquire_iban(iban)
    fallback['ownership'] = None
    return fallback
