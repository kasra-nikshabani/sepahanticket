# football_tickets/csrf.py
"""
هندلر سراسری خطای CSRF.

رفتار پیش‌فرض جنگو برای شکست CSRF این است که همیشه یک صفحه‌ی HTML برمی‌گرداند
(حتی برای درخواست‌های fetch/AJAX که کد جاوااسکریپت‌شان response.json() صدا
می‌زند) -- و همین باعث خطای "Unexpected token '<', <!DOCTYPE ..." سمت کاربر
می‌شود، دقیقاً همان چیزی که در صفحه‌ی «تکمیل اطلاعات خرید» (استعلام ثبت‌احوال)
رخ می‌داد: اگر توکن CSRF به هر دلیلی نامعتبر شود (مثلاً کاربر یک تب قدیمی را
باز نگه داشته و نشستش در تب دیگری چرخیده)، Middleware حتی قبل از رسیدن به
ویو، یک صفحه‌ی HTML برمی‌گرداند -- try/except داخل ویو هم کمکی نمی‌کند چون
اصلاً به ویو نمی‌رسد.

تشخیص AJAX/fetch بودن درخواست عمدتاً روی هدر استاندارد Fetch Metadata
(`Sec-Fetch-Dest: empty`) تکیه دارد -- این هدر را خودِ مرورگر برای هر
fetch()/XHR به‌صورت خودکار می‌فرستد (کد جاوااسکریپت لازم نیست صریحاً
چیزی ست کند)، پس فراموش‌کردن یک هدر دستی در JS باعث لو رفتن HTML به
جای JSON نمی‌شود. `X-Requested-With` هم به‌عنوان یک نشانه‌ی کمکی/قدیمی‌تر
چک می‌شود. برای ناوبری معمولی مرورگر (بارگذاری خودِ صفحه)، همان صفحه‌ی
خطای استاندارد جنگو نمایش داده می‌شود.
"""
from django.http import JsonResponse
from django.views.csrf import csrf_failure as django_csrf_failure


def csrf_failure(request, reason=""):
    is_ajax = (
        request.headers.get('Sec-Fetch-Dest') == 'empty'
        or request.headers.get('X-Requested-With') == 'XMLHttpRequest'
    )

    if is_ajax:
        return JsonResponse(
            {
                'success': False,
                'error': 'نشست شما منقضی شده یا صفحه قدیمی شده است. لطفاً صفحه را رفرش کنید و دوباره تلاش کنید.',
            },
            status=403,
        )

    return django_csrf_failure(request, reason=reason)
