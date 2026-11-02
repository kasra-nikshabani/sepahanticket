from datetime import timedelta
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from matches.models import Stadium, Block, Row, Seat, Match, MatchSeat
from tickets.models import Ticket, SpecialCode

User = get_user_model()

class MatchVipAssignTests(TestCase):
    def setUp(self):
        from accounts.models import SiteSettings
        s = SiteSettings.get_solo(); s.block_foreign_ips = False; s.save()
        self.admin = User.objects.create_user(username='adm', password='x', is_staff=True, user_type='admin')
        self.vip1 = User.objects.create_user(username='vip1', password='x', user_type='vip', first_name='ویژه۱')
        self.vip2 = User.objects.create_user(username='vip2', password='x', user_type='vip', first_name='ویژه۲')
        self.stadium = Stadium.objects.create(name='نقش جهان', capacity=100)
        self.block = Block.objects.create(stadium=self.stadium, name='VIP', price=0, zone_type='vip')
        self.row = Row.objects.create(block=self.block, number=1)
        for i in range(1, 6):
            Seat.objects.create(row=self.row, number=i)
        self.match = Match.objects.create(
            home_team='سپاهان', away_team='آلومینیوم', stadium=self.stadium,
            date_time=timezone.now() + timedelta(days=3),
        )
        self.client.force_login(self.admin)

    def test_page_lists_vips(self):
        r = self.client.get(f'/tickets/admin/match/{self.match.id}/vip-assign/')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'ویژه۱')
        self.assertContains(r, 'ویژه۲')

    def test_single_ticket_and_code(self):
        url = f'/tickets/admin/match/{self.match.id}/vip-assign/'
        r = self.client.post(url, {
            'action': 'issue_tickets_single', 'user_id': self.vip1.id,
            'quantity': 1, 'block_id': self.block.id,
        })
        self.assertEqual(r.status_code, 302)
        self.assertEqual(Ticket.objects.filter(user=self.vip1, match=self.match, status='admin_assigned').count(), 1)
        r = self.client.post(url, {
            'action': 'issue_codes_single', 'user_id': self.vip2.id, 'quantity': 2,
        })
        self.assertEqual(r.status_code, 302)
        self.assertEqual(SpecialCode.objects.filter(vip_owner=self.vip2, match=self.match).count(), 2)

    def test_batch_codes(self):
        url = f'/tickets/admin/match/{self.match.id}/vip-assign/'
        r = self.client.post(url, {
            'action': 'issue_codes_batch',
            'user_ids': [self.vip1.id, self.vip2.id],
            'quantity': 1,
        })
        self.assertEqual(r.status_code, 302)
        self.assertEqual(SpecialCode.objects.filter(match=self.match).count(), 2)
