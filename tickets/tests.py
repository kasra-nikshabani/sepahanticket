"""
تست‌های Endpoint فقط-خواندنی Polling سرویس Loyalty (Phase 12 در sepapp، ADR-0014).

با اجرای معمولی تست‌ها اجرا می‌شوند؛ توکن سرویس با override_settings تنظیم می‌شود،
پس به settings_test_loyalty.py (جایگزین اختیاری SQLite) وابسته نیستند.
"""
from datetime import timedelta
from urllib.parse import quote

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone

from matches.models import Match, Stadium
from tickets.models import Order

User = get_user_model()
TEST_TOKEN = 'test-only-token-never-used-in-production'


@override_settings(LOYALTY_POLL_SERVICE_TOKEN=TEST_TOKEN)
class CompletedOrdersEndpointTest(TestCase):

    def setUp(self):
        self.stadium = Stadium.objects.create(name='ورزشگاه نقش جهان', capacity=70000)
        self.match = Match.objects.create(
            home_team='سپاهان', away_team='استقلال', stadium=self.stadium, date_time=timezone.now())
        self.user_with_fan_id = User.objects.create_user(
            username='fan_with_sso', national_code='0011122233', phone_number='09120000001',
            fan_id_subject='11111111-1111-1111-1111-111111111111')
        self.user_without_fan_id = User.objects.create_user(
            username='fan_legacy', national_code='0011122234', phone_number='09120000002')

    def _url(self, since):
        # quote ضروری است -- "+" در Query String خام معادل Space دیکد می‌شود (RFC 3986)،
        # و isoformat() آفست UTC را دقیقاً به‌شکل "+00:00" برمی‌گرداند؛ بدون Encode درست،
        # سمت سرور دقیقاً همین رشته را نامعتبر می‌بیند -- با تست واقعی همین‌جا کشف شد.
        return f'/tickets/api/loyalty/completed-orders/?since={quote(since)}'

    def test_rejects_missing_token(self):
        response = self.client.get(self._url('2020-01-01T00:00:00+00:00'))
        self.assertEqual(response.status_code, 401)

    def test_rejects_wrong_token(self):
        response = self.client.get(self._url('2020-01-01T00:00:00+00:00'), HTTP_AUTHORIZATION='Bearer wrong-token')
        self.assertEqual(response.status_code, 401)

    def test_rejects_missing_since(self):
        response = self.client.get(
            '/tickets/api/loyalty/completed-orders/', HTTP_AUTHORIZATION=f'Bearer {TEST_TOKEN}')
        self.assertEqual(response.status_code, 400)

    def test_returns_only_paid_orders_after_since_with_fan_id(self):
        now = timezone.now()
        paid_order = Order.objects.create(
            user=self.user_with_fan_id, match=self.match, total_amount=500000,
            payment_status='paid', paid_at=now)
        Order.objects.create(
            user=self.user_with_fan_id, match=self.match, total_amount=999999,
            payment_status='pending', paid_at=None)
        Order.objects.create(
            user=self.user_with_fan_id, match=self.match, total_amount=888888,
            payment_status='paid', paid_at=now - timedelta(days=2))

        response = self.client.get(
            self._url((now - timedelta(hours=1)).isoformat()), HTTP_AUTHORIZATION=f'Bearer {TEST_TOKEN}')

        self.assertEqual(response.status_code, 200)
        orders = response.json()['orders']
        self.assertEqual(len(orders), 1)
        self.assertEqual(orders[0]['order_id'], paid_order.id)
        self.assertEqual(orders[0]['amount'], 500000)
        self.assertEqual(orders[0]['fan_id_subject'], '11111111-1111-1111-1111-111111111111')

    def test_legacy_user_without_fan_id_still_included_with_null(self):
        now = timezone.now()
        Order.objects.create(
            user=self.user_without_fan_id, match=self.match, total_amount=100000,
            payment_status='paid', paid_at=now)

        response = self.client.get(
            self._url((now - timedelta(hours=1)).isoformat()), HTTP_AUTHORIZATION=f'Bearer {TEST_TOKEN}')

        orders = response.json()['orders']
        self.assertEqual(len(orders), 1)
        self.assertIsNone(orders[0]['fan_id_subject'])
