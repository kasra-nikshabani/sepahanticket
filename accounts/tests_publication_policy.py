from copy import deepcopy
from django.test import TestCase
from django.urls import reverse
from accounts import tests_programs as fixtures
from accounts.models import SupportTicket
from accounts.publication_policy import change_request_url
from matches.models import MatchBlockPrice, MatchRowPrice, MatchSeatPrice


class PublishedProgramPolicyTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        fixtures.OrganizerProgramTests.setUpTestData.__func__(cls)

    def setUp(self):
        self.client.force_login(self.owner)

    def test_all_wizard_steps_reject_changes_and_redirect_get_to_ticket(self):
        original = deepcopy(self.proposal.data)
        for step in range(1, 6):
            url = reverse('accounts:event_submission_step', args=[self.proposal.pk, step])
            self.assertRedirects(self.client.get(url), change_request_url(self.proposal))
            for action in ['save', 'next', 'submit', 'reopen']:
                response = self.client.post(url, {'action': action, 'title': 'تغییر غیرمجاز',
                    'category': 'concert', 'confirm': 'on', 'credits': 'عوامل تازه', 'prices': '۰', 'seat_layout': '{}'})
                self.assertEqual(response.status_code, 403)
                self.assertContains(response, 'ثبت تیکت تغییرات', status_code=403)
        self.proposal.refresh_from_db()
        self.event.refresh_from_db()
        self.assertEqual(self.proposal.data, original)
        self.assertEqual(self.proposal.title, self.event.title)
        self.assertEqual(self.proposal.status, 'draft')

    def test_previously_submitted_or_returned_and_inactive_publication_stays_locked(self):
        self.proposal.status = 'submitted'
        self.proposal.data['review_feedback'] = 'تکمیل اطلاعات'
        self.proposal.save()
        self.event.is_active = False
        self.event.save()
        url = reverse('accounts:event_submission_step', args=[self.proposal.pk, 1])
        self.assertEqual(self.client.post(url, {'action': 'reopen'}).status_code, 403)
        self.proposal.refresh_from_db()
        self.assertEqual(self.proposal.status, 'submitted')
        self.assertEqual(self.client.get(change_request_url(self.proposal)).status_code, 200)

    def test_owner_cannot_change_prices_through_either_legacy_route(self):
        urls = [reverse('accounts:program_pricing', args=[self.proposal.pk]),
            reverse('accounts:program_session_pricing', args=[self.proposal.pk, self.first.pk])]
        for url in urls:
            self.assertRedirects(self.client.get(url), change_request_url(self.proposal))
            for action in ['apply', 'reset']:
                self.assertEqual(self.client.post(url, {'action': action, 'scope': 'future', 'target': 'row',
                    'row': self.row.pk, 'price': '۰'}).status_code, 403)
        self.assertFalse(MatchRowPrice.objects.exists())
        self.assertFalse(MatchSeatPrice.objects.exists())
        self.assertFalse(MatchBlockPrice.objects.exists())
        foreign_session_url = reverse('accounts:program_session_pricing', args=[self.proposal.pk, self.foreign_session.pk])
        self.assertEqual(self.client.get(foreign_session_url).status_code, 404)

    def test_change_ticket_has_server_owned_event_submission_and_private_scope(self):
        url = change_request_url(self.proposal)
        response = self.client.get(url)
        self.assertContains(response, 'درخواست تغییر برنامه')
        self.assertTrue(response.context['form'].fields['event'].disabled)
        self.assertTrue(response.context['form'].fields['category'].disabled)
        response = self.client.post(url, {'category': 'general', 'event': self.foreign_event.pk,
            'subject': 'تغییر ساعت', 'body': 'سانس اول را به ساعت هشت تغییر دهید.'})
        ticket = SupportTicket.objects.get()
        self.assertRedirects(response, reverse('accounts:support_detail', args=[ticket.pk]))
        self.assertEqual(ticket.category, 'program')
        self.assertEqual(ticket.event, self.event)
        self.assertEqual(ticket.submission, self.proposal)
        self.assertEqual(ticket.requester, self.owner)
        self.assertEqual(ticket.status, 'waiting')
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(url).status_code, 404)
        self.assertEqual(self.client.post(url, {'subject': 'تغییر', 'body': 'نام جدید'}).status_code, 404)
        self.assertEqual(self.client.get(reverse('accounts:support_create'), {'change': '1', 'event': 'bad'}).status_code, 404)
        self.assertEqual(SupportTicket.objects.count(), 1)

    def test_owner_report_remains_readonly_and_displays_admin_updated_title(self):
        self.event.title = 'عنوان جدید توسط ادمین'
        self.event.save()
        response = self.client.get(reverse('accounts:program_detail', args=[self.proposal.pk]))
        self.assertContains(response, self.event.title)
        self.assertContains(response, 'ثبت تیکت تغییرات')
        self.assertNotContains(response, 'ویرایش اطلاعات درخواست')
        self.assertNotContains(response, reverse('accounts:program_pricing', args=[self.proposal.pk]))
        self.assertContains(self.client.get(reverse('accounts:program_list')), self.event.title)
        self.client.force_login(self.other)
        self.assertEqual(self.client.post(reverse('accounts:event_submission_step', args=[self.proposal.pk, 1]), {'action': 'save'}).status_code, 404)

    def test_unpublished_draft_can_still_be_edited(self):
        url = reverse('accounts:event_submission_step', args=[self.draft.pk, 1])
        self.assertEqual(self.client.get(url).status_code, 200)
        response = self.client.post(url, {'title': 'پیش‌نویس اصلاح شده', 'category': 'event', 'action': 'save'})
        self.assertRedirects(response, url)
        self.draft.refresh_from_db()
        self.assertEqual(self.draft.title, 'پیش‌نویس اصلاح شده')
        self.assertIsNone(self.draft.published_event_id)
