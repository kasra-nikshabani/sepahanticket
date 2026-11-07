import csv
import io
from datetime import datetime, timedelta
from unittest.mock import patch
from django.contrib.admin.models import LogEntry
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from accounts.models import User
from accounts import tests_programs as fixtures
from accounts.management_views import audit
from accounts.management_reports import safe_cell
from matches.models import MatchSeat, MatchBlockActive
from tickets.models import Ticket


@override_settings(CULTURAL_PLATFORM=True)
class ManagementReportTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        fixtures.OrganizerProgramTests.setUpTestData.__func__(cls)
        cls.admin = User.objects.create_user(username='report-manager', is_staff=True)

    def setUp(self):
        cache.clear()
        self.client.force_login(self.admin)

    def csv_rows(self, url):
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertIn('no-store', response['Cache-Control'])
        self.assertEqual(response['Content-Disposition'], 'attachment; filename="didavar-sales.csv"')
        return list(csv.reader(io.StringIO(b''.join(response.streaming_content).decode('utf-8-sig'))))

    def test_event_report_has_only_its_program_and_actual_per_session_sales(self):
        response = self.client.get(reverse('management:event_report', args=[self.event.pk]))
        self.assertEqual(response.context['stats']['revenue'], 3500000)
        self.assertEqual(response.context['session_count'], 2)
        sessions = list(response.context['page_obj'])
        self.assertEqual(sessions[0].report_sales['revenue'], 1200000)
        self.assertEqual(sessions[1].report_sales['revenue'], 2300000)
        self.assertEqual(sessions[0].report_capacity, 8)
        self.assertEqual(sessions[0].report_fill, 25)
        self.assertNotContains(response, 'برنامه خصوصی دیگران')
        self.assertEqual(self.client.post(reverse('management:event_report', args=[self.event.pk])).status_code, 405)

    def test_csv_defaults_to_paid_and_matches_filtered_search_and_currency(self):
        Ticket.objects.filter(match=self.first, seat=self.seats[0]).update(full_name='=HYPERLINK("evil")')
        rows = self.csv_rows(reverse('management:session_export', args=[self.first.pk]) + '?status=paid')
        self.assertEqual(len(rows), 3)
        amounts = {row[1]: row[10] for row in rows[1:]}
        self.assertEqual(amounts["'=HYPERLINK(\"evil\")"], '120000')
        self.assertEqual(amounts['صاحب بلیط رایگان'], '0')
        response = self.client.get(reverse('management:sales'), {'event': self.event.pk, 'q': 'نگار', 'status': 'paid'})
        self.assertEqual(response.context['stats']['revenue'], 2300000)
        self.assertEqual(response.context['page_obj'].paginator.count, 1)
        exported = self.csv_rows(reverse('management:sales_export') + f'?event={self.event.pk}&q=نگار&status=paid')
        self.assertEqual(len(exported), 2)
        self.assertEqual(exported[1][1], 'نگار سانس دوم')
        for value in ('=SUM(A1)', '+cmd', '-1', '@calc', '  =A1', '\tformula', '\nformula'):
            self.assertTrue(safe_cell(value).startswith("'"))

    def test_purchase_dates_include_entire_local_end_day_and_invalid_ranges_do_not_export(self):
        start = timezone.make_aware(datetime(2026, 11, 11))
        paid = Ticket.objects.filter(match__event=self.event, status='paid').order_by('pk')
        ids = list(paid.values_list('pk', flat=True))
        Ticket.objects.filter(pk=ids[0]).update(purchase_date=start)
        Ticket.objects.filter(pk=ids[1]).update(purchase_date=start + timedelta(hours=23, minutes=59))
        Ticket.objects.filter(pk=ids[2]).update(purchase_date=start + timedelta(days=1))
        args = f'?event={self.event.pk}&start=۱۴۰۵/۰۸/۲۰&end=۱۴۰۵/۰۸/۲۰'
        response = self.client.get(reverse('management:sales') + args)
        self.assertEqual(response.context['page_obj'].paginator.count, 2)
        self.assertEqual(response.context['stats']['revenue'], 1200000)
        self.assertEqual(len(self.csv_rows(reverse('management:sales_export') + args)), 3)
        for query in ('?start=invalid', '?start=۱۴۰۵/۰۸/۲۱&end=۱۴۰۵/۰۸/۲۰', '?status=invalid'):
            response = self.client.get(reverse('management:sales') + query)
            self.assertEqual(response.context['page_obj'].paginator.count, 0)
            self.assertTrue(response.context['filter_form'].errors)
            self.assertEqual(self.client.get(reverse('management:sales_export') + query).status_code, 400)

    def test_admin_map_shows_correct_holder_buyer_and_reserved_seat_without_cross_session_names(self):
        item = MatchSeat.objects.get(match=self.first, seat=self.seats[6])
        data = {item.pk: {'user_id': self.buyer.pk, 'match_id': self.first.pk}}
        with patch('accounts.program_seating.SeatReservation.get_reserved_map', return_value=data):
            response = self.client.get(reverse('management:session_sales', args=[self.first.pk]))
        details = response.context['seat_map']['details']
        sold_id = MatchSeat.objects.get(match=self.first, seat=self.seats[0]).pk
        self.assertEqual(details[str(sold_id)]['holder'], 'نگار صاحب بلیط')
        self.assertEqual(details[str(sold_id)]['buyer'], 'مریم خریدار')
        self.assertEqual(details[str(item.pk)]['state'], 'reserved')
        self.assertEqual(details[str(item.pk)]['reserver'], 'مریم خریدار')
        self.assertNotContains(response, 'نام محرمانه دیگران')
        self.assertNotContains(response, 'نگار سانس دوم')
        self.assertNotContains(response, '0123456789')

    def test_disabled_block_overrides_prevent_starting_sales_and_correct_capacity(self):
        MatchBlockActive.objects.create(match=self.first, block=self.block, is_active=False)
        self.first.ticket_sales_enabled = False
        self.first.save()
        response = self.client.get(reverse('management:event_report', args=[self.event.pk]))
        self.assertEqual(list(response.context['page_obj'])[0].report_capacity, 0)
        self.client.post(reverse('management:session_sales', args=[self.first.pk]), {'action': 'open_sales'})
        self.first.refresh_from_db()
        self.assertFalse(self.first.ticket_sales_enabled)

    def test_request_history_states_and_audit_search(self):
        self.draft.data = {'review_feedback': 'تکمیل اطلاعات'}
        self.draft.save()
        returned = self.client.get(reverse('management:requests'), {'state': 'returned'})
        self.assertEqual(list(returned.context['page_obj']), [self.draft])
        published = self.client.get(reverse('management:requests'), {'state': 'published'})
        self.assertEqual(published.context['page_obj'].paginator.count, 2)
        self.assertEqual(self.client.get(reverse('management:requests')).context['page_obj'].paginator.count, 0)
        from types import SimpleNamespace
        audit(SimpleNamespace(user=self.admin), self.event, 'قیمت‌ها بررسی شدند')
        response = self.client.get(reverse('management:activity'), {'q': 'قیمت‌ها'})
        self.assertEqual(response.context['page_obj'].paginator.count, 1)
        self.assertContains(response, 'report-manager')
        self.assertContains(response, 'قیمت‌ها بررسی شدند')
        self.assertEqual(LogEntry.objects.count(), 1)

    def test_reports_exports_and_audit_are_staff_only_and_read_only(self):
        urls = [reverse('management:activity'), reverse('management:event_report', args=[self.event.pk]),
                reverse('management:sales_export'), reverse('management:session_export', args=[self.first.pk])]
        before = (Ticket.objects.count(), LogEntry.objects.count())
        for url in urls:
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200)
            if response.streaming:
                b''.join(response.streaming_content)
            self.assertEqual(self.client.post(url).status_code, 405)
        self.assertEqual(before, (Ticket.objects.count(), LogEntry.objects.count()))
        self.client.force_login(self.owner)
        for url in urls:
            self.assertEqual(self.client.get(url).status_code, 302)
