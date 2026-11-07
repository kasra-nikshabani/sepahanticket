"""Native cultural administration permissions and business workflows."""
import json
import tempfile
from django.contrib.auth import authenticate
from django.contrib.admin.models import LogEntry
from django.core.cache import cache
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from .models import User, EventSubmission
from . import tests_programs as fixtures
from . import tests_submissions as wizard_fixtures
from matches.models import Event, Stadium, Seat, MatchRowPrice
from tickets.models import Ticket


@override_settings(CULTURAL_PLATFORM=True)
class ManagementTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        fixtures.OrganizerProgramTests.setUpTestData.__func__(cls)
        cls.admin = User.objects.create_user(username='panel-admin', password='Test-manager-123',
            user_type='admin', is_staff=True, is_superuser=True,
            phone_number='09123334444', is_phone_verified=True)

    def setUp(self):
        cache.clear()
        self.client.force_login(self.admin)

    def test_all_native_pages_render_and_gets_preserve_business_records(self):
        counts = (Event.objects.count(), Ticket.objects.count(), Stadium.objects.count(), LogEntry.objects.count())
        urls = [reverse('management:' + name) for name in ('dashboard', 'events', 'event_create',
            'sessions', 'session_create', 'requests', 'venues', 'venue_create', 'users', 'sales', 'settings')]
        urls += [reverse('management:' + name, args=[pk]) for name, pk in (
            ('event_edit', self.event.pk), ('session_edit', self.first.pk), ('session_sales', self.first.pk),
            ('session_pricing', self.first.pk), ('venue_edit', self.venue.pk),
            ('user_detail', self.owner.pk), ('request_detail', self.proposal.pk))]
        for url in urls:
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200)
                self.assertIn('no-store', response['Cache-Control'])
        self.assertEqual(counts, (Event.objects.count(), Ticket.objects.count(), Stadium.objects.count(), LogEntry.objects.count()))
        self.assertContains(self.client.get('/admin/'), 'همه‌چیز برای یک دیدار بهتر')

    def test_only_staff_can_read_or_change_panel(self):
        self.client.force_login(self.owner)
        for method in (self.client.get, self.client.post):
            for name in ('dashboard', 'events', 'users', 'settings'):
                self.assertEqual(method(reverse('management:' + name)).status_code, 302)
        self.client.logout()
        response = self.client.get(reverse('management:dashboard'))
        self.assertIn(reverse('accounts:login_password'), response.url)

    def test_real_sales_exclude_pending_cancelled_and_complimentary_amounts(self):
        response = self.client.get(reverse('management:dashboard'))
        self.assertEqual(response.context['stats']['revenue'], 69500000)
        self.assertEqual(response.context['stats']['sold'], 4)
        response = self.client.get(reverse('management:session_sales', args=[self.first.pk]))
        self.assertEqual(response.context['stats']['revenue'], 1200000)
        self.assertContains(response, 'نگار صاحب بلیط')
        self.assertContains(response, 'مریم خریدار')

    def test_password_login_cannot_bypass_hash_and_rejects_external_redirect(self):
        self.client.logout()
        self.assertIsNone(authenticate(username=self.admin.phone_number, password='wrong'))
        self.assertIsNone(authenticate(username=self.admin.username, password='wrong'))
        response = self.client.post(reverse('accounts:login_password') + '?next=https://example.com/',
            {'username': self.admin.username, 'password': 'Test-manager-123'})
        self.assertRedirects(response, reverse('management:dashboard'))

    def test_csrf_and_dashboard_read_only(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.admin)
        self.assertEqual(client.post(reverse('management:settings'), {}).status_code, 403)
        self.assertEqual(self.client.post(reverse('management:dashboard')).status_code, 405)

    def test_vip_registry_and_legacy_navigation_are_retired(self):
        for name in ('tickets:vip_dashboard', 'tickets:manage_vip_users', 'tickets:inquiry_fan'):
            self.assertEqual(self.client.get(reverse(name)).status_code, 404)
        self.assertRedirects(self.client.get(reverse('matches:admin_match_list')), reverse('management:sessions'))
        settings = self.client.get(reverse('management:settings'))
        self.assertNotContains(settings, 'ثبت احوال')
        self.assertNotContains(settings, 'کاربر ویژه')
        self.assertEqual(set(settings.context['form'].fields),
            {'block_foreign_ips', 'wallet_enabled', 'wallet_charge_enabled', 'withdrawal_enabled'})

    def test_admin_pricing_preserves_paid_tickets_and_shared_hall(self):
        Ticket.objects.filter(match=self.first, status='pending').delete()
        url = reverse('management:session_pricing', args=[self.first.pk])
        self.assertRedirects(self.client.post(url, {'scope': 'session', 'target': 'row',
            'row': self.row.pk, 'price': '۳۵۰۰۰۰', 'action': 'apply'}), url)
        self.assertEqual(MatchRowPrice.objects.get().price, 3500000)
        self.assertEqual(Ticket.objects.get(match=self.first, seat=self.seats[0]).price, 1200000)
        self.block.refresh_from_db()
        self.assertEqual(self.block.price, 50000)
        self.assertTrue(LogEntry.objects.exists())

    def test_cannot_enable_past_cancelled_or_unpublished_session(self):
        self.first.is_cancelled = True
        self.first.ticket_sales_enabled = False
        self.first.save()
        self.client.post(reverse('management:session_sales', args=[self.first.pk]), {'action': 'open_sales'})
        self.first.refresh_from_db()
        self.assertFalse(self.first.ticket_sales_enabled)

    def test_native_session_accepts_jalali_date_and_keeps_sales_closed(self):
        response = self.client.post(reverse('management:session_create'), {'event': self.event.pk,
            'stadium': self.venue.pk, 'match_date': '۱۴۰۵/۰۸/۲۰', 'match_time': '19:30', 'is_active': 'on'})
        self.assertEqual(response.status_code, 302)
        session = self.event.sessions.latest('pk')
        self.assertEqual(session.date_time.date().isoformat(), '2026-11-11')
        self.assertTrue(session.has_time)
        self.assertFalse(session.ticket_sales_enabled)
        self.assertEqual(session.match_seats.count(), 8)

    def test_user_form_cannot_grant_admin_or_change_identity_inquiry_settings(self):
        self.client.post(reverse('management:user_detail', args=[self.owner.pk]), {
            'first_name': 'کسری', 'last_name': 'نیک شبانی', 'is_active': 'on', 'user_type': 'admin',
            'is_staff': 'on', 'is_superuser': 'on'})
        self.owner.refresh_from_db()
        self.assertFalse(self.owner.is_staff)
        self.assertFalse(self.owner.is_superuser)
        self.assertEqual(self.owner.user_type, 'normal')
        self.assertEqual(self.client.get(reverse('management:user_detail', args=[self.admin.pk])).status_code, 404)

    def test_admin_hall_builder_creates_real_seats_and_preserves_existing_geometry(self):
        plan = {'version': 1, 'stage': 'top', 'direction': 'rtl', 'sections': [
            {'id': 'main', 'name': 'همکف', 'rows': [{'number': 1, 'offset': 0, 'alignment': 'center', 'curvature': -75, 'seats': [1, None, 2]}]}]}
        response = self.client.post(reverse('management:venue_create'), {'name': 'سالن جدید', 'city': 'تهران',
            'capacity': '۲', 'base_price': '۲۵۰۰۰۰', 'seat_layout': json.dumps(plan)})
        self.assertRedirects(response, reverse('management:venues'))
        venue = Stadium.objects.get(name='سالن جدید')
        self.assertEqual(Seat.objects.filter(row__block__stadium=venue).count(), 2)
        self.assertEqual(venue.blocks.get().price, 2500000)
        venue.refresh_from_db()
        self.assertEqual(venue.seating_layout, plan)
        reference = self.client.get(reverse('accounts:venue_preset', args=[venue.pk])).json()
        self.assertEqual(reference['sections'][0]['rows'][0]['curvature'], -75)
        self.assertIsNone(reference['sections'][0]['rows'][0]['seats'][1])
        self.client.post(reverse('management:venue_edit', args=[venue.pk]), {'name': 'سالن جدید', 'city': 'تهران',
            'capacity': '۲', 'base_price': '۰', 'seat_layout': '{}'})
        self.assertEqual(venue.blocks.get().price, 2500000)
        self.assertEqual(Seat.objects.filter(row__block__stadium=venue).count(), 2)


@override_settings(CULTURAL_PLATFORM=True)
class ManagementPublicationTests(TestCase):
    # Reuse the existing full wizard fixture without inheriting its test methods.
    image = wizard_fixtures.SubmissionWizardTests.image
    url = wizard_fixtures.SubmissionWizardTests.url
    create_draft = wizard_fixtures.SubmissionWizardTests.create_draft
    details = wizard_fixtures.SubmissionWizardTests.details
    advance = wizard_fixtures.SubmissionWizardTests.advance

    def setUp(self):
        self.upload_dir = tempfile.TemporaryDirectory()
        settings = override_settings(SUBMISSION_UPLOAD_ROOT=self.upload_dir.name + '/private', MEDIA_ROOT=self.upload_dir.name + '/public')
        settings.enable()
        self.addCleanup(self.upload_dir.cleanup)
        self.addCleanup(settings.disable)
        self.user = User.objects.create_user(username='creator', first_name='کسری')
        self.admin = User.objects.create_user(username='manager', is_staff=True)
        self.client.force_login(self.user)
        self.advance()
        self.client.post(self.url(5), {'organizer_role': 'تهیه‌کننده', 'confirm': 'on', 'action': 'submit'})
        self.submission.refresh_from_db()
        self.client.force_login(self.admin)
        self.review_url = reverse('management:request_detail', args=[self.submission.pk])

    def test_approval_publishes_art_and_custom_venue_but_keeps_license_private(self):
        response = self.client.post(self.review_url, {'action': 'publish', 'license_checked': 'on'})
        self.assertEqual(response.status_code, 302)
        self.submission.refresh_from_db()
        self.assertEqual(self.submission.status, 'draft')
        self.assertEqual(self.submission.owner, self.user)
        event = self.submission.published_event
        self.assertIsNotNone(event)
        self.assertTrue(event.is_active)
        self.assertEqual(event.scene_images.count(), 1)
        self.assertEqual(self.submission.venue.seating_layout, self.submission.data['seat_layout'])
        self.assertIn('/public/', event.poster.path)
        self.assertIn('/private/', self.submission.license_image.path)
        from .models import Notification
        notice = Notification.objects.get(recipient=self.user, kind='publication')
        self.assertEqual(notice.action_url, reverse('accounts:program_detail', args=[self.submission.pk]))
        self.assertFalse(event.sessions.exists())
        self.assertEqual(self.submission.venue.blocks.get().rows.get().seats.count(), 3)
        self.client.post(self.review_url, {'action': 'publish', 'license_checked': 'on'})
        self.assertEqual(Event.objects.count(), 1)
        self.assertEqual(Notification.objects.filter(recipient=self.user, kind='publication').count(), 1)
        self.client.force_login(self.user)
        self.assertEqual(self.client.post(self.url(3), {'credits': 'عوامل تازه', 'action': 'save'}).status_code, 403)

    def test_return_requires_reason_and_shows_feedback_to_owner(self):
        self.client.post(self.review_url, {'action': 'return'})
        self.submission.refresh_from_db()
        self.assertEqual(self.submission.status, 'submitted')
        self.client.post(self.review_url, {'action': 'return', 'feedback': 'نام عوامل را تکمیل کن'})
        self.submission.refresh_from_db()
        self.assertEqual(self.submission.status, 'draft')
        self.client.force_login(self.user)
        self.assertContains(self.client.get(self.url(3)), 'نام عوامل را تکمیل کن')
        from .models import Notification
        self.assertEqual(Notification.objects.get(recipient=self.user).kind, 'review')

    def test_incomplete_request_cannot_be_published(self):
        self.submission.data['styles'] = ''
        self.submission.save()
        self.client.post(self.review_url, {'action': 'publish', 'license_checked': 'on'})
        self.assertFalse(Event.objects.exists())
        self.submission.refresh_from_db()
        self.assertEqual(self.submission.status, 'submitted')

    def test_publication_requires_existing_license_and_explicit_staff_verification(self):
        response = self.client.post(self.review_url, {'action': 'publish'}, follow=True)
        self.assertContains(response, 'مجوز ارشاد را مشاهده و بررسی آن را تأیید کن')
        self.assertFalse(Event.objects.exists())
        self.submission.license_image.delete(save=True)
        response = self.client.post(self.review_url, {'action': 'publish', 'license_checked': 'on'}, follow=True)
        self.assertContains(response, 'بدون تصویر مجوز ارشاد قابل انتشار نیست')
        self.assertFalse(Event.objects.exists())
        self.assertContains(response, 'انتشار امکان‌پذیر نیست')
        self.submission.refresh_from_db()
        self.assertEqual(self.submission.status, 'submitted')

    def test_missing_license_file_cannot_be_approved_even_if_filename_remains(self):
        self.submission.license_image.storage.delete(self.submission.license_image.name)
        self.client.post(self.review_url, {'action': 'publish', 'license_checked': 'on'})
        self.assertFalse(Event.objects.exists())

    def test_general_event_does_not_require_license_but_still_requires_admin_approval(self):
        self.submission.category = 'event'
        self.submission.data['category'] = 'event'
        self.submission.license_image.delete(save=False)
        self.submission.save()
        self.client.force_login(self.user)
        self.assertEqual(self.client.post(self.review_url, {'action': 'publish'}).status_code, 302)
        self.assertFalse(Event.objects.exists())
        self.client.force_login(self.admin)
        self.client.post(self.review_url, {'action': 'publish'})
        self.submission.refresh_from_db()
        self.assertIsNotNone(self.submission.published_event)
        self.assertEqual(self.submission.published_event.category, 'event')

    def test_both_theater_and_concert_block_submission_without_license_but_allow_draft(self):
        self.client.force_login(self.user)
        self.submission.license_image.delete(save=True)
        self.submission.status = 'draft'
        for category in ('theater', 'concert'):
            self.submission.category = category
            self.submission.data['category'] = category
            self.submission.save()
            response = self.client.get(self.url(4))
            self.assertTrue(response.context['form'].fields['license_image'].required_for_submission)
            self.assertFalse(response.context['form'].fields['license_image'].required)
            self.assertRedirects(self.client.post(self.url(4), {'prices': '۳۰۰۰۰۰', 'action': 'save'}), self.url(4))
            self.assertRedirects(self.client.post(self.url(5), {'organizer_role': 'مدیر', 'confirm': 'on', 'action': 'submit'}), self.url(4))
            self.submission.refresh_from_db()
            self.assertEqual(self.submission.status, 'draft')
            self.assertIsNone(self.submission.published_event)
            self.assertFalse(Event.objects.exists())
        response = self.client.post(self.url(4), {'license_image': self.image('invalid-now-valid.png'), 'action': 'save'})
        self.assertRedirects(response, self.url(4))
        self.assertRedirects(self.client.post(self.url(5), {'organizer_role': 'مدیر', 'confirm': 'on', 'action': 'submit'}), self.url(5))
        self.assertFalse(Event.objects.exists())

    def test_feedback_creates_private_program_conversation_and_preserves_review_history(self):
        from .models import SupportTicket
        self.client.post(self.review_url, {'action': 'message', 'feedback': 'توضیح بیشتر درباره اجرا'})
        self.submission.refresh_from_db()
        self.assertEqual(self.submission.status, 'submitted')
        ticket = SupportTicket.objects.get(submission=self.submission)
        self.assertEqual(ticket.requester, self.user)
        self.assertEqual(ticket.category, 'program')
        self.assertIsNone(ticket.event)
        self.assertEqual(ticket.status, 'answered')
        self.assertEqual(self.submission.data['review_support_ticket'], ticket.pk)
        self.client.post(self.review_url, {'action': 'return', 'feedback': 'مجوز را واضح‌تر بارگذاری کنید'})
        self.submission.refresh_from_db()
        self.assertEqual(self.submission.status, 'draft')
        self.assertEqual(SupportTicket.objects.count(), 1)
        self.assertEqual(ticket.messages.count(), 2)
        self.client.force_login(self.user)
        self.assertContains(self.client.get(self.url(1)), 'مجوز را واضح‌تر بارگذاری کنید')
        self.assertContains(self.client.get(reverse('accounts:program_detail', args=[self.submission.pk])), 'مشاهده پیام‌ها و پاسخ')
        url = reverse('accounts:support_detail', args=[ticket.pk])
        self.assertContains(self.client.get(url), 'توضیح بیشتر درباره اجرا')
        self.assertContains(self.client.get(url), 'جزئیات برنامه')
        self.client.post(url, {'body': 'تصویر تازه را اضافه می‌کنم'})
        ticket.refresh_from_db()
        self.assertEqual(ticket.status, 'waiting')
        self.submission.refresh_from_db()
        self.assertEqual(self.submission.status, 'draft')
        outsider = User.objects.create_user(username='review-outsider')
        self.client.force_login(outsider)
        self.assertEqual(self.client.get(url).status_code, 404)
        self.assertEqual(self.client.get(reverse('accounts:event_submission_asset', args=[self.submission.pk, 'license_image'])).status_code, 404)

    def test_published_changes_require_ticket_and_staff_applies_them(self):
        self.client.post(self.review_url, {'action': 'publish', 'license_checked': 'on'})
        self.submission.refresh_from_db()
        event = self.submission.published_event
        self.assertEqual(self.submission.data['license_review']['reviewed_by'], self.admin.pk)
        original_title = event.title
        self.client.force_login(self.user)
        response = self.client.post(self.url(1), {'category': 'theater', 'prefix': 'نمایش', 'title': 'عنوان اصلاح شده', 'action': 'save'})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.client.post(self.url(5), {'organizer_role': 'تهیه‌کننده', 'confirm': 'on', 'action': 'submit'}).status_code, 403)
        event.refresh_from_db()
        self.submission.refresh_from_db()
        self.assertEqual(event.title, original_title)
        self.assertEqual(self.submission.title, original_title)
        self.assertEqual(self.submission.status, 'draft')
        change_url = reverse('accounts:support_create') + f'?category=program&event={event.pk}&change=1'
        self.assertRedirects(self.client.get(self.url(1)), change_url)
        self.client.post(change_url, {'subject': 'تغییر عنوان', 'body': 'لطفاً عنوان برنامه را تغییر دهید.'})
        ticket = self.user.support_tickets.get()
        self.assertEqual(ticket.event, event)
        self.assertEqual(ticket.submission, self.submission)
        self.client.force_login(self.admin)
        response = self.client.get(reverse('management:support_detail', args=[ticket.pk]))
        self.assertContains(response, reverse('management:event_edit', args=[event.pk]))
        self.assertContains(response, reverse('management:event_report', args=[event.pk]))
        response = self.client.post(reverse('management:event_edit', args=[event.pk]), {
            'title': 'عنوان اصلاح شده', 'category': 'theater', 'duration_minutes': 90, 'is_active': 'on',
            'scenes-TOTAL_FORMS': 1, 'scenes-INITIAL_FORMS': 1,
            'scenes-MIN_NUM_FORMS': 0, 'scenes-MAX_NUM_FORMS': 20,
            'scenes-0-id': event.scene_images.get().pk, 'scenes-0-order': 0,
        })
        self.assertEqual(response.status_code, 302, response.context['form'].errors if response.status_code == 200 else '')
        event.refresh_from_db()
        self.assertEqual(event.title, 'عنوان اصلاح شده')
        self.client.force_login(self.user)
        self.assertContains(self.client.get(reverse('accounts:program_detail', args=[self.submission.pk])), 'عنوان اصلاح شده')

    def test_review_message_validation_and_get_do_not_change_request(self):
        from .models import SupportTicket
        for feedback in ('', ' ' * 5, 'x' * 3001):
            self.client.post(self.review_url, {'action': 'return', 'feedback': feedback})
        self.client.get(self.review_url, {'action': 'publish', 'license_checked': 'on'})
        self.submission.refresh_from_db()
        self.assertEqual(self.submission.status, 'submitted')
        self.assertFalse(SupportTicket.objects.exists())
        self.assertFalse(Event.objects.exists())
