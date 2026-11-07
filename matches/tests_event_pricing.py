from django.db import transaction
from django.test import TestCase
from django.urls import reverse
from matches import tests_events as event_fixtures
from matches.models import MatchRowPrice, MatchSeatPrice, MatchBlockPrice, get_seat_price_map
from tickets.models import Order, Ticket, DiscountCode
from wallet.models import Wallet
from payments.models import Payment
from payments.views import _finalize_ticket_purchase


class CulturalPriceTests(TestCase):
    setUp = event_fixtures.EventTests.setUp
    reserve = event_fixtures.EventTests.reserve
    payload = event_fixtures.EventTests.payload

    def tariff(self):
        MatchBlockPrice.objects.create(match=self.first, block=self.block, price=100000)
        MatchRowPrice.objects.create(match=self.first, row=self.row, price=200000)
        MatchSeatPrice.objects.create(match=self.first, seat=self.seats[0], price=300000)

    def test_checkout_and_wallet_issuance_use_individual_tariffs(self):
        self.tariff()
        seats = self.reserve()
        response = self.client.get(reverse('tickets:ticket_info', args=[self.first.pk]))
        self.assertEqual(response.context['total_price'], 500000)
        self.assertEqual([item['price'] for item in response.context['seats_data']], [300000, 200000])
        Wallet.objects.update_or_create(user=self.user, defaults={'balance': 500000})
        payload = self.payload(seats)
        payload.update(use_wallet='true', wallet_amount='500000')
        self.assertRedirects(self.client.post(reverse('tickets:ticket_info', args=[self.first.pk]), payload), reverse('tickets:user_tickets'))
        self.assertEqual(Order.objects.get().total_amount, 500000)
        self.assertEqual(set(Ticket.objects.values_list('price', flat=True)), {300000, 200000})

    def test_gateway_issuance_uses_same_tariffs_and_discount_rounding(self):
        self.tariff()
        seats = self.reserve()
        DiscountCode.objects.create(code='ROWPRICE', discount_percent=10, is_active=True)
        payment = Payment.objects.create(user=self.user, purpose='ticket_purchase', match=self.first,
            buyer_info=self.payload(seats), gateway_amount=450000, discount_code='ROWPRICE', discount_percent=10)
        with transaction.atomic():
            success, message = _finalize_ticket_purchase(payment, 450000)
        self.assertTrue(success, message)
        self.assertEqual(Order.objects.get().total_amount, 450000)
        self.assertEqual(set(Ticket.objects.values_list('price', flat=True)), {270000, 180000})

    def test_public_starting_price_sections_and_seat_map_use_effective_prices(self):
        self.tariff()
        detail = self.client.get(reverse('matches:event_detail', args=[self.event.pk]))
        self.assertEqual(detail.context['starting_price'], 100000)  # Other session retains its default.
        self.second.ticket_sales_enabled = False
        self.second.save(update_fields=['ticket_sales_enabled'])
        detail = self.client.get(reverse('matches:event_detail', args=[self.event.pk]))
        self.assertEqual(detail.context['starting_price'], 200000)
        response = self.client.get(reverse('matches:select_block', args=[self.first.pk]))
        self.assertEqual(response.context['blocks'][0].session_price, 200000)
        self.assertEqual(response.context['blocks'][0].session_max_price, 300000)
        session = self.client.session
        session['selected_block_id'] = self.block.pk
        session.save()
        response = self.client.get(reverse('matches:block_map', args=[self.first.pk]))
        self.assertEqual([item['price'] for item in response.context['map_data'][0]['seats']], [300000, 200000, 200000])
        self.assertContains(response, 'data-price="300000"')

    def test_free_seat_keeps_zero_and_sport_sessions_keep_existing_block_pricing(self):
        self.tariff()
        MatchSeatPrice.objects.filter(match=self.first, seat=self.seats[0]).update(price=0)
        self.assertEqual(get_seat_price_map(self.first, self.seats)[self.seats[0].pk], 0)
        self.event.category = 'sport'
        self.event.save(update_fields=['category'])
        self.first.refresh_from_db()
        self.assertEqual(get_seat_price_map(self.first, self.seats)[self.seats[0].pk], 100000)
