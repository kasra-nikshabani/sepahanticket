from django.contrib.admin.models import LogEntry
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from .models import User, EventSubmission, SupportTicket, SupportMessage
from matches.models import Event


@override_settings(CULTURAL_PLATFORM=True)
class SupportTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='support-user', first_name='کسری', last_name='نیک شبانی')
        self.other = User.objects.create_user(username='other-support-user')
        self.admin = User.objects.create_user(username='support-admin', is_staff=True)
        self.event = Event.objects.create(title='نمایش ریشه', category='theater')
        self.inactive = Event.objects.create(title='برنامه خصوصی', category='concert', is_active=False)
        self.client.force_login(self.user)

    def create(self, **extra):
        data = {'category': 'general', 'subject': 'پیگیری حساب', 'body': 'پیام اولیه'}
        data.update(extra)
        return self.client.post(reverse('accounts:support_create'), data)

    def detail(self, ticket, staff=False):
        return reverse('management:support_detail' if staff else 'accounts:support_detail', args=[ticket.pk])

    def test_create_general_and_program_tickets_and_initial_messages(self):
        response = self.create()
        ticket = SupportTicket.objects.get()
        self.assertRedirects(response, self.detail(ticket))
        self.assertEqual(ticket.requester, self.user)
        self.assertEqual(ticket.status, 'waiting')
        self.assertIsNone(ticket.event)
        self.assertEqual(ticket.messages.get().body, 'پیام اولیه')
        self.assertFalse(ticket.messages.get().is_staff_reply)
        self.create(category='program', event=self.event.pk, subject='گزارش فروش')
        program_ticket = SupportTicket.objects.get(category='program')
        self.assertEqual(program_ticket.event, self.event)
        self.assertContains(self.client.get(self.detail(program_ticket)), self.event.title)

    def test_category_and_event_validation_and_nonempty_messages(self):
        cases = [dict(category='program'), dict(category='general', event=self.event.pk),
            dict(category='bad'), dict(category='program', event=self.inactive.pk),
            dict(body='  '), dict(subject='  '), dict(body='a' * 8001)]
        for extra in cases:
            with self.subTest(extra=str(extra)[:100]):
                self.assertEqual(self.create(**extra).status_code, 200)
                self.assertEqual(SupportTicket.objects.count(), 0)
                self.assertEqual(SupportMessage.objects.count(), 0)
        sports = Event.objects.create(title='ورزش', category='sport')
        self.create(category='program', event=sports.pk)
        self.assertEqual(SupportTicket.objects.count(), 0)

    def test_organizer_can_link_own_inactive_program_only(self):
        own = Event.objects.create(title='برنامه سازنده', category='theater', is_active=False)
        EventSubmission.objects.create(owner=self.user, title=own.title, category='theater', published_event=own)
        self.assertEqual(self.create(category='program', event=own.pk).status_code, 302)
        self.assertEqual(SupportTicket.objects.get().event, own)
        self.client.force_login(self.other)
        self.create(category='program', event=own.pk)
        self.assertEqual(SupportTicket.objects.count(), 1)

    def test_owner_privacy_for_list_detail_reply_and_status(self):
        self.create(subject='خصوصی', body='متن محرمانه')
        ticket = SupportTicket.objects.get()
        self.client.force_login(self.other)
        self.assertNotContains(self.client.get(reverse('accounts:support_list')), 'خصوصی')
        self.assertEqual(self.client.get(self.detail(ticket)).status_code, 404)
        for action in ['reply', 'close', 'reopen']:
            self.assertEqual(self.client.post(self.detail(ticket), {'action': action, 'body': 'نفوذ'}).status_code, 404)
        ticket.refresh_from_db()
        self.assertEqual(ticket.status, 'waiting')
        self.assertEqual(ticket.messages.count(), 1)

    def test_staff_only_admin_and_anonymous_redirects(self):
        self.create()
        ticket = SupportTicket.objects.get()
        self.assertEqual(self.client.get(reverse('management:support')).status_code, 302)
        self.assertEqual(self.client.post(self.detail(ticket, True), {'body': 'پاسخ'}).status_code, 302)
        self.client.logout()
        for name in ['accounts:support_list', 'accounts:support_create', 'management:support']:
            self.assertEqual(self.client.get(reverse(name)).status_code, 302)
        self.assertEqual(self.client.get(self.detail(ticket)).status_code, 302)
        self.assertEqual(ticket.messages.count(), 1)

    def test_reply_states_history_close_and_reopen(self):
        self.create()
        ticket = SupportTicket.objects.get()
        self.client.force_login(self.admin)
        url = self.detail(ticket, True)
        self.assertRedirects(self.client.post(url, {'body': 'پاسخ پشتیبانی'}), url)
        ticket.refresh_from_db()
        self.assertEqual(ticket.status, 'answered')
        self.assertTrue(ticket.messages.last().is_staff_reply)
        self.assertEqual(LogEntry.objects.count(), 1)
        self.client.force_login(self.user)
        self.client.post(self.detail(ticket), {'body': 'اطلاعات تکمیلی'})
        ticket.refresh_from_db()
        self.assertEqual(ticket.status, 'waiting')
        self.client.post(self.detail(ticket), {'action': 'close'})
        ticket.refresh_from_db()
        self.assertEqual(ticket.status, 'closed')
        response = self.client.post(self.detail(ticket), {'body': 'بدون باز کردن'})
        self.assertContains(response, 'ابتدا تیکت را دوباره باز کنید')
        self.assertEqual(ticket.messages.count(), 3)
        self.client.post(self.detail(ticket), {'action': 'reopen'})
        ticket.refresh_from_db()
        self.assertEqual(ticket.status, 'waiting')
        self.assertEqual(self.client.post(self.detail(ticket), {'action': 'delete'}).status_code, 400)
        self.assertEqual(self.client.post(self.detail(ticket), {'body': '  '}).status_code, 200)
        self.assertEqual(ticket.messages.count(), 3)

    def test_filters_counts_pagination_and_staff_search(self):
        self.create(subject='حساب')
        self.create(category='program', event=self.event.pk, subject='ریشه')
        other_ticket = SupportTicket.objects.create(requester=self.other, category='general', subject='دیگری', status='closed')
        response = self.client.get(reverse('accounts:support_list'), {'category': 'program'})
        self.assertEqual([ticket.subject for ticket in response.context['page_obj']], ['ریشه'])
        self.assertEqual(response.context['program_count'], 1)
        self.assertEqual(response.context['general_count'], 1)
        self.client.force_login(self.admin)
        response = self.client.get(reverse('management:support'), {'category': 'general', 'status': 'closed'})
        self.assertEqual(list(response.context['page_obj']), [other_ticket])
        response = self.client.get(reverse('management:support'), {'q': 'کسری'})
        self.assertEqual(response.context['page_obj'].paginator.count, 2)
        self.assertEqual(response.context['pending_support'], 2)
        for i in range(25):
            SupportTicket.objects.create(requester=self.user, category='general', subject=f'پیام {i}')
        response = self.client.get(reverse('management:support'), {'page': 2, 'category': 'general'})
        self.assertEqual(len(response.context['page_obj']), 7)
        self.assertContains(response, 'category=general')

    def test_csrf_and_readonly_get_and_escaped_message(self):
        self.create(body='<script>alert(1)</script>')
        ticket = SupportTicket.objects.get()
        updated = ticket.updated_at
        response = self.client.get(self.detail(ticket), {'action': 'close'})
        self.assertContains(response, '&lt;script&gt;')
        self.assertNotContains(response, '<script>alert')
        ticket.refresh_from_db()
        self.assertEqual(ticket.updated_at, updated)
        self.assertEqual(ticket.status, 'waiting')
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.user)
        self.assertEqual(csrf_client.post(reverse('accounts:support_create'), {'body': 'پیام'}).status_code, 403)
        self.assertEqual(csrf_client.post(self.detail(ticket), {'action': 'close'}).status_code, 403)
        csrf_client.force_login(self.admin)
        self.assertEqual(csrf_client.post(self.detail(ticket, True), {'body': 'پاسخ'}).status_code, 403)

    def test_deleted_event_keeps_conversation_and_staff_responds(self):
        self.create(category='program', event=self.event.pk)
        ticket = SupportTicket.objects.get()
        self.event.delete()
        ticket.refresh_from_db()
        self.assertIsNone(ticket.event)
        self.assertContains(self.client.get(self.detail(ticket)), 'برنامه حذف شده')
        self.client.force_login(self.admin)
        self.assertEqual(self.client.post(self.detail(ticket, True), {'body': 'پیگیری'}).status_code, 302)

    def test_new_form_and_admin_thread_render_and_prefilled_program(self):
        response = self.client.get(reverse('accounts:support_create'), {'category': 'program', 'event': self.event.pk})
        self.assertEqual(response.context['form']['event'].value(), str(self.event.pk))
        self.assertContains(response, 'data-support-event')
        self.create()
        ticket = SupportTicket.objects.get()
        self.client.force_login(self.admin)
        self.assertContains(self.client.get(self.detail(ticket, True)), 'پاسخ به کاربر')
        self.assertContains(self.client.get(reverse('management:dashboard')), 'تیکت‌های پشتیبانی')
