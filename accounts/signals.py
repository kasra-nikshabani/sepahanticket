# accounts/signals.py
"""
محدودیت ۳۰ دقیقه‌ای نشست (SESSION_COOKIE_AGE در settings.py) نباید شامل
ادمین‌ها بشود. چون ادمین ممکن است از هر مسیری وارد شود -- فرم لاگین خودِ
سایت (accounts:login_password) یا صفحه‌ی لاگین داخلی خودِ جنگو ادمین
(/admin/login/) -- به‌جای تغییر جداگانه‌ی هر ویو، به سیگنال user_logged_in
گوش می‌دهیم که django.contrib.auth.login() همیشه (فارغ از این‌که کدام
ویو صدایش زده) آن را ارسال می‌کند.
"""
from django.contrib.auth.signals import user_logged_in
from django.dispatch import receiver

ADMIN_SESSION_AGE = 60 * 60 * 24 * 7  # ۷ روز -- یعنی عملاً بدون محدودیت ۳۰ دقیقه‌ای


@receiver(user_logged_in)
def extend_admin_session(sender, request, user, **kwargs):
    if getattr(user, 'user_type', None) == 'admin':
        request.session.set_expiry(ADMIN_SESSION_AGE)
