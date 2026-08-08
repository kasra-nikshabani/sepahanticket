# accounts/middleware.py
"""
ردیابی سبک بازدیدکننده‌ها برای شمارنده‌ی «کاربران آنلاین» و «بازدید ۲۴ ساعت
گذشته» در پنل ادمین.

عمداً از session استفاده نمی‌کند (چون این پروژه برای ترافیک بالا
SESSION_SAVE_EVERY_REQUEST را خاموش نگه داشته تا نوشتن اضافی روی Redis در
لحظه‌ی فروش بلیط پیش نیاید)؛ به‌جایش شناسه‌ی بازدیدکننده از IP یا شناسه‌ی
کاربر لاگین‌شده ساخته می‌شود.

- «آنلاین بودن»: فقط یک SET در Redis با TTL ۵ دقیقه‌ای (بدون نوشتن در
  دیتابیس، برای هر درخواست تکرار می‌شود ولی هزینه‌اش ناچیز است).
- «بازدید ۲۴ ساعته»: حداکثر یک ردیف در دیتابیس به‌ازای هر بازدیدکننده در هر
  بازه‌ی ۲۴ ساعته (با یک فلگ در Redis از نوشتن‌های تکراری جلوگیری می‌شود).
"""
from django.core.cache import cache

ONLINE_TTL = 300  # ۵ دقیقه -> «الان آنلاینه»
VISIT_DEDUPE_TTL = 60 * 60 * 24  # ۲۴ ساعت -> حداکثر یک ردیف دیتابیس در این بازه

EXCLUDED_PREFIXES = ('/admin/', '/static/', '/media/', '/tickets/api/')


def _get_visitor_id(request):
    if request.user.is_authenticated:
        return f"user:{request.user.id}"
    ip = request.META.get('HTTP_X_REAL_IP') or request.META.get('REMOTE_ADDR') or 'unknown'
    return f"ip:{ip}"


class VisitTrackingMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.method == 'GET' and not request.path.startswith(EXCLUDED_PREFIXES):
            self._track(request)
        return self.get_response(request)

    def _track(self, request):
        visitor_id = _get_visitor_id(request)

        cache.set(f'online_visitor:{visitor_id}', 1, timeout=ONLINE_TTL)

        dedupe_key = f'visited_today:{visitor_id}'
        if cache.get(dedupe_key):
            return
        cache.set(dedupe_key, 1, timeout=VISIT_DEDUPE_TTL)

        from .models import SiteVisit
        SiteVisit.objects.create(
            visitor_id=visitor_id,
            ip_address=request.META.get('HTTP_X_REAL_IP') or request.META.get('REMOTE_ADDR'),
            user=request.user if request.user.is_authenticated else None,
        )
