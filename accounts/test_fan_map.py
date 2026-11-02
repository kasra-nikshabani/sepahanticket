from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from accounts.isfahan_geo import city_for_national_code
from matches.models import Block, Match, Row, Seat, Stadium
from tickets.models import Ticket

User = get_user_model()


class IsfahanGeoTests(TestCase):
    def test_isfahan_prefix(self):
        info = city_for_national_code('1272761371')
        self.assertEqual(info['key'], 'isfahan')
        self.assertEqual(info['name'], 'اصفهان')

    def test_outside_province(self):
        info = city_for_national_code('0010000003')
        self.assertEqual(info['key'], 'outside')

    def test_unknown(self):
        self.assertEqual(city_for_national_code('')['key'], 'unknown')
        self.assertEqual(city_for_national_code('12')['key'], 'unknown')


class FanMapViewTests(TestCase):
    def setUp(self):
        from accounts.models import SiteSettings
        s = SiteSettings.get_solo()
        s.block_foreign_ips = False
        s.save()

        self.admin = User.objects.create_user(
            username='adminmap', password='pw12345',
            is_staff=True, user_type='admin', national_code='1270000001',
        )
        self.stadium = Stadium.objects.create(name='نقش جهان', capacity=1000)
        self.block = Block.objects.create(stadium=self.stadium, name='A', price=100000, zone_type='home')
        self.row = Row.objects.create(block=self.block, number=1)
        self.seat1 = Seat.objects.create(row=self.row, number=1)
        self.seat2 = Seat.objects.create(row=self.row, number=2)
        self.m1 = Match.objects.create(
            home_team='سپاهان', away_team='الف', stadium=self.stadium,
            date_time=timezone.now() + timedelta(days=2),
        )
        self.m2 = Match.objects.create(
            home_team='سپاهان', away_team='ب', stadium=self.stadium,
            date_time=timezone.now() + timedelta(days=10),
        )
        fan = User.objects.create_user(
            username='fanmap', password='pw12345',
            national_code='1272761371', phone_number='09138162670',
        )
        Ticket.objects.create(
            user=fan, match=self.m1, seat=self.seat1,
            national_code='1272761371', full_name='کسری نیک شبانی',
            status='paid', price=100000,
        )
        Ticket.objects.create(
            user=fan, match=self.m2, seat=self.seat2,
            national_code='1272761371', full_name='کسری نیک شبانی',
            status='paid', price=100000,
        )
        self.client.force_login(self.admin)

    def test_page_loads_and_marks_loyal_isfahan_buyer(self):
        resp = self.client.get('/accounts/admin/fan-map/')
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()
        self.assertIn('نقشه هواداران استان اصفهان', body)
        self.assertIn('اصفهان', body)
        self.assertIn('1272761371', body)
        self.assertContains(resp, 'هوادار وفادار')
