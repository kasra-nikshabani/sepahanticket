from django.test import TestCase
from django.urls import reverse

from tickets.models import Ticket
from . import tests_programs


class ProgramCheckinTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        tests_programs.OrganizerProgramTests.setUpTestData.__func__(cls)

    def setUp(self):
        self.client.force_login(self.owner)
        self.ticket = Ticket.objects.get(match=self.first, seat=self.seats[1], status='paid')
        self.other_session_ticket = Ticket.objects.get(match=self.second, status='paid')
        self.cancelled_ticket = Ticket.objects.get(match=self.first, status='cancelled')
        Ticket.objects.filter(pk=self.ticket.pk).update(ticket_number='123456')
        Ticket.objects.filter(pk=self.other_session_ticket.pk).update(ticket_number='654321')
        Ticket.objects.filter(pk=self.cancelled_ticket.pk).update(ticket_number='222222')
        self.ticket.refresh_from_db()
        self.other_session_ticket.refresh_from_db()
        self.cancelled_ticket.refresh_from_db()
        self.page_url = reverse('accounts:program_checkin', args=[self.proposal.pk, self.first.pk])
        self.action_url = reverse('accounts:program_checkin_action', args=[self.proposal.pk, self.first.pk])

    def post_code(self, code, action='verify'):
        return self.client.post(self.action_url, {'ticket_code': code, 'action': action})

    def test_owner_can_open_session_scanner_with_manual_entry_and_camera(self):
        response = self.client.get(self.page_url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'اسکن QR بلیط')
        self.assertContains(response, 'ورود شمارهٔ بلیط')
        self.assertContains(response, 'events/checkin.js')
        detail = self.client.get(reverse('accounts:program_session', args=[self.proposal.pk, self.first.pk]))
        self.assertContains(detail, reverse('accounts:program_checkin', args=[self.proposal.pk, self.first.pk]))

    def test_verify_does_not_consume_ticket_and_persian_digits_are_accepted(self):
        response = self.post_code('۱۲۳۴۵۶')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['status'], 'valid')
        self.assertEqual(response.json()['holder'], self.ticket.full_name)
        self.ticket.refresh_from_db()
        self.assertFalse(self.ticket.is_used)
        self.assertIsNone(self.ticket.used_at)

    def test_full_qr_payload_is_verified_and_wrong_qr_session_is_rejected(self):
        response = self.post_code(self.ticket.gate_qr_payload)
        self.assertEqual(response.json()['status'], 'valid')
        malformed = f'Ticket:{self.ticket.ticket_number}|Match:{self.second.pk}|Seat:{self.ticket.seat_id}|User:{self.owner.username}'
        response = self.post_code(malformed)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()['status'], 'invalid')

    def test_confirmation_marks_entry_once_and_reports_duplicate_scan(self):
        self.assertEqual(self.post_code('123456', 'verify').json()['status'], 'valid')
        first = self.post_code('123456', 'check_in')
        self.assertEqual(first.json()['status'], 'checked_in')
        self.ticket.refresh_from_db()
        self.assertTrue(self.ticket.is_used)
        self.assertIsNotNone(self.ticket.used_at)
        duplicate = self.post_code('123456', 'check_in')
        self.assertEqual(duplicate.status_code, 409)
        self.assertEqual(duplicate.json()['status'], 'used')

    def test_other_session_cancelled_and_unowned_program_tickets_are_rejected(self):
        self.assertEqual(self.post_code('654321').json()['status'], 'invalid')
        self.assertEqual(self.post_code('222222').json()['status'], 'invalid')
        self.assertFalse(self.other_session_ticket.is_used)
        self.assertFalse(self.cancelled_ticket.is_used)
        self.assertEqual(self.client.get(reverse('accounts:program_checkin', args=[self.foreign_proposal.pk, self.foreign_session.pk])).status_code, 404)
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(self.page_url).status_code, 404)
        self.assertEqual(self.post_code('123456').status_code, 404)
