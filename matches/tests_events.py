from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.db import IntegrityError, transaction, connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TestCase, TransactionTestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import SiteSettings
from tickets.models import DiscountCode, Order, Ticket, is_free_for_age
from tickets.reservation import SeatReservation
from wallet.models import Wallet
from .forms import MatchForm
from .models import Block, Event, EventRating, EventSceneImage, Match, MatchBlockPrice, MatchSeat, Row, Seat, Stadium, get_basa_discount_percent


class EventTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = get_user_model().objects.create_user(username='buyer', password='test')
        self.staff = get_user_model().objects.create_user(username='staff', password='test', is_staff=True)
        self.venue = Stadium.objects.create(name='سالن فرهنگ', city='اصفهان', address='خیابان فرهنگ', capacity=3)
        self.block = Block.objects.create(stadium=self.venue, name='بخش اصلی', zone_type='away', price=100000)
        self.row = Row.objects.create(block=self.block, number=1)
        self.seats = [Seat.objects.create(row=self.row, number=n) for n in (1, 2, 3)]
        self.event = Event.objects.create(title='نمایش تازه', category='theater', artists='هنرمند نمونه')
        self.first = Match.objects.create(event=self.event, stadium=self.venue, date_time=timezone.now()+timedelta(days=2))
        self.second = Match.objects.create(event=self.event, stadium=self.venue, date_time=timezone.now()+timedelta(days=3))
        self.client.force_login(self.user)
        self.qr_patch = patch.object(Ticket, 'generate_qr_code')
        self.qr_patch.start()
        self.addCleanup(self.qr_patch.stop)

    def reserve(self, count=2):
        seats = list(self.first.match_seats.order_by('seat__number')[:count])
        for seat in seats:
            ok, _ = SeatReservation.reserve(seat.pk, self.user.pk, self.first.pk)
            self.assertTrue(ok)
            seat.is_available = False
            seat.reserved_until = timezone.now()+timedelta(minutes=10)
            seat.save()
        session = self.client.session
        session['selected_seats'] = [seat.pk for seat in seats]
        session['match_id'] = self.first.pk
        session['reserved_at'] = timezone.now().isoformat()
        session.save()
        return seats

    def payload(self, seats):
        data = {'match_id': self.first.pk, 'amount': 1}
        for seat in seats:
            data[f'match_seat_id_{seat.pk}'] = seat.pk
            data[f'full_name_{seat.pk}'] = 'خریدار همراه'
        return data

    def test_inventory_is_independent_per_session(self):
        first = self.first.match_seats.get(seat=self.seats[0])
        first.is_available = False
        first.save()
        self.assertTrue(self.second.match_seats.get(seat=self.seats[0]).is_available)
        with self.assertRaises(IntegrityError), transaction.atomic():
            MatchSeat.objects.create(match=self.first, seat=self.seats[0])

    def test_sales_status_distinguishes_closed_cancelled_ended_and_sold_out(self):
        from .event_views import prepare_session_status
        self.first.ticket_sales_enabled = False
        prepare_session_status(self.first)
        self.assertEqual(self.first.sale_status, 'closed')
        self.assertFalse(self.first.can_purchase)
        self.first.is_cancelled = True
        prepare_session_status(self.first)
        self.assertEqual(self.first.sale_status, 'cancelled')
        self.first.is_cancelled = False
        self.first.ticket_sales_enabled = True
        self.first.date_time = timezone.now() - timedelta(days=1)
        prepare_session_status(self.first)
        self.assertEqual(self.first.sale_status, 'ended')
        self.first.date_time = timezone.now() + timedelta(days=1)
        for inventory in self.first.match_seats.all():
            Ticket.objects.create(user=self.user, match=self.first, seat=inventory.seat,
                match_seat=inventory, full_name='خریدار', national_code='', price=100000, status='paid')
        prepare_session_status(self.first)
        self.assertEqual(self.first.sale_status, 'sold_out')
        self.assertFalse(self.first.can_purchase)

    def test_temporary_reservations_are_not_reported_as_sold_out(self):
        from .event_views import prepare_session_status
        self.first.match_seats.update(is_available=False, reserved_until=timezone.now() + timedelta(minutes=10))
        prepare_session_status(self.first)
        self.assertEqual(self.first.sale_status, 'reserved')
        self.first.match_seats.update(reserved_until=timezone.now() - timedelta(minutes=1))
        prepare_session_status(self.first)
        self.assertEqual(self.first.sale_status, 'open')
        self.assertTrue(self.first.can_purchase)

    def test_detail_and_category_explain_the_current_sales_state(self):
        self.first.ticket_sales_enabled = False
        self.first.save()
        self.second.date_time = timezone.now() - timedelta(days=1)
        self.second.save()
        response = self.client.get(reverse('matches:event_detail', args=[self.event.pk]))
        self.assertContains(response, 'فروش این سانس بسته است')
        self.assertNotContains(response, reverse('matches:select_floor', args=[self.first.pk]))
        response = self.client.get(reverse('matches:event_catalogue'), {'category': 'theater', 'sort': 'new'})
        self.assertEqual(response.context['catalogue_title'], 'نمایش‌ها')
        self.assertEqual(response.context['catalogue_noun'], 'نمایش')
        self.first.date_time = timezone.now() - timedelta(days=2)
        self.first.save()
        response = self.client.get(reverse('matches:event_detail', args=[self.event.pk]))
        self.assertContains(response, 'اجراهای این برنامه پایان یافته')

    def test_sessions_group_by_local_day_and_nearest_buyable_skips_closed_sessions(self):
        tomorrow = timezone.localtime().replace(hour=18, minute=0, second=0, microsecond=0) + timedelta(days=2)
        self.first.date_time = tomorrow
        self.first.ticket_sales_enabled = False
        self.first.save()
        self.second.date_time = tomorrow + timedelta(hours=2)
        self.second.save()
        third = Match.objects.create(event=self.event, stadium=self.venue, date_time=tomorrow+timedelta(days=1))
        response = self.client.get(reverse('matches:event_detail', args=[self.event.pk]))
        groups = response.context['session_groups']
        self.assertEqual([len(g['sessions']) for g in groups], [2, 1])
        self.assertEqual(response.context['nearest_session'].pk, self.second.pk)
        self.assertEqual(groups[0]['sessions'][1].available_count, 3)
        self.assertContains(response, 'نزدیک‌ترین سانس قابل خرید')
        self.second.match_seats.update(is_available=False, reserved_until=timezone.now()+timedelta(minutes=10))
        response = self.client.get(reverse('matches:event_detail', args=[self.event.pk]))
        self.assertEqual(response.context['nearest_session'].pk, third.pk)

    def test_persian_toman_wallet_purchase_keeps_rial_accounting(self):
        seats = self.reserve()
        Wallet.objects.update_or_create(user=self.user, defaults={'balance': 200000})
        data = self.payload(seats)
        data.update(use_wallet='true', wallet_amount_toman='۲۰٬۰۰۰', wallet_amount='1')
        response = self.client.post(reverse('tickets:ticket_info', args=[self.first.pk]), data)
        self.assertRedirects(response, reverse('tickets:user_tickets'))
        self.assertEqual(Wallet.objects.get(user=self.user).balance, 0)
        self.assertEqual(Order.objects.get(match=self.first).total_amount, 200000)
        self.assertEqual(Ticket.objects.filter(match=self.first, status='paid').count(), 2)
        from accounts.models import Notification
        self.assertEqual(Notification.objects.get(recipient=self.user).kind, 'purchase')

    @patch('payments.views.ZibalClient')
    def test_toman_wallet_partial_payment_has_correct_gateway_amount(self, gateway):
        seats = self.reserve()
        Wallet.objects.update_or_create(user=self.user, defaults={'balance': 100000})
        data = self.payload(seats)
        data.update(use_wallet='true', wallet_amount_toman='۵۰۰۰٫۱')
        gateway.return_value.payment_request.return_value = {'trackId': 123}
        gateway.return_value.generate_payment_url.return_value = '/test-gateway/'
        response = self.client.post(reverse('tickets:ticket_info', args=[self.first.pk]), data)
        self.assertEqual(response.status_code, 302)
        from payments.models import Payment
        payment = Payment.objects.get()
        self.assertEqual(payment.wallet_amount_used, 50001)
        self.assertEqual(payment.gateway_amount, 149999)
        self.assertEqual(gateway.return_value.payment_request.call_args.kwargs['amount'], 149999)

    def test_wallet_input_rejects_invalid_amount_and_preserves_buyer_names(self):
        seats = self.reserve()
        data = self.payload(seats)
        data.update(use_wallet='true', wallet_amount_toman='۱۰۰٫۰۰۱')
        response = self.client.post(reverse('tickets:ticket_info', args=[self.first.pk]), data)
        self.assertContains(response, 'مبلغ کیف پول را به تومان وارد کنید')
        self.assertContains(response, 'value="خریدار همراه"')
        self.assertFalse(Order.objects.exists())
        self.assertFalse(Ticket.objects.exists())

    def test_catalogue_groups_sessions_and_filters(self):
        response = self.client.get(reverse('matches:event_catalogue'))
        self.assertContains(response, self.event.title)
        self.assertEqual(response.context['page_obj'].paginator.count, 1)
        self.assertEqual(len(response.context['page_obj'][0].upcoming_sessions), 2)
        for params, expected in [({'q': 'هنرمند'}, 1), ({'category': 'concert'}, 0), ({'city': 'تهران'}, 0), ({'city': 'اصفهان'}, 1)]:
            response = self.client.get(reverse('matches:event_catalogue'), params)
            self.assertEqual(response.context['page_obj'].paginator.count, expected)

    def test_card_rating_uses_real_votes_and_persian_numbers(self):
        response = self.client.get(reverse('matches:home'))
        self.assertContains(response, 'بدون امتیاز')
        EventRating.objects.create(event=self.event, user=self.user, score=4)
        EventRating.objects.create(event=self.event, user=self.staff, score=5)
        for url in (reverse('matches:home'), reverse('matches:event_catalogue')):
            response = self.client.get(url)
            event = response.context['sections'][0]['events'][0] if 'sections' in response.context else response.context['page_obj'][0]
            self.assertEqual(event.rating_average, 4.5)
            self.assertEqual(event.rating_count, 2)
            self.assertContains(response, '۴٫۵')
            self.assertContains(response, '۱۲۰ دقیقه')

    def test_rating_is_unique_and_limited_to_five(self):
        EventRating.objects.create(event=self.event, user=self.user, score=4)
        with self.assertRaises(IntegrityError), transaction.atomic():
            EventRating.objects.create(event=self.event, user=self.user, score=5)
        with self.assertRaises(IntegrityError), transaction.atomic():
            EventRating.objects.create(event=self.event, user=self.staff, score=6)

    def test_homepage_shows_five_latest_in_each_category(self):
        expected = {}
        for category in ('theater', 'concert', 'event'):
            events = [Event.objects.create(title=f'{category} {number}', category=category)
                      for number in range(6)]
            expected[category] = [event.pk for event in reversed(events[-5:])]
        Event.objects.create(title='مخفی', category='concert', is_active=False)
        Event.objects.create(title='ورزش', category='sport')
        response = self.client.get(reverse('matches:home'))
        sections = response.context['sections']
        self.assertEqual([s['category'] for s in sections], ['theater', 'concert', 'event'])
        for section in sections:
            self.assertEqual([event.pk for event in section['events']], expected[section['category']])
            url = reverse('matches:event_catalogue') + '?category=' + section['category'] + '&amp;sort=new'
            self.assertContains(response, url)
        self.assertNotContains(response, 'filter-sidebar')
        self.assertNotContains(response, 'banner-caption')

    def test_category_all_link_lists_more_than_homepage_limit(self):
        for number in range(6):
            Event.objects.create(title=f'نمایش {number}', category='theater')
        response = self.client.get(reverse('matches:event_catalogue'), {'category': 'theater', 'sort': 'new'})
        self.assertEqual(response.context['page_obj'].paginator.count, 7)

    def test_didavar_header_is_shared_by_event_and_login_pages(self):
        self.client.logout()
        for url in (reverse('matches:home'), reverse('accounts:phone_login'),
                    reverse('matches:event_detail', args=[self.event.pk])):
            response = self.client.get(url)
            self.assertContains(response, 'دیدآور')
            self.assertContains(response, 'هر رویداد، یک دیدار.')
            self.assertContains(response, 'home-header')
            self.assertContains(response, reverse('matches:event_catalogue') + '?category=concert&amp;sort=new')
            self.assertNotContains(response, 'category=sport')

    def test_hidden_events_and_past_sessions_are_not_listed(self):
        self.event.is_active = False
        self.event.save()
        self.assertEqual(self.client.get(reverse('matches:event_catalogue')).context['page_obj'].paginator.count, 0)
        self.assertEqual(self.client.get(reverse('matches:event_detail', args=[self.event.pk])).status_code, 404)
        self.event.is_active = True
        self.event.save()
        self.event.sessions.update(date_time=timezone.now()-timedelta(days=1))
        self.assertEqual(self.client.get(reverse('matches:event_catalogue')).context['page_obj'].paginator.count, 0)

    def test_event_detail_lists_both_sessions(self):
        response = self.client.get(reverse('matches:event_detail', args=[self.event.pk]))
        self.assertContains(response, reverse('matches:select_floor', args=[self.first.pk]))
        self.assertContains(response, reverse('matches:select_floor', args=[self.second.pk]))

    def test_detail_media_is_optional_and_supports_photos_teaser_or_both(self):
        url = reverse('matches:event_detail', args=[self.event.pk])
        response = self.client.get(url)
        self.assertNotContains(response, 'id="event-media"')
        self.event.teaser = 'event_teasers/demo.mp4'
        self.event.cover = 'event_covers/demo.jpg'
        self.event.save()
        response = self.client.get(url)
        self.assertContains(response, 'id="event-media"')
        self.assertContains(response, self.event.teaser.url)
        self.assertContains(response, self.event.cover.url)
        self.assertNotContains(response, 'class="scene-gallery"')
        second = EventSceneImage.objects.create(event=self.event, image='event_scenes/second.jpg', order=2)
        first = EventSceneImage.objects.create(event=self.event, image='event_scenes/first.jpg', order=1, caption='<script>alert(1)</script>')
        response = self.client.get(url)
        self.assertEqual([photo.pk for photo in response.context['scene_images']], [first.pk, second.pk])
        self.assertContains(response, 'class="scene-gallery"')
        self.assertContains(response, '&lt;script&gt;')
        self.assertEqual(len(response.context['venues']), 1)
        self.event.teaser = ''
        self.event.save()
        response = self.client.get(url)
        self.assertContains(response, 'class="scene-gallery"')
        self.assertNotContains(response, '<video')

    def test_admin_can_edit_scene_caption_and_reject_invalid_teaser(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        self.client.force_login(self.staff)
        photo = EventSceneImage.objects.create(event=self.event, image='event_scenes/photo.jpg')
        data = {'title': self.event.title, 'category': 'theater', 'duration_minutes': 90,
                'is_active': 'on', 'scenes-TOTAL_FORMS': 1, 'scenes-INITIAL_FORMS': 1,
                'scenes-0-id': photo.pk, 'scenes-0-event': self.event.pk,
                'scenes-0-caption': 'تصویر صحنه', 'scenes-0-order': 2}
        url = reverse('matches:event_edit', args=[self.event.pk])
        response = self.client.post(url, data)
        self.assertRedirects(response, reverse('matches:event_list'))
        photo.refresh_from_db()
        self.assertEqual(photo.caption, 'تصویر صحنه')
        data['teaser'] = SimpleUploadedFile('invalid.html', b'<html></html>', content_type='text/html')
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, 200)
        self.assertIn('teaser', response.context['form'].errors)

    def test_catalogue_time_filter_and_soon_sort(self):
        other = Event.objects.create(title='کنسرت نزدیک', category='concert')
        Match.objects.create(event=other, stadium=self.venue, date_time=timezone.now()+timedelta(minutes=5))
        response = self.client.get(reverse('matches:event_catalogue'), {'sort': 'soon', 'period': 'week'})
        self.assertEqual(response.context['page_obj'][0].pk, other.pk)
        response = self.client.get(reverse('matches:event_catalogue'), {'period': 'today'})
        self.assertNotIn(self.event.pk, [event.pk for event in response.context['page_obj']])
        self.second.date_time = timezone.now()+timedelta(days=10)
        self.second.save()
        response = self.client.get(reverse('matches:event_catalogue'), {'period': 'week', 'category': 'theater'})
        self.assertEqual(len(response.context['page_obj'][0].upcoming_sessions), 1)

    def test_catalogue_price_respects_session_overrides_and_disabled_blocks(self):
        from .models import MatchBlockActive
        MatchBlockPrice.objects.create(match=self.first, block=self.block, price=220000)
        self.second.ticket_sales_enabled = False
        self.second.save()
        response = self.client.get(reverse('matches:event_catalogue'))
        self.assertEqual(response.context['page_obj'][0].starting_price, 220000)
        self.assertContains(response, '۲۲٬۰۰۰')
        MatchBlockActive.objects.create(match=self.first, block=self.block, is_active=False)
        response = self.client.get(reverse('matches:event_catalogue'))
        self.assertIsNone(response.context['page_obj'][0].starting_price)

    def test_cancelled_session_has_no_purchase_link_in_detail(self):
        self.first.is_cancelled = True
        self.first.save()
        response = self.client.get(reverse('matches:event_detail', args=[self.event.pk]))
        self.assertNotContains(response, reverse('matches:select_floor', args=[self.first.pk]))

    def test_cultural_purchase_skips_team_selection(self):
        response = self.client.get(reverse('matches:select_floor', args=[self.first.pk]))
        self.assertRedirects(response, reverse('matches:select_block', args=[self.first.pk]))
        response = self.client.get(reverse('matches:select_block', args=[self.first.pk]))
        self.assertContains(response, self.block.name)
        self.assertNotContains(response, 'ورزشگاه نقش جهان')
        response = self.client.post(reverse('matches:select_block', args=[self.first.pk]), {'block_id': self.block.pk})
        self.assertRedirects(response, reverse('matches:block_map', args=[self.first.pk]))

    def test_section_from_another_venue_is_rejected(self):
        venue = Stadium.objects.create(name='سالن دیگر', capacity=1)
        block = Block.objects.create(stadium=venue, name='غریبه')
        response = self.client.post(reverse('matches:select_block', args=[self.first.pk]), {'block_id': block.pk})
        self.assertEqual(response.status_code, 404)
        session = self.client.session
        session['selected_block_id'] = block.pk
        session.save()
        self.assertEqual(self.client.get(reverse('matches:block_map', args=[self.first.pk])).status_code, 404)

    def test_cancelled_or_hidden_session_cannot_be_purchased(self):
        self.first.is_cancelled = True
        self.first.save()
        self.assertFalse(self.first.sales_available)
        response = self.client.get(reverse('matches:select_floor', args=[self.first.pk]))
        self.assertRedirects(response, reverse('matches:home'))

    def test_price_override_does_not_change_other_sessions(self):
        self.client.force_login(self.staff)
        self.client.post(reverse('matches:admin_match_block_prices', args=[self.first.pk]), {f'price_{self.block.pk}': 200000})
        self.block.refresh_from_db()
        self.assertEqual(self.block.price, 100000)
        self.assertEqual(MatchBlockPrice.objects.get(match=self.first, block=self.block).price, 200000)
        self.assertFalse(MatchBlockPrice.objects.filter(match=self.second).exists())

    def test_nonfinite_and_fractional_prices_are_rejected(self):
        self.client.force_login(self.staff)
        for price in ['NaN', 'Infinity', '0.5', '-1']:
            self.client.post(reverse('matches:admin_match_block_prices', args=[self.first.pk]), {f'price_{self.block.pk}': price})
        self.assertFalse(MatchBlockPrice.objects.filter(match=self.first).exists())

    def test_session_form_requires_event_and_time(self):
        data = {'event': self.event.pk, 'stadium': self.venue.pk, 'match_date': '2026-12-01', 'match_time': '19:30', 'is_active': True, 'ticket_sales_enabled': True}
        form = MatchForm(data)
        self.assertTrue(form.is_valid(), form.errors)
        session = form.save()
        self.assertEqual(session.event, self.event)
        self.assertTrue(session.has_time)
        self.assertEqual(timezone.localtime(session.date_time).hour, 19)
        data.pop('match_time')
        self.assertFalse(MatchForm(data).is_valid())

    def test_venue_change_is_rejected_after_inventory_creation(self):
        other = Stadium.objects.create(name='دیگر', capacity=1)
        form = MatchForm({'event': self.event.pk, 'stadium': other.pk, 'match_date': '2026-12-01', 'match_time': '19:30'}, instance=self.first)
        self.assertFalse(form.is_valid())
        self.assertIn('stadium', form.errors)

    def test_event_management_requires_staff(self):
        response = self.client.get(reverse('matches:event_create'))
        self.assertEqual(response.status_code, 302)
        self.client.force_login(self.staff)
        self.assertEqual(self.client.get(reverse('matches:event_create')).status_code, 200)
        response = self.client.post(reverse('matches:event_create'), {'title': 'کنسرت جدید', 'category': 'concert', 'duration_minutes': 90, 'is_active': 'on', 'scenes-TOTAL_FORMS': 0, 'scenes-INITIAL_FORMS': 0})
        self.assertRedirects(response, reverse('matches:event_list'))
        self.assertTrue(Event.objects.filter(title='کنسرت جدید').exists())

    def test_sports_discount_policies_do_not_apply_to_cultural_sessions(self):
        config = SiteSettings.get_solo()
        config.free_under_15 = True
        config.save()
        self.assertFalse(is_free_for_age(10, match=self.first))
        self.assertEqual(get_basa_discount_percent(self.first), 0)

    def test_checkout_does_not_require_identity_inquiry(self):
        self.reserve()
        response = self.client.get(reverse('tickets:ticket_info', args=[self.first.pk]))
        self.assertContains(response, 'نام دارنده هر بلیط')
        self.assertNotContains(response, 'استعلام و تایید')
        self.assertNotContains(response, 'name="national_code_')

    def test_wallet_purchase_issues_multiple_tickets_without_national_code(self):
        seats = self.reserve()
        Wallet.objects.filter(user=self.user).update(balance=200000)
        if not Wallet.objects.filter(user=self.user).exists():
            Wallet.objects.create(user=self.user, balance=200000)
        data = self.payload(seats)
        data.update(use_wallet='true', wallet_amount=200000)
        response = self.client.post(reverse('tickets:ticket_info', args=[self.first.pk]), data)
        self.assertRedirects(response, reverse('tickets:user_tickets'))
        self.assertEqual(Ticket.objects.filter(match=self.first, status='paid').count(), 2)
        self.assertEqual(Wallet.objects.get(user=self.user).balance, 0)
        self.assertEqual(Order.objects.get(match=self.first).total_amount, 200000)
        self.assertTrue(all(ticket.national_code == '' for ticket in Ticket.objects.all()))
        self.assertTrue(self.second.match_seats.get(seat=self.seats[0]).is_available)

    def test_missing_name_and_another_users_reservation_are_rejected(self):
        seats = self.reserve()
        data = self.payload(seats)
        data[f'full_name_{seats[0].pk}'] = ''
        response = self.client.post(reverse('tickets:ticket_info', args=[self.first.pk]), data)
        self.assertContains(response, 'نام دارنده هر بلیط را وارد کنید')
        self.assertFalse(Order.objects.exists())
        SeatReservation.release(seats[0].pk, force=True)
        SeatReservation.reserve(seats[0].pk, self.staff.pk, self.first.pk)
        data = self.payload(seats)
        response = self.client.post(reverse('tickets:ticket_info', args=[self.first.pk]), data)
        self.assertContains(response, 'رزرو صندلی منقضی شده است')
        self.assertFalse(Order.objects.exists())

    @patch('payments.views.ZibalClient')
    def test_gateway_amount_is_calculated_on_server(self, gateway):
        seats = self.reserve()
        data = self.payload(seats)
        gateway.return_value.payment_request.return_value = {'trackId': 123}
        gateway.return_value.generate_payment_url.return_value = '/test-gateway/'
        response = self.client.post(reverse('tickets:ticket_info', args=[self.first.pk]), data)
        self.assertEqual(response.status_code, 302)
        from payments.models import Payment
        payment = Payment.objects.get()
        self.assertEqual(payment.gateway_amount, 200000)
        self.assertEqual(gateway.return_value.payment_request.call_args.kwargs['amount'], 200000)

    def test_full_discount_free_checkout(self):
        seats = self.reserve()
        DiscountCode.objects.create(code='FREE', discount_percent=100, match=self.first,
            expires_at=timezone.now()+timedelta(days=1), max_uses=10)
        data = self.payload(seats)
        data['discount_code'] = 'FREE'
        response = self.client.post(reverse('tickets:ticket_info', args=[self.first.pk]), data)
        self.assertRedirects(response, reverse('tickets:user_tickets'))
        self.assertEqual(Ticket.objects.count(), 2)
        self.assertEqual(Order.objects.get().total_amount, 0)

    @override_settings(GATE_USERS={'gate_event': {'password': 'test', 'zone': 'event', 'session_ids': []}})
    def test_event_gate_requires_authorized_session(self):
        response = self.client.post('/tickets/api/gate-login/', {'username': 'gate_event', 'password': 'test', 'match_id': self.first.pk}, content_type='application/json')
        self.assertEqual(response.status_code, 403)

    def test_event_gate_cannot_scan_ticket_for_another_session(self):
        ticket = Ticket.objects.create(user=self.user, match=self.second, seat=self.seats[0],
            match_seat=self.second.match_seats.get(seat=self.seats[0]), full_name='همراه', national_code='', price=100000)
        self.second.date_time = timezone.now()
        self.second.save()
        gates = {'gate_event': {'password': 'test', 'zone': 'event', 'session_ids': [self.first.pk]}}
        with override_settings(GATE_USERS=gates):
            login = self.client.post('/tickets/api/gate-login/', {'username': 'gate_event', 'password': 'test', 'match_id': self.first.pk}, content_type='application/json')
        self.assertEqual(login.status_code, 200)
        response = self.client.post('/tickets/api/scan-ticket/', {'qr_data': f'Ticket:{ticket.ticket_number}|Match:{self.second.pk}'}, content_type='application/json', HTTP_AUTHORIZATION='Bearer '+login.json()['token'])
        self.assertEqual(response.json()['status'], 'invalid')
        ticket.refresh_from_db()
        self.assertFalse(ticket.is_used)

    def test_valid_event_scan_then_duplicate_scan(self):
        self.first.date_time = timezone.now()
        self.first.save()
        ticket = Ticket.objects.create(user=self.user, match=self.first, seat=self.seats[0],
            match_seat=self.first.match_seats.get(seat=self.seats[0]), full_name='همراه', national_code='', price=100000)
        gates = {'gate_event': {'password': 'test', 'zone': 'event', 'session_ids': [self.first.pk]}}
        with override_settings(GATE_USERS=gates):
            login = self.client.post('/tickets/api/gate-login/', {'username': 'gate_event', 'password': 'test', 'match_id': self.first.pk}, content_type='application/json')
        for expected in ['valid', 'used']:
            response = self.client.post('/tickets/api/scan-ticket/', {'qr_data': f'Ticket:{ticket.ticket_number}|Match:{self.first.pk}'}, content_type='application/json', HTTP_AUTHORIZATION='Bearer '+login.json()['token'])
            self.assertEqual(response.json()['status'], expected)
        self.assertEqual(response.json()['full_name'], 'همراه')

    def test_gateway_finalization_issues_all_cultural_tickets(self):
        from payments.models import Payment
        from payments.views import _finalize_ticket_purchase
        seats = self.reserve()
        payment = Payment.objects.create(user=self.user, purpose='ticket_purchase',
            gateway_amount=200000, match_id=self.first.pk, buyer_info=self.payload(seats))
        with transaction.atomic():
            success, message = _finalize_ticket_purchase(payment, 200000)
        self.assertTrue(success, message)
        self.assertEqual(Ticket.objects.filter(match=self.first).count(), 2)
        self.assertEqual(Order.objects.get().total_amount, 200000)
        from accounts.models import Notification
        from accounts.notifications import notify_purchase
        notice = Notification.objects.get(kind='purchase')
        self.assertEqual(notice.recipient_id, self.user.pk)
        self.assertEqual(notice.action_url, reverse('tickets:user_tickets') + '?match_id=' + str(self.first.pk))
        notify_purchase(Order.objects.get())
        self.assertEqual(Notification.objects.filter(kind='purchase').count(), 1)

    def test_mismatched_seat_field_names_are_rejected(self):
        seats = self.reserve()
        data = self.payload(seats)
        data[f'match_seat_id_{self.second.match_seats.first().pk}'] = data.pop(f'match_seat_id_{seats[0].pk}')
        response = self.client.post(reverse('tickets:ticket_info', args=[self.first.pk]), data)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Order.objects.exists())

    @override_settings(REGISTRATION_IDENTITY_REQUIRED=False)
    def test_phone_registration_does_not_require_national_code_or_gender(self):
        from accounts.forms import PhoneRegisterForm
        form = PhoneRegisterForm({'first_name': 'مینا', 'last_name': 'نمونه', 'phone_number': '09120000001'})
        self.assertTrue(form.is_valid(), form.errors)
        self.assertIsNone(form.cleaned_data['national_code'])

    @override_settings(REGISTRATION_IDENTITY_REQUIRED=True)
    def test_legacy_registration_can_still_require_identity(self):
        from accounts.forms import PhoneRegisterForm
        form = PhoneRegisterForm({'first_name': 'مینا', 'last_name': 'نمونه', 'phone_number': '09120000001'})
        self.assertFalse(form.is_valid())
        self.assertIn('national_code', form.errors)


    @patch('accounts.views.get_valid_otp')
    def test_verified_phone_registration_creates_account_without_identity(self, valid_otp):
        self.client.logout()
        session = self.client.session
        session['otp_phone'] = '09120000001'
        session['pending_registration'] = {'phone_number': '09120000001',
            'national_code': None, 'first_name': 'مینا', 'last_name': 'نمونه', 'gender': ''}
        session.save()
        response = self.client.post(reverse('accounts:otp_verify'), {'otp_code': '1234'})
        self.assertRedirects(response, reverse('matches:home'))
        user = get_user_model().objects.get(phone_number='09120000001')
        self.assertEqual(user.username, '09120000001')
        self.assertIsNone(user.national_code)
        self.assertTrue(user.is_phone_verified)



class LegacyEventMigrationTests(TransactionTestCase):
    def test_backfill_keeps_session_and_order_ids(self):
        executor = MigrationExecutor(connection)
        old_target = [('matches', '0026_match_has_time')]
        executor.migrate(old_target)
        try:
            old_apps = executor.loader.project_state(old_target).apps
            venue = old_apps.get_model('matches', 'Stadium').objects.create(name='سالن قدیمی', capacity=10)
            fixture = old_apps.get_model('matches', 'Match').objects.create(
                home_team='سپاهان', away_team='حریف', stadium_id=venue.pk, date_time=timezone.now())
            # The order table stays in place throughout the event migration.
            user = get_user_model().objects.create_user(username='migration-user')
            order = Order.objects.create(user=user, match_id=fixture.pk, total_amount=100000, payment_status='paid')
            executor = MigrationExecutor(connection)
            executor.migrate(executor.loader.graph.leaf_nodes())
            session = Match.objects.get(pk=fixture.pk)
            self.assertEqual(session.event.title, 'سپاهان - حریف')
            self.assertEqual(session.event.category, 'sport')
            self.assertEqual(Order.objects.get(pk=order.pk).match_id, fixture.pk)
            self.assertFalse(session.is_cultural)
        finally:
            executor = MigrationExecutor(connection)
            executor.migrate(executor.loader.graph.leaf_nodes())
