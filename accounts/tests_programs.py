from datetime import timedelta
from importlib import import_module
from types import SimpleNamespace
from unittest.mock import patch
from django.apps import apps
from django.db import connection
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from accounts.models import User, EventSubmission
from matches.models import Event, Match, Stadium, Block, Row, Seat, MatchSeat, MatchBlockActive
from tickets.models import Ticket


class OrganizerProgramTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = User.objects.create_user(username='organizer', first_name='کسری', last_name='نیک شبانی')
        cls.other = User.objects.create_user(username='other-owner', first_name='بیگانه')
        cls.buyer = User.objects.create_user(username='buyer', first_name='مریم', last_name='خریدار')
        cls.event = Event.objects.create(title='نمایش متعلق به من', category='theater')
        cls.proposal = EventSubmission.objects.create(owner=cls.owner, title=cls.event.title, category='theater', published_event=cls.event)
        cls.draft = EventSubmission.objects.create(owner=cls.owner, title='پیش‌نویس من', category='event')
        cls.foreign_event = Event.objects.create(title='برنامه خصوصی دیگران', category='concert')
        cls.foreign_proposal = EventSubmission.objects.create(owner=cls.other, title=cls.foreign_event.title, category='concert', published_event=cls.foreign_event)
        cls.venue = Stadium.objects.create(name='سالن', capacity=8)
        cls.block = Block.objects.create(stadium=cls.venue, name='همکف')
        cls.row = Row.objects.create(block=cls.block, number=1)
        cls.seats = [Seat.objects.create(row=cls.row, number=i) for i in range(1, 9)]
        now = timezone.now() + timedelta(days=3)
        cls.first = Match.objects.create(event=cls.event, stadium=cls.venue, date_time=now, created_by=cls.owner)
        cls.second = Match.objects.create(event=cls.event, stadium=cls.venue, date_time=now + timedelta(days=1), created_by=cls.owner)
        cls.foreign_session = Match.objects.create(event=cls.foreign_event, stadium=cls.venue, date_time=now, created_by=cls.other)
        Ticket.objects.bulk_create([
            Ticket(user=cls.buyer, match=cls.first, seat=cls.seats[0], full_name='نگار صاحب بلیط', national_code='', price=1200000, status='paid', is_used=True),
            Ticket(user=cls.buyer, match=cls.first, seat=cls.seats[1], full_name='صاحب بلیط رایگان', national_code='', price=0, status='paid'),
            Ticket(user=cls.owner, match=cls.first, seat=cls.seats[2], full_name='مهمان ویژه', national_code='', price=99000000, status='vip_issued'),
            Ticket(user=cls.buyer, match=cls.first, seat=cls.seats[3], full_name='بلیط لغوشده', national_code='', price=88000000, status='cancelled'),
            Ticket(user=cls.buyer, match=cls.first, seat=cls.seats[4], full_name='بلیط پرداخت‌نشده', national_code='', price=77000000, status='pending'),
            Ticket(user=cls.buyer, match=cls.second, seat=cls.seats[0], full_name='نگار سانس دوم', national_code='', price=2300000, status='paid'),
            Ticket(user=cls.other, match=cls.foreign_session, seat=cls.seats[0], full_name='نام محرمانه دیگران', national_code='0123456789', price=66000000, status='paid'),
        ])

    def setUp(self):
        self.client.force_login(self.owner)

    def detail(self, program=None):
        return reverse('accounts:program_detail', args=[(program or self.proposal).pk])

    def session(self, session=None):
        return reverse('accounts:program_session', args=[self.proposal.pk, (session or self.first).pk])

    def test_owner_list_contains_drafts_and_published_and_only_paid_revenue(self):
        response = self.client.get(reverse('accounts:program_list'))
        self.assertContains(response, self.event.title)
        self.assertContains(response, self.draft.title)
        self.assertNotContains(response, self.foreign_event.title)
        self.assertEqual(response.context['stats']['sold'], 3)
        self.assertEqual(response.context['stats']['revenue'], 3500000)
        self.assertEqual(response.context['stats']['buyers'], 1)
        self.assertEqual(response.context['program_count'], 2)
        self.assertIn('no-store', response['Cache-Control'])

    def test_session_report_is_scoped_and_distinguishes_holder_and_purchaser(self):
        response = self.client.get(self.session())
        self.assertContains(response, 'نگار صاحب بلیط')
        self.assertContains(response, 'مریم خریدار')
        self.assertNotContains(response, 'نگار سانس دوم')
        self.assertNotContains(response, 'نام محرمانه دیگران')
        self.assertNotContains(response, '0123456789')
        self.assertEqual(response.context['stats']['sold'], 2)
        self.assertEqual(response.context['stats']['revenue'], 1200000)
        self.assertEqual(response.context['stats']['complimentary'], 1)
        self.assertEqual(response.context['stats']['used'], 1)
        self.assertEqual(response.context['page_obj'].paginator.count, 3)

    def test_cross_owner_and_cross_event_session_links_are_rejected(self):
        self.assertEqual(self.client.get(self.detail(self.foreign_proposal)).status_code, 404)
        self.assertEqual(self.client.get(self.session(self.foreign_session)).status_code, 404)
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(self.detail()).status_code, 404)
        self.assertEqual(self.client.get(self.session()).status_code, 404)
        self.client.logout()
        self.assertEqual(self.client.get(reverse('accounts:program_list')).status_code, 302)
        self.assertEqual(self.client.get(self.detail()).status_code, 302)

    def test_report_routes_are_read_only(self):
        self.assertEqual(self.client.post(reverse('accounts:program_list')).status_code, 405)
        self.assertEqual(self.client.post(self.detail()).status_code, 405)
        self.assertEqual(self.client.post(self.session()).status_code, 405)

    def test_filters_paginate_without_changing_statistics(self):
        response = self.client.get(self.session(), {'q': 'لغوشده', 'status': 'cancelled', 'page': 'invalid'})
        self.assertEqual(response.context['page_obj'].paginator.count, 1)
        self.assertEqual(response.context['stats']['revenue'], 1200000)
        self.assertContains(response, 'بلیط لغوشده')
        response = self.client.get(self.session(), {'status': 'not-a-status', 'page': '9999'})
        self.assertEqual(response.context['selected_status'], 'issued')
        self.assertEqual(response.context['page_obj'].number, 1)

    def test_seat_states_reservations_and_override_activity(self):
        MatchSeat.objects.filter(match=self.first, seat=self.seats[5]).update(reserved_until=timezone.now() + timedelta(minutes=4))
        MatchSeat.objects.filter(match=self.first, seat=self.seats[6]).update(is_enabled=False)
        response = self.client.get(self.session())
        states = {item.seat_id: item.report_state for item in response.context['seat_page']}
        self.assertEqual(states[self.seats[0].pk], 'sold')
        self.assertEqual(states[self.seats[2].pk], 'complimentary')
        self.assertEqual(states[self.seats[5].pk], 'reserved')
        self.assertEqual(states[self.seats[6].pk], 'disabled')
        self.assertEqual(states[self.seats[7].pk], 'available')
        MatchBlockActive.objects.create(match=self.first, block=self.block, is_active=False)
        response = self.client.get(self.session())
        states = {item.seat_id: item.report_state for item in response.context['seat_page']}
        self.assertEqual(states[self.seats[0].pk], 'sold')
        self.assertEqual(states[self.seats[7].pk], 'disabled')

    def test_json_link_cannot_grant_access_to_unowned_published_program(self):
        self.draft.data = {'published_event_id': self.foreign_event.pk}
        self.draft.save()
        response = self.client.get(self.detail(self.draft))
        self.assertIsNone(response.context['event'])
        self.assertNotContains(response, 'نام محرمانه دیگران')
        self.assertContains(response, 'هنوز منتشر نشده است')

    def test_quantity_program_has_capacity_panel_and_no_seat_report(self):
        self.proposal.data = {'admission_mode': 'quantity', 'ticket_capacity': 100, 'ticket_price': 0}
        self.proposal.save()
        response = self.client.get(self.session())
        self.assertIsNone(response.context['seat_page'])
        self.assertContains(response, 'ظرفیت بلیط تعدادی')
        self.assertContains(response, 'بدون شماره صندلی')
        self.assertNotContains(response, 'وضعیت هر صندلی')

    def test_draft_changes_do_not_change_published_seating_report(self):
        self.proposal.data = {'admission_mode': 'quantity', 'publication_snapshot': {'admission_mode': 'seated'}}
        self.proposal.save()
        response = self.client.get(self.session())
        self.assertFalse(response.context['is_quantity'])
        self.assertContains(response, 'وضعیت هر صندلی')

    def test_seat_map_shows_holder_and_purchaser_for_selected_session_only(self):
        response = self.client.get(self.session())
        details = response.context['seat_map']['details']
        item = MatchSeat.objects.get(match=self.first, seat=self.seats[0])
        self.assertEqual(details[str(item.pk)]['holder'], 'نگار صاحب بلیط')
        self.assertEqual(details[str(item.pk)]['buyer'], 'مریم خریدار')
        self.assertEqual(details[str(item.pk)]['state'], 'sold')
        self.assertEqual(details[str(item.pk)]['amount'], 1200000)
        self.assertNotIn('نگار سانس دوم', str(details))
        self.assertNotIn('نام محرمانه دیگران', str(details))
        self.assertContains(response, 'data-program-seat-map')
        self.assertContains(response, 'program-seat-map.js')

    def test_temporary_reservation_owner_and_missing_owner_are_not_guessed(self):
        item = MatchSeat.objects.get(match=self.first, seat=self.seats[5])
        item.reserved_until = timezone.now() + timedelta(minutes=5)
        item.save(update_fields=['reserved_until'])
        with patch('accounts.program_seating.SeatReservation.get_reserved_map', return_value={
            item.pk: {'match_id': self.first.pk, 'user_id': self.buyer.pk}}):
            response = self.client.get(self.session())
        detail = response.context['seat_map']['details'][str(item.pk)]
        self.assertEqual(detail['state'], 'reserved')
        self.assertEqual(detail['reserver'], 'مریم خریدار')
        self.assertEqual(detail['holder'], '')
        with patch('accounts.program_seating.SeatReservation.get_reserved_map', return_value={
            item.pk: {'match_id': self.foreign_session.pk, 'user_id': self.other.pk}}):
            response = self.client.get(self.session())
        detail = response.context['seat_map']['details'][str(item.pk)]
        self.assertEqual(detail['state'], 'reserved')
        self.assertEqual(detail['reserver'], '')
        item.reserved_until = timezone.now() - timedelta(minutes=1)
        item.save(update_fields=['reserved_until'])
        with patch('accounts.program_seating.SeatReservation.get_reserved_map', return_value={}):
            response = self.client.get(self.session())
        self.assertEqual(response.context['seat_map']['details'][str(item.pk)]['state'], 'available')

    def test_map_preserves_published_aisles_alignment_and_bottom_stage(self):
        self.proposal.data = {'seat_layout': {}, 'publication_snapshot': {'admission_mode': 'seated',
            'seat_layout': {'stage': 'bottom', 'direction': 'ltr', 'sections': [
                {'name': self.block.name, 'rows': [{'number': 1, 'alignment': 'center', 'offset': 0,
                    'seats': [1, 2, None, 3, 4, 5, 6, 7, 8]}]}]}}}
        self.proposal.save()
        response = self.client.get(self.session())
        row = response.context['seat_map']['rows'][0]
        self.assertIsNone(row['cells'][2])
        self.assertEqual(row['alignment'], 'center')
        self.assertEqual(response.context['seat_map']['stage'], 'bottom')
        self.assertEqual(response.context['seat_map']['direction'], 'ltr')
        self.assertContains(response, 'program-map-gap')

    def test_map_block_is_scoped_and_large_maps_are_bounded(self):
        foreign_venue = Stadium.objects.create(name='سالن دیگران', capacity=1)
        foreign_block = Block.objects.create(stadium=foreign_venue, name='بخش محرمانه')
        response = self.client.get(self.session(), {'map_block': foreign_block.pk})
        self.assertEqual(response.context['seat_map']['block'], self.block)
        self.assertNotContains(response, foreign_block.name)
        row = Row.objects.create(block=self.block, number=2)
        additional = Seat.objects.bulk_create([Seat(row=row, number=i) for i in range(1, 311)])
        MatchSeat.objects.bulk_create([MatchSeat(match=self.first, seat=seat) for seat in additional])
        response = self.client.get(self.session())
        self.assertEqual(len(response.context['seat_map']['details']), 300)
        self.assertTrue(response.context['seat_map']['page'].has_next())
        response = self.client.get(self.session(), {'map_page': 2, 'map_block': self.block.pk})
        self.assertEqual(len(response.context['seat_map']['details']), 18)

    def test_map_json_and_tooltips_escape_buyer_supplied_markup(self):
        Ticket.objects.filter(match=self.first, seat=self.seats[0], status='paid').update(full_name='</script><img src=x onerror=alert(1)>')
        response = self.client.get(self.session())
        self.assertNotContains(response, '</script><img src=x')
        self.assertContains(response, '\\u003C/script\\u003E')

    def test_backfill_checks_session_creator_before_linking_legacy_json(self):
        candidate = EventSubmission.objects.create(owner=self.owner, title='پیوند جعلی', category='event',
            data={'published_event_id': self.foreign_event.pk})
        migration = import_module('accounts.migrations.0021_eventsubmission_published_event')
        migration.link_verified_preview_publications(apps, SimpleNamespace(connection=connection))
        candidate.refresh_from_db()
        self.assertIsNone(candidate.published_event_id)
        own_event = Event.objects.create(title='انتشار قدیمی من', category='theater')
        Match.objects.create(event=own_event, stadium=self.venue, date_time=timezone.now(), created_by=self.owner)
        valid = EventSubmission.objects.create(owner=self.owner, title=own_event.title, category='theater',
            data={'published_event_id': own_event.pk})
        migration.link_verified_preview_publications(apps, SimpleNamespace(connection=connection))
        valid.refresh_from_db()
        self.assertEqual(valid.published_event_id, own_event.pk)
