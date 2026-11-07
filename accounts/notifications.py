from django.contrib import messages
from django.utils.http import url_has_allowed_host_and_scheme


def internal_notification_url(url):
    return url.startswith('/') and url_has_allowed_host_and_scheme(url, allowed_hosts=set())


def welcome_user(request, user):
    name = user.first_name.strip() or user.get_full_name().strip()
    greeting = f'{name}، به دیدآور خوش آمدی!' if name else 'به دیدآور خوش آمدی!'
    messages.success(request, greeting, extra_tags='welcome')


def notify(user, kind, title, body, action_url, key):
    from .models import Notification
    if not internal_notification_url(action_url):
        raise ValueError('Notification destinations must be internal paths.')
    return Notification.objects.get_or_create(recipient=user, dedupe_key=key,
        defaults={'kind': kind, 'title': title, 'body': body, 'action_url': action_url})[0]


def notify_purchase(order):
    from django.urls import reverse
    if (order.payment_status == 'paid' and order.match.is_cultural
            and order.tickets.filter(status__in=['paid', 'admin_assigned', 'vip_issued']).exists()):
        notify(order.user, 'purchase', 'بلیط‌های شما آمادهٔ دیدارند',
            f'خرید برنامهٔ «{order.match.display_title}» با موفقیت انجام شد. بلیط دیجیتال و وضعیت فایل قابل دریافت در بلیط‌های من قابل مشاهده است.',
            reverse('tickets:user_tickets') + '?match_id=' + str(order.match_id), f'order:{order.pk}:paid')
