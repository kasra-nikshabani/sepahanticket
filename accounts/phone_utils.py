"""نرمال‌سازی شماره موبایل ایران برای ورود و ثبت در پنل."""
import re

_FA_TO_EN = str.maketrans('۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩', '01234567890123456789')


def normalize_iran_mobile(raw):
    """ورودی‌های رایج (۰۹۱۲… / 912… / +98912… / ارقام فارسی) را به ۰۹xxxxxxxxx تبدیل می‌کند.
    اگر معتبر نباشد None برمی‌گرداند."""
    if raw is None:
        return None
    s = str(raw).strip().translate(_FA_TO_EN)
    s = re.sub(r'[\s\-_]', '', s)
    if s.startswith('+'):
        s = s[1:]
    s = re.sub(r'\D', '', s)
    if s.startswith('98') and len(s) == 12:
        s = '0' + s[2:]
    elif s.startswith('9') and len(s) == 10:
        s = '0' + s
    if re.fullmatch(r'09\d{9}', s):
        return s
    return None
