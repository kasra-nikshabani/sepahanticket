# tickets/api_loyalty.py
#
# Endpoint فقط-خواندنی جدید، افزودنی برای ماژول Loyalty در sepapp (Backend جدید، Phase 12).
# جزئیات کامل و دلایل معماری: ریپوی sepapp، docs/adr/0014.
#
# این فایل هیچ منطق سفارش/پرداخت موجود را تغییر نمی‌دهد -- فقط سفارش‌های پرداخت‌شده
# را برای Polling دوره‌ای سرویس Loyalty (Spring Boot) گزارش می‌کند. احراز هویت با
# یک راز مشترک ساده است (LOYALTY_POLL_SERVICE_TOKEN)، نه Keycloak -- Middleware
# فعلی Keycloak فقط کاربر Fan را احراز هویت می‌کند، نه یک سرویس بیرونی.
import secrets
from datetime import datetime, timezone

from django.conf import settings
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from .models import Order

MAX_ORDERS_PER_POLL = 500


def _service_authenticated(request):
    auth_header = request.headers.get('Authorization', '')
    if not auth_header.startswith('Bearer '):
        return False
    token = auth_header[len('Bearer '):].strip()
    expected = settings.LOYALTY_POLL_SERVICE_TOKEN
    if not expected:
        return False
    return secrets.compare_digest(token, expected)


@csrf_exempt
@require_http_methods(['GET'])
def completed_orders(request):
    """
    سفارش‌های پرداخت‌شده (payment_status='paid') با paid_at بعد از پارامتر since --
    مرتب‌شده بر اساس paid_at صعودی، حداکثر ۵۰۰ ردیف در هر فراخوانی.
    """
    if not _service_authenticated(request):
        return JsonResponse({'error': 'unauthorized'}, status=401)

    since_param = request.GET.get('since')
    if not since_param:
        return JsonResponse({'error': 'missing since parameter'}, status=400)
    try:
        since = datetime.fromisoformat(since_param)
        if since.tzinfo is None:
            since = since.replace(tzinfo=timezone.utc)
    except ValueError:
        return JsonResponse({'error': 'invalid since parameter, expected ISO-8601'}, status=400)

    orders = (
        Order.objects
        .filter(payment_status='paid', paid_at__gt=since)
        .select_related('user')
        .order_by('paid_at')[:MAX_ORDERS_PER_POLL]
    )

    return JsonResponse({
        'orders': [
            {
                'order_id': order.id,
                'order_number': order.order_number,
                'fan_id_subject': order.user.fan_id_subject,
                'amount': order.total_amount,
                'paid_at': order.paid_at.isoformat() if order.paid_at else None,
            }
            for order in orders
        ]
    })
