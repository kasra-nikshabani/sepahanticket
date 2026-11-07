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


from django.db.models.signals import post_save


@receiver(post_save, sender='payments.Payment')
def notify_failed_ticket_payment(sender, instance, raw=False, **kwargs):
    if raw or instance.status != 'failed' or instance.purpose != 'ticket_purchase' or not instance.match_id:
        return
    from django.urls import reverse
    from .notifications import notify
    if instance.match.is_cultural:
        notify(instance.user, 'payment', 'پرداخت بلیط تکمیل نشد',
            f'خرید برنامهٔ «{instance.match.display_title}» تکمیل نشده است. بلیط‌های من و وضعیت کیف پول را بررسی کنید؛ در صورت نیاز از پشتیبانی کمک بگیرید.',
            reverse('tickets:user_tickets'), f'payment:{instance.pk}:failed')
