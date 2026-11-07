from datetime import timedelta
from unittest.mock import patch
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from accounts.models import EventSubmission, User
from accounts import tests_programs as program_fixtures
from matches.models import (Match, MatchBlockPrice, MatchRowPrice, MatchSeatPrice, MatchSeat,
                            Row, Seat, Stadium, Block, get_seat_price_map)
from payments.models import Payment
from tickets.models import Ticket


class StaffPricingTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        program_fixtures.OrganizerProgramTests.setUpTestData.__func__(cls)
        cls.another_row = Row.objects.create(block=cls.block, number=2)
        cls.extra = Seat.objects.create(row=cls.another_row, number=1)
        MatchSeat.objects.bulk_create([MatchSeat(match=item, seat=cls.extra) for item in (cls.first, cls.second, cls.foreign_session)])

    def setUp(self):
        cache.clear()
        self.admin = User.objects.create_user(username='pricing-staff', is_staff=True)
        Ticket.objects.filter(match=self.first, status='pending').delete()
        self.client.force_login(self.admin)
        self.url = reverse('management:session_pricing', args=[self.first.pk])

    def change(self, **extra):
        payload = dict(scope='session', target='row', row=self.row.pk, price='۳۵۰٬۰۰۰', action='apply')
        payload.update(extra)
        return self.client.post(self.url, payload)

    def test_admin_navigation_and_regular_user_protection(self):
        self.assertContains(self.client.get(self.url), 'بازه قیمت فعلی هر ردیف')
        self.client.force_login(self.owner)
        self.assertEqual(self.change().status_code, 302)
        self.assertFalse(MatchRowPrice.objects.exists())
        self.client.logout()
        self.assertEqual(self.client.get(self.url).status_code, 302)

    def test_row_price_converts_toman_and_preserves_venue_other_sessions_and_sold_tickets(self):
        self.assertRedirects(self.change(), self.url)
        self.assertEqual(MatchRowPrice.objects.get().price, 3500000)
        self.block.refresh_from_db()
        self.assertEqual(self.block.price, 50000)
        self.assertEqual(get_seat_price_map(self.second, self.seats)[self.seats[0].pk], 50000)
        self.assertEqual(Ticket.objects.get(match=self.first, seat=self.seats[0], status='paid').price, 1200000)
        self.assertEqual(get_seat_price_map(self.first, [self.extra])[self.extra.pk], 50000)

    def test_seat_price_precedes_row_and_zero_is_a_real_price_then_reset_inherits(self):
        self.change()
        response = self.change(target='seats', seat_numbers='۲، ۴-۶', price='۰')
        self.assertRedirects(response, self.url)
        self.assertEqual(MatchSeatPrice.objects.count(), 4)
        prices = get_seat_price_map(self.first, self.seats)
        self.assertEqual(prices[self.seats[0].pk], 3500000)
        self.assertEqual(prices[self.seats[1].pk], 0)
        self.assertRedirects(self.change(target='seats', seat_numbers='۲، ۴-۶', price='', action='reset'), self.url)
        self.assertFalse(MatchSeatPrice.objects.exists())
        self.assertEqual(get_seat_price_map(self.first, self.seats)[self.seats[1].pk], 3500000)
        self.change(action='reset', price='')
        self.assertEqual(get_seat_price_map(self.first, self.seats)[self.seats[1].pk], 50000)

    def test_future_scope_changes_only_future_sessions_in_same_hall_for_owned_program(self):
        past = Match.objects.create(event=self.event, stadium=self.venue, date_time=timezone.now()-timedelta(days=1))
        cancelled = Match.objects.create(event=self.event, stadium=self.venue, date_time=self.first.date_time, is_cancelled=True)
        other_hall = Stadium.objects.create(name='سالن متفاوت', capacity=1)
        different = Match.objects.create(event=self.event, stadium=other_hall, date_time=self.first.date_time)
        self.assertRedirects(self.change(scope='future'), self.url)
        self.assertEqual(set(MatchRowPrice.objects.values_list('match_id', flat=True)), {self.first.pk, self.second.pk})
        self.assertFalse(MatchRowPrice.objects.filter(match_id__in=[past.pk, cancelled.pk, different.pk, self.foreign_session.pk]).exists())

    def test_invalid_selection_or_amount_cannot_create_rules(self):
        foreign_block = Block.objects.create(stadium=Stadium.objects.create(name='بیگانه', capacity=1), name='بیگانه')
        foreign_row = Row.objects.create(block=foreign_block, number=1)
        for payload in [dict(price='-۱'), dict(price='۱۰۰۰۰۰۰۰۰۰'), dict(row=''), dict(row=foreign_row.pk),
                        dict(target='seats', seat_numbers='۹۹'), dict(target='seats', seat_numbers='۴-۲'),
                        dict(target='seats', seat_numbers='۱-۹۹۹۹'), dict(scope=str(self.foreign_session.pk))]:
            with self.subTest(payload=payload):
                self.assertEqual(self.change(**payload).status_code, 200)
                self.assertFalse(MatchRowPrice.objects.exists())
                self.assertFalse(MatchSeatPrice.objects.exists())

    def test_base_price_is_session_scoped_and_does_not_erase_row_or_seat_rules(self):
        self.change()
        self.change(target='seats', seat_numbers='۳', price='۴۰۰۰۰۰')
        self.assertRedirects(self.change(target='base', price='۲۵۰۰۰۰'), self.url)
        self.assertEqual(MatchBlockPrice.objects.get().price, 2500000)
        self.assertEqual(get_seat_price_map(self.first, [self.extra])[self.extra.pk], 2500000)
        self.assertEqual(get_seat_price_map(self.first, self.seats)[self.seats[0].pk], 3500000)
        self.assertEqual(get_seat_price_map(self.first, self.seats)[self.seats[2].pk], 4000000)
        self.assertRedirects(self.change(target='base', action='reset', price=''), self.url)
        self.assertFalse(MatchBlockPrice.objects.exists())

    def test_live_reservation_blocks_price_changes_atomically_across_sessions(self):
        item = MatchSeat.objects.get(match=self.second, seat=self.seats[-1])
        item.reserved_until = timezone.now() + timedelta(minutes=5)
        item.save(update_fields=['reserved_until'])
        response = self.change(scope='future')
        self.assertContains(response, 'رزرو موقت دارند')
        self.assertFalse(MatchRowPrice.objects.exists())
        item.reserved_until = None
        item.save(update_fields=['reserved_until'])
        with patch('accounts.program_pricing.SeatReservation.get_reserved_map', return_value={item.pk: {'user_id': self.buyer.pk}}):
            self.assertContains(self.change(scope='future'), 'رزرو موقت دارند')
        self.assertFalse(MatchRowPrice.objects.exists())

    def test_pending_gateway_payment_blocks_changes_but_not_completed_payment(self):
        payment = Payment.objects.create(user=self.buyer, purpose='ticket_purchase', match=self.first, gateway_amount=100000)
        self.assertContains(self.change(), 'پرداخت در حال انجام دارد')
        self.assertFalse(MatchRowPrice.objects.exists())
        payment.status = 'success'
        payment.save(update_fields=['status'])
        self.assertRedirects(self.change(), self.url)

    def test_past_or_cancelled_session_and_quantity_or_unpublished_program_are_not_editable(self):
        Match.objects.filter(pk=self.first.pk).update(date_time=timezone.now()-timedelta(days=1))
        self.assertContains(self.change(), 'سانس پایان‌یافته یا لغوشده')
        self.assertFalse(MatchRowPrice.objects.exists())
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get(reverse('accounts:program_pricing', args=[self.draft.pk])).status_code, 404)

    def test_report_shows_program_totals_and_current_session_sales_together(self):
        self.client.force_login(self.owner)
        response = self.client.get(reverse('accounts:program_session', args=[self.proposal.pk, self.first.pk]))
        self.assertEqual(response.context['program_stats']['revenue'], 3500000)
        self.assertEqual(response.context['stats']['revenue'], 1200000)
        self.assertContains(response, 'فروش کل برنامه')
        self.assertContains(response, 'فروش این سانس')
        self.assertNotContains(response, 'قیمت‌گذاری این سانس')
        self.assertContains(response, 'ثبت تیکت تغییرات')
