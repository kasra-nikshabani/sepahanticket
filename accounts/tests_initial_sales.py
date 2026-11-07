import json
from datetime import date, timedelta
from types import SimpleNamespace
from tickets.cultural_checkout import validate_purchase
from unittest.mock import patch
import jdatetime
from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings
from django.urls import reverse
from accounts import tests_management as management_fixtures
from accounts.models import EventSubmission
from accounts.submission_forms import DetailsForm
from accounts.submission_schedule import session_plan
from matches.models import Event, Match, Seat, MatchBlockPrice, get_seat_price_map


@override_settings(CULTURAL_PLATFORM=True)
class InitialSalesTests(TestCase):
    image = management_fixtures.ManagementPublicationTests.image
    url = management_fixtures.ManagementPublicationTests.url
    create_draft = management_fixtures.ManagementPublicationTests.create_draft
    details = management_fixtures.ManagementPublicationTests.details
    advance = management_fixtures.ManagementPublicationTests.advance
    setUp = management_fixtures.ManagementPublicationTests.setUp

    def define_plan(self, **extra):
        self.submission.data.update({'start_date': jdatetime.date(1405, 9, 10).togregorian().isoformat(),
            'end_date': jdatetime.date(1405, 9, 20).togregorian().isoformat(), 'time': '19:30:00',
            'second_time': None, 'third_time': None, **extra})
        plan = session_plan(self.submission.data)
        self.submission.data['opening_sessions'] = [item['key'] for item in plan[:3]]
        self.submission.save()
        return plan

    def publish(self, **extra):
        data = {'action': 'publish', 'license_checked': 'on', 'approve_opening_sales': 'on', 'opening_base_price': '۳۰۰٬۰۰۰'}
        data.update(extra)
        return self.client.post(self.review_url, data)

    def test_dates_ten_through_twenty_create_eleven_sessions_only_first_three_open(self):
        plan = self.define_plan()
        self.assertFalse(Match.objects.exists())
        response = self.publish()
        self.assertEqual(response.status_code, 302)
        self.submission.refresh_from_db()
        sessions = list(self.submission.published_event.sessions.order_by('date_time'))
        self.assertEqual(len(sessions), 11)
        self.assertEqual([session.date_time for session in sessions], [item['date_time'] for item in plan])
        self.assertEqual([session.ticket_sales_enabled for session in sessions], [True] * 3 + [False] * 8)
        self.assertEqual([session.sales_available for session in sessions], [True] * 3 + [False] * 8)
        with self.assertRaisesMessage(ValueError, 'فروش این سانس در دسترس نیست'):
            validate_purchase(SimpleNamespace(), sessions[3])
        self.assertEqual(self.submission.data['initial_schedule_session_ids'], [session.pk for session in sessions])
        self.assertTrue(self.submission.data['initial_sales_approved'])
        self.assertTrue(all(session.match_seats.count() == 3 for session in sessions))
        self.assertEqual(MatchBlockPrice.objects.count(), 11)
        self.assertTrue(all(price == 3000000 for price in get_seat_price_map(sessions[0], Seat.objects.all()).values()))
        self.client.post(self.review_url, {'action': 'publish', 'license_checked': 'on'})
        self.assertEqual(Match.objects.count(), 11)
        self.client.force_login(self.user)
        self.assertContains(self.client.get(reverse('accounts:program_detail', args=[self.submission.pk])), 'فروش غیرفعال')
        self.assertEqual(self.client.post(self.url(2), {'opening_sessions': json.dumps([item['key'] for item in plan])}).status_code, 403)

    def test_two_times_in_one_day_can_open_independently(self):
        plan = self.define_plan(second_time='21:30:00')
        self.submission.data['opening_sessions'] = [plan[0]['key'], plan[3]['key']]
        self.submission.save()
        self.publish(opening_base_price='۰')
        opened = Match.objects.filter(ticket_sales_enabled=True).order_by('date_time')
        self.assertEqual(list(opened.values_list('date_time', flat=True)), [plan[0]['date_time'], plan[3]['date_time']])
        self.assertEqual(Match.objects.count(), 22)
        self.assertTrue(all(price == 0 for price in get_seat_price_map(opened.first(), Seat.objects.all()).values()))

    def test_unapproved_or_empty_selection_keeps_every_session_closed(self):
        self.define_plan()
        self.publish(approve_opening_sales='', opening_base_price='')
        self.assertEqual(Match.objects.count(), 11)
        self.assertFalse(Match.objects.filter(ticket_sales_enabled=True).exists())
        self.assertFalse(MatchBlockPrice.objects.exists())

    def test_empty_selection_is_valid_and_builds_closed_schedule(self):
        self.define_plan()
        self.submission.data['opening_sessions'] = []
        self.submission.save()
        self.publish(approve_opening_sales='', opening_base_price='')
        self.assertEqual(Match.objects.count(), 11)
        self.assertFalse(Match.objects.filter(ticket_sales_enabled=True).exists())

    def test_price_is_required_and_invalid_choices_cannot_publish_or_create_inventory(self):
        self.define_plan()
        response = self.publish(opening_base_price='')
        self.assertContains(response, 'قیمت پایه بلیط را وارد کنید')
        self.assertFalse(Event.objects.exists())
        self.assertFalse(Match.objects.exists())
        self.submission.data['opening_sessions'] = ['2026-01-01T19:30']
        self.submission.save()
        self.publish()
        self.assertFalse(Event.objects.exists())
        self.assertFalse(Match.objects.exists())

    def test_past_selected_session_blocks_sales_but_can_publish_closed(self):
        self.define_plan()
        yesterday = date.today() - timedelta(days=1)
        self.submission.data.update(start_date=yesterday.isoformat(), end_date=yesterday.isoformat())
        self.submission.data['opening_sessions'] = [session_plan(self.submission.data)[0]['key']]
        self.submission.save()
        response = self.publish()
        self.assertContains(response, 'فروش سانس گذشته را نمی‌توان باز کرد')
        self.assertFalse(Event.objects.exists())
        self.publish(approve_opening_sales='', opening_base_price='')
        self.assertEqual(Match.objects.count(), 1)
        self.assertFalse(Match.objects.get().ticket_sales_enabled)

    def test_unprepared_quantity_sales_are_never_opened_as_seated_sales(self):
        self.define_plan(admission_mode='quantity', ticket_capacity=50, ticket_price=100000)
        response = self.publish()
        self.assertContains(response, 'آماده‌سازی فروش تعدادی یا آنلاین')
        self.assertFalse(Event.objects.exists())
        self.publish(approve_opening_sales='', opening_base_price='')
        self.assertEqual(Match.objects.count(), 11)
        self.assertFalse(Match.objects.filter(ticket_sales_enabled=True).exists())

    def test_failure_during_session_creation_rolls_back_publication_and_venue(self):
        self.define_plan()
        with patch('accounts.management_views.create_initial_sessions', side_effect=ValidationError('ساخت سانس انجام نشد')):
            self.publish()
        self.submission.refresh_from_db()
        self.assertIsNone(self.submission.published_event_id)
        self.assertIsNone(self.submission.venue_id)
        self.assertEqual(self.submission.status, 'submitted')
        self.assertFalse(Event.objects.exists())
        self.assertFalse(Match.objects.exists())

    def test_picker_api_is_readonly_authenticated_and_bounds_schedule(self):
        self.client.force_login(self.user)
        url = reverse('accounts:schedule_options')
        params = {'start_date': '۱۴۰۵/۰۹/۱۰', 'end_date': '۱۴۰۵/۰۹/۲۰', 'time': '19:30', 'second_time': '21:00'}
        response = self.client.get(url, params)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()['sessions']), 22)
        self.assertIn('1405/09/10', response.json()['sessions'][0]['label'])
        self.assertEqual(self.client.post(url, params).status_code, 405)
        for extra in [{'end_date': '۱۴۰۵/۰۸/۰۹'}, {'end_date': '۱۴۰۶/۰۸/۲۰'}, {'time': '99:00'}, {'time': '19:30:01'}]:
            self.assertEqual(self.client.get(url, {**params, **extra}).status_code, 400)
        self.assertFalse(Match.objects.exists())
        self.client.logout()
        self.assertEqual(self.client.get(url, params).status_code, 302)

    def test_draft_persists_selection_and_final_submission_revalidates_range(self):
        plan = self.define_plan()
        self.submission.status = 'draft'
        self.submission.save()
        self.client.force_login(self.user)
        response = self.client.post(self.url(2), self.details(start_date='۱۴۰۵/۰۹/۱۰', end_date='۱۴۰۵/۰۹/۲۰',
            opening_sessions=json.dumps([item['key'] for item in plan[:3]]), action='save'))
        self.assertRedirects(response, self.url(2))
        self.submission.refresh_from_db()
        self.assertEqual(len(self.submission.data['opening_sessions']), 3)
        self.assertContains(self.client.get(self.url(2)), 'data-opening-picker')
        self.submission.data['start_date'] = self.submission.data['end_date']
        self.submission.save()
        self.assertRedirects(self.client.post(self.url(5), {'organizer_role': 'مدیر', 'confirm': 'on', 'action': 'submit'}), self.url(2))
        self.submission.refresh_from_db()
        self.assertEqual(self.submission.status, 'draft')

    def test_selection_rejects_outside_hours_and_non_list_json(self):
        for value in [{'fake': True}, False, ['2026-11-01T23:00'], ['2026-11-30T19:30']]:
            form = DetailsForm(self.details(start_date='۱۴۰۵/۰۹/۱۰', end_date='۱۴۰۵/۰۹/۲۰',
                opening_sessions=json.dumps(value)), partial=True)
            self.assertFalse(form.is_valid())
            self.assertIn('opening_sessions', form.errors)
