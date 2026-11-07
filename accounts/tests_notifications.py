from datetime import timedelta
from django.test import TestCase, Client, override_settings
from django.db import transaction
from django.urls import reverse
from django.utils import timezone
from .models import User, Notification, EventSubmission, SupportTicket
from .notifications import notify
from matches.models import Event, Match, Stadium
from payments.models import Payment


@override_settings(CULTURAL_PLATFORM=True)
class NotificationTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='notified')
        self.other = User.objects.create_user(username='other-notified')
        self.admin = User.objects.create_user(username='notify-admin', is_staff=True)
        self.client.force_login(self.user)

    def notice(self, user=None, key='first'):
        return notify(user or self.user, 'support', 'خبر خصوصی', 'متن <script> خصوصی', reverse('accounts:support_list'), key)

    def test_inbox_badge_and_read_operations_are_private(self):
        owned = self.notice()
        other = self.notice(self.other)
        response = self.client.get(reverse('accounts:notifications'))
        self.assertEqual(len(response.context['page_obj']), 1)
        self.assertEqual(response.context['unread_notification_count'], 1)
        self.assertContains(response, '&lt;script&gt;')
        self.assertEqual(self.client.get(reverse('accounts:notification_open', args=[owned.pk])).status_code, 405)
        owned.refresh_from_db()
        self.assertIsNone(owned.read_at)
        self.assertEqual(self.client.post(reverse('accounts:notification_open', args=[other.pk])).status_code, 404)
        self.assertRedirects(self.client.post(reverse('accounts:notification_open', args=[owned.pk])), reverse('accounts:support_list'))
        owned.refresh_from_db()
        self.assertIsNotNone(owned.read_at)
        self.assertEqual(self.client.get(reverse('accounts:notifications'), {'state': 'unread'}).context['page_obj'].paginator.count, 0)

    def test_mark_all_is_post_only_owner_scoped_and_csrf_protected(self):
        owned = self.notice()
        other = self.notice(self.other)
        url = reverse('accounts:notifications_read_all')
        self.assertEqual(self.client.get(url).status_code, 405)
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.user)
        self.assertEqual(csrf_client.post(url).status_code, 403)
        self.client.post(url)
        owned.refresh_from_db(); other.refresh_from_db()
        self.assertIsNotNone(owned.read_at)
        self.assertIsNone(other.read_at)

    def test_notifications_are_idempotent_and_transactional(self):
        self.assertEqual(self.notice().pk, self.notice().pk)
        self.assertEqual(Notification.objects.count(), 1)
        with self.assertRaises(ValueError), transaction.atomic():
            self.notice(key='rolled-back')
            raise ValueError('rollback')
        self.assertFalse(Notification.objects.filter(dedupe_key='rolled-back').exists())
        for url in ['//example.com', '/\\example.com', 'https://example.com']:
            with self.subTest(url=url), self.assertRaises(ValueError):
                notify(self.user, 'support', 'bad', 'bad', url, 'bad-url')
        existing = self.notice()
        Notification.objects.filter(pk=existing.pk).update(action_url='/\\example.com')
        self.assertRedirects(self.client.post(reverse('accounts:notification_open', args=[existing.pk])), reverse('accounts:notifications'))

    def test_staff_support_reply_notifies_requester_only(self):
        ticket = SupportTicket.objects.create(requester=self.user, category='general', subject='سوال')
        self.client.force_login(self.admin)
        self.client.post(reverse('management:support_detail', args=[ticket.pk]), {'action': 'reply', 'body': 'پاسخ مدیریت'})
        notification = Notification.objects.get()
        self.assertEqual(notification.recipient, self.user)
        self.assertEqual(notification.kind, 'support')
        self.assertEqual(notification.action_url, reverse('accounts:support_detail', args=[ticket.pk]))
        self.client.force_login(self.user)
        self.client.post(reverse('accounts:support_detail', args=[ticket.pk]), {'action': 'reply', 'body': 'ممنون'})
        self.assertEqual(Notification.objects.count(), 1)

    def test_failed_ticket_payment_generates_one_notice_without_issuing_tickets(self):
        event = Event.objects.create(title='کنسرت تست', category='concert')
        venue = Stadium.objects.create(name='سالن تست', capacity=1)
        match = Match.objects.create(event=event, stadium=venue, date_time=timezone.now()+timedelta(days=1))
        payment = Payment.objects.create(user=self.user, match=match, purpose='ticket_purchase', status='pending')
        self.assertFalse(Notification.objects.exists())
        payment.status='failed'; payment.save(); payment.save()
        self.assertEqual(Notification.objects.count(), 1)
        self.assertEqual(Notification.objects.get().kind, 'payment')
        self.assertEqual(match.ticket_set.count(), 0)

    def test_review_message_notifies_creator_with_link_to_private_thread(self):
        from .management_views import send_review_message
        from django.test import RequestFactory
        submission = EventSubmission.objects.create(owner=self.user, category='theater', title='نمایش من')
        request = RequestFactory().post('/'); request.user=self.admin
        with transaction.atomic():
            ticket = send_review_message(request, submission, 'پوستر را اصلاح کنید', needs_changes=True)
        notification = Notification.objects.get()
        self.assertEqual(notification.kind, 'review')
        self.assertEqual(notification.recipient, self.user)
        self.assertEqual(notification.action_url, reverse('accounts:support_detail', args=[ticket.pk]))
