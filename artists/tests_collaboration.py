from datetime import timedelta
from django.contrib.admin.models import LogEntry
from django.db import transaction
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
import jdatetime
from accounts.models import User, EventSubmission, Notification
from matches.models import Event
from .models import (ArtistProfile, ArtistCredit, CollaborationOpportunity as Opportunity,
    CollaborationApplication as Application, CollaborationMessage, CollaborationReport)
from .collaboration_services import change_application_status


@override_settings(CULTURAL_PLATFORM=True)
class CollaborationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = User.objects.create_user(username='project-owner', phone_number='09120000011', email='owner-private@example.com')
        cls.applicant = User.objects.create_user(username='stage-artist', phone_number='09120000012', email='artist-private@example.com')
        cls.other = User.objects.create_user(username='other-applicant')
        cls.stranger = User.objects.create_user(username='stranger')
        cls.admin = User.objects.create_user(username='collaboration-admin', is_staff=True)
        cls.artist = ArtistProfile.objects.create(owner=cls.applicant, display_name='هنرمند صحنه',
            status='approved', biography='معرفی هنری برای همکاری در پروژه‌های نمایشی.', skills='مدیریت پشت صحنه',
            experience='همکاری در دو نمایش', city='اصفهان', preferred_role='stage', looking_for_work=True)
        cls.other_artist = ArtistProfile.objects.create(owner=cls.other, display_name='هنرمند دوم', status='approved')
        cls.event = Event.objects.create(title='پروژه در حال تولید', category='theater', is_active=False)
        EventSubmission.objects.create(owner=cls.owner, title=cls.event.title, category='theater', published_event=cls.event)

    def setUp(self):
        self.client.force_login(self.owner)
        self.opportunity = Opportunity.objects.create(owner=self.owner, title='دستیار صحنه برای نمایش',
            project_name='نمایش تازه', organizer_name='گروه نمایشی', role='stage', city='اصفهان',
            description='برای تمرین و اجرای نمایش به یک دستیار صحنه نیاز داریم.', schedule='سه عصر در هفته',
            positions=1, deadline=timezone.localdate()+timedelta(days=10), pay_type='negotiable',
            pay_details='پرداخت برای کل پروژه پس از توافق', status='published')

    def data(self, **extra):
        day = jdatetime.date.fromgregorian(date=timezone.localdate()+timedelta(days=10)).strftime('%Y/%m/%d')
        return {'title': 'فراخوان تازه', 'project_name': 'نمایش تازه', 'organizer_name': 'گروه هنری',
            'role': 'stage', 'city': 'اصفهان', 'positions': '۱', 'deadline': day,
            'description': 'شرح کامل وظایف و همکاری در پروژهٔ هنری تازه.', 'schedule': 'شنبه و دوشنبه ساعت ۱۸',
            'pay_type': 'negotiable', 'pay_details': 'مبلغ توافقی برای کل پروژه', 'action': 'submit', **extra}

    def application_data(self, **extra):
        return {'introduction': 'در زمینهٔ مدیریت صحنه تجربه دارم و علاقه‌مند به همکاری هستم.',
            'availability': 'عصرهای شنبه تا چهارشنبه', 'portfolio_url': 'https://example.com/work', **extra}

    def apply(self, user=None, opportunity=None):
        user = user or self.applicant
        opportunity = opportunity or self.opportunity
        self.client.force_login(user)
        response = self.client.post(reverse('artists:opportunity_apply', args=[opportunity.pk]), self.application_data())
        self.assertEqual(response.status_code, 302)
        return Application.objects.get(opportunity=opportunity, applicant=user)

    def change(self, application, action, user=None):
        self.client.force_login(user or self.owner)
        return self.client.post(reverse('artists:application_status', args=[application.pk]), {'action': action})

    def test_complete_review_application_conversation_selection_and_confirmation_flow(self):
        response = self.client.post(reverse('artists:opportunity_create'), self.data(event=self.event.pk))
        self.assertEqual(response.status_code, 302)
        opportunity = Opportunity.objects.get(title='فراخوان تازه')
        self.assertEqual(opportunity.status, 'pending')
        self.assertEqual(self.client.get(opportunity.get_absolute_url()).status_code, 200)
        self.client.force_login(self.applicant)
        self.assertEqual(self.client.get(opportunity.get_absolute_url()).status_code, 404)
        self.client.force_login(self.admin)
        review = reverse('management:opportunity_detail', args=[opportunity.pk])
        self.assertEqual(self.client.post(review, {'action': 'approve'}).status_code, 302)
        opportunity.refresh_from_db()
        self.assertTrue(opportunity.is_open)
        application = self.apply(opportunity=opportunity)
        self.change(application, 'reviewing')
        self.change(application, 'invited')
        self.assertEqual(self.client.post(application.get_absolute_url(), {'body': 'برای گفت‌وگو دوشنبه مناسب است؟'}).status_code, 302)
        self.change(application, 'selected')
        application.refresh_from_db()
        self.assertEqual(application.status, 'selected')
        self.change(application, 'accept', self.applicant)
        application.refresh_from_db()
        self.assertEqual(application.status, 'accepted')
        self.assertEqual(application.status_changes.count(), 5)
        self.assertTrue(Notification.objects.filter(recipient=self.owner, dedupe_key__startswith='collaboration-status:').exists())
        self.assertFalse(ArtistCredit.objects.exists())
        self.event.refresh_from_db()
        self.assertFalse(self.event.is_active)
        self.assertEqual(self.applicant.user_type, 'normal')

    def test_create_cannot_spoof_owner_status_or_link_someone_elses_event(self):
        url = reverse('artists:opportunity_create')
        self.client.post(url, self.data(owner=self.other.pk, status='published', reviewed_by=self.admin.pk))
        item = Opportunity.objects.get(title='فراخوان تازه')
        self.assertEqual(item.owner_id, self.owner.pk)
        self.assertEqual(item.status, 'pending')
        self.assertIsNone(item.reviewed_by_id)
        foreign_event = Event.objects.create(title='برنامه دیگری', category='concert')
        response = self.client.post(url, self.data(title='ارتباط غیرمجاز', event=foreign_event.pk))
        self.assertIn('event', response.context['form'].errors)
        self.assertFalse(Opportunity.objects.filter(title='ارتباط غیرمجاز').exists())

    def test_partial_draft_can_be_saved_then_completed_and_submitted(self):
        response = self.client.post(reverse('artists:opportunity_create'), {'title': 'پیش‌نویس ناتمام', 'action': 'save'})
        self.assertEqual(response.status_code, 302)
        item = Opportunity.objects.get(title='پیش‌نویس ناتمام')
        self.assertEqual(item.status, 'draft')
        self.assertIsNone(item.deadline)
        self.assertFalse(item.is_open)
        url = reverse('artists:opportunity_edit', args=[item.pk])
        self.assertEqual(self.client.get(url).status_code, 200)
        self.client.post(url, self.data(version=item.updated_at.isoformat()))
        item.refresh_from_db()
        self.assertEqual(item.status, 'pending')

    def test_form_validates_pay_range_persian_numbers_dates_and_whitespace(self):
        url = reverse('artists:opportunity_create')
        for fields, expected in [({'pay_type': 'range'}, 'pay_min'),
            ({'pay_type': 'range', 'pay_min': '۲۰۰۰۰۰', 'pay_max': '۱۰۰۰۰۰'}, 'pay_max'),
            ({'deadline': '۱۴۰۵/۱۳/۱۰'}, 'deadline'), ({'schedule': '   '}, 'schedule'),
            ({'description': 'کوتاه'}, 'description'), ({'positions': '۰'}, 'positions')]:
            with self.subTest(fields=fields):
                response = self.client.post(url, self.data(**fields))
                self.assertEqual(response.status_code, 200)
                self.assertIn(expected, response.context['form'].errors)
        response = self.client.post(url, self.data(pay_type='range', pay_min='۲٬۰۰۰٬۰۰۰', pay_max='۳٬۰۰۰٬۰۰۰'))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Opportunity.objects.get(title='فراخوان تازه').pay_min, 2000000)

    def test_public_list_and_apply_hide_unreviewed_expired_closed_and_inactive_owners(self):
        self.client.force_login(self.applicant)
        for state in ('draft', 'pending', 'revision', 'paused', 'closed'):
            Opportunity.objects.filter(pk=self.opportunity.pk).update(status=state)
            self.assertEqual(self.client.get(reverse('artists:opportunities')).context['page_obj'].paginator.count, 0)
            self.assertEqual(self.client.get(reverse('artists:opportunity_apply', args=[self.opportunity.pk])).status_code, 404)
        Opportunity.objects.filter(pk=self.opportunity.pk).update(status='published', deadline=timezone.localdate()-timedelta(days=1))
        self.assertEqual(self.client.get(reverse('artists:opportunities')).context['page_obj'].paginator.count, 0)
        self.assertEqual(self.client.post(reverse('artists:opportunity_apply', args=[self.opportunity.pk]), self.application_data()).status_code, 404)
        Opportunity.objects.filter(pk=self.opportunity.pk).update(deadline=timezone.localdate())
        User.objects.filter(pk=self.owner.pk).update(is_active=False)
        self.assertEqual(self.client.get(self.opportunity.get_absolute_url()).status_code, 404)

    def test_public_pages_never_expose_account_contacts_application_messages_or_review_notes(self):
        application = self.apply()
        CollaborationMessage.objects.create(application=application, sender=self.applicant, body='گفت‌وگوی خصوصی من')
        Opportunity.objects.filter(pk=self.opportunity.pk).update(review_note='پیام خصوصی مدیریت')
        self.client.logout()
        response = self.client.get(self.opportunity.get_absolute_url())
        for private in (self.owner.email, self.owner.phone_number, self.applicant.email, self.applicant.phone_number,
            application.introduction, 'گفت‌وگوی خصوصی من', 'پیام خصوصی مدیریت'):
            self.assertNotContains(response, private)

    def test_application_requires_approved_visible_profile_and_disallows_self_application(self):
        url = reverse('artists:opportunity_apply', args=[self.opportunity.pk])
        self.assertEqual(self.client.post(url, self.application_data()).status_code, 404)
        for user, state, visible in [(self.stranger, None, True), (self.applicant, 'pending', True), (self.applicant, 'approved', False)]:
            if state:
                ArtistProfile.objects.filter(owner=user).update(status=state, is_visible=visible)
            self.client.force_login(user)
            self.assertRedirects(self.client.post(url, self.application_data()), reverse('artists:edit'))
        self.assertFalse(Application.objects.exists())

    def test_application_validation_rejects_short_intro_and_unsafe_portfolio(self):
        self.client.force_login(self.applicant)
        url = reverse('artists:opportunity_apply', args=[self.opportunity.pk])
        for data, field in [({'introduction': 'سلام'}, 'introduction'), ({'availability': ' '}, 'availability'),
            ({'portfolio_url': 'javascript:alert(1)'}, 'portfolio_url'), ({'portfolio_url': 'ftp://example.com'}, 'portfolio_url')]:
            response = self.client.post(url, self.application_data(**data))
            self.assertIn(field, response.context['form'].errors)
        self.assertFalse(Application.objects.exists())

    def test_duplicate_application_is_idempotent_and_withdrawal_can_be_resubmitted(self):
        application = self.apply()
        self.apply()
        self.assertEqual(Application.objects.count(), 1)
        self.assertEqual(Notification.objects.filter(dedupe_key__startswith='collaboration-apply:').count(), 1)
        self.change(application, 'withdraw', self.applicant)
        again = self.apply()
        self.assertEqual(again.pk, application.pk)
        self.assertEqual(again.status, 'submitted')
        self.assertEqual(again.status_changes.count(), 3)

    def test_private_pages_and_status_changes_are_owner_scoped(self):
        application = self.apply()
        self.client.force_login(self.stranger)
        urls = [reverse('artists:opportunity_edit', args=[self.opportunity.pk]),
            reverse('artists:opportunity_manage', args=[self.opportunity.pk]), application.get_absolute_url()]
        for url in urls:
            self.assertEqual(self.client.get(url).status_code, 404)
            self.assertEqual(self.client.post(url, {'body': 'نفوذ', 'action': 'close'}).status_code, 404)
        self.assertEqual(self.client.post(reverse('artists:application_status', args=[application.pk]), {'action': 'selected'}).status_code, 404)
        self.assertEqual(self.client.get(reverse('artists:my_applications')).context['page_obj'].paginator.count, 0)
        self.assertEqual(self.client.get(reverse('artists:my_opportunities')).context['page_obj'].paginator.count, 0)

    def test_applicant_cannot_set_owner_status_and_owner_cannot_accept_for_applicant(self):
        application = self.apply()
        self.change(application, 'accepted')
        self.change(application, 'selected', self.applicant)
        application.refresh_from_db()
        self.assertEqual(application.status, 'submitted')
        self.assertEqual(application.status_changes.count(), 1)

    def test_capacity_is_reserved_by_selection_and_released_by_withdrawal(self):
        first = self.apply()
        second = self.apply(self.other)
        change_application_status(first.pk, self.owner, 'selected')
        with self.assertRaises(ValueError):
            change_application_status(second.pk, self.owner, 'selected')
        second.refresh_from_db()
        self.assertEqual(second.status, 'submitted')
        change_application_status(first.pk, self.applicant, 'withdraw')
        change_application_status(second.pk, self.owner, 'selected')
        change_application_status(second.pk, self.other, 'accept')
        with self.assertRaises(ValueError):
            change_application_status(second.pk, self.owner, 'declined')
        with self.assertRaises(ValueError):
            change_application_status(second.pk, self.other, 'withdraw')

    def test_full_capacity_prevents_fresh_application(self):
        first = self.apply()
        change_application_status(first.pk, self.owner, 'selected')
        self.client.force_login(self.other)
        response = self.client.post(reverse('artists:opportunity_apply', args=[self.opportunity.pk]), self.application_data())
        self.assertContains(response, 'ظرفیت فراخوان')
        self.assertEqual(Application.objects.count(), 1)
        listing = self.client.get(reverse('artists:opportunities'))
        self.assertEqual(listing.context['page_obj'].paginator.count, 0)
        self.assertEqual(list(listing.context['recommended']), [])

    def test_edit_cannot_reduce_positions_below_selected_or_accepted_applicants(self):
        self.opportunity.positions = 2
        self.opportunity.save()
        first = self.apply()
        second = self.apply(self.other)
        change_application_status(first.pk, self.owner, 'selected')
        change_application_status(second.pk, self.owner, 'selected')
        change_application_status(second.pk, self.other, 'accept')
        self.client.force_login(self.owner)
        response = self.client.post(reverse('artists:opportunity_edit', args=[self.opportunity.pk]),
            self.data(positions='۱', version=self.opportunity.updated_at.isoformat()))
        self.assertIn('positions', response.context['form'].errors)
        self.opportunity.refresh_from_db()
        self.assertEqual(self.opportunity.positions, 2)

    def test_owner_can_close_intake_while_existing_applicant_can_confirm(self):
        application = self.apply()
        change_application_status(application.pk, self.owner, 'selected')
        self.client.force_login(self.owner)
        self.client.post(reverse('artists:opportunity_manage', args=[self.opportunity.pk]), {'action': 'close'})
        self.opportunity.refresh_from_db()
        self.assertEqual(self.opportunity.status, 'closed')
        change_application_status(application.pk, self.applicant, 'accept')
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(reverse('artists:opportunity_apply', args=[self.opportunity.pk])).status_code, 404)

    def test_published_edit_requires_review_and_keeps_applications(self):
        application = self.apply()
        self.client.force_login(self.owner)
        url = reverse('artists:opportunity_edit', args=[self.opportunity.pk])
        self.client.post(url, self.data(version=self.opportunity.updated_at.isoformat()))
        self.opportunity.refresh_from_db()
        self.assertEqual(self.opportunity.status, 'pending')
        self.assertTrue(Application.objects.filter(pk=application.pk).exists())
        with self.assertRaises(ValueError):
            change_application_status(application.pk, self.owner, 'selected')
        self.client.force_login(self.applicant)
        self.assertEqual(self.client.get(self.opportunity.get_absolute_url()).status_code, 404)
        self.assertEqual(self.client.get(application.get_absolute_url()).status_code, 200)

    def test_stale_edit_does_not_overwrite_admin_decision(self):
        old_version = self.opportunity.updated_at.isoformat()
        self.opportunity.review_note = 'تصمیم جدید'
        self.opportunity.save()
        self.client.post(reverse('artists:opportunity_edit', args=[self.opportunity.pk]), self.data(version=old_version))
        self.opportunity.refresh_from_db()
        self.assertEqual(self.opportunity.title, 'دستیار صحنه برای نمایش')
        self.assertEqual(self.opportunity.review_note, 'تصمیم جدید')

    def test_pause_blocks_owner_editing_status_changes_and_messages_until_admin_reopens(self):
        application = self.apply()
        self.client.force_login(self.admin)
        review = reverse('management:opportunity_detail', args=[self.opportunity.pk])
        self.client.post(review, {'action': 'pause', 'note': 'نیاز به رسیدگی گزارش'})
        self.client.force_login(self.owner)
        edit = reverse('artists:opportunity_edit', args=[self.opportunity.pk])
        self.assertEqual(self.client.get(edit).status_code, 403)
        self.assertEqual(self.client.post(edit, self.data()).status_code, 403)
        with self.assertRaises(ValueError):
            change_application_status(application.pk, self.owner, 'selected')
        self.client.post(application.get_absolute_url(), {'body': 'پیام غیرمجاز'})
        self.assertFalse(CollaborationMessage.objects.exists())
        self.client.force_login(self.admin)
        self.client.post(review, {'action': 'approve'})
        self.opportunity.refresh_from_db()
        self.assertEqual(self.opportunity.status, 'paused')
        self.client.post(review, {'action': 'reopen', 'note': 'اطلاعات را اصلاح کنید'})
        self.opportunity.refresh_from_db()
        self.assertEqual(self.opportunity.status, 'revision')

    def test_admin_requires_notes_and_valid_complete_pending_opportunity(self):
        self.client.force_login(self.admin)
        review = reverse('management:opportunity_detail', args=[self.opportunity.pk])
        for action in ('pause', 'revision'):
            self.client.post(review, {'action': action})
            self.opportunity.refresh_from_db()
            self.assertEqual(self.opportunity.status, 'published')
        Opportunity.objects.filter(pk=self.opportunity.pk).update(status='pending', description='')
        self.client.post(review, {'action': 'approve'})
        self.opportunity.refresh_from_db()
        self.assertEqual(self.opportunity.status, 'pending')
        self.assertFalse(LogEntry.objects.exists())

    def test_messages_are_private_notified_once_and_staff_access_is_read_only(self):
        application = self.apply()
        self.client.post(application.get_absolute_url(), {'body': 'پیام خصوصی دربارهٔ زمان تمرین'})
        message = CollaborationMessage.objects.get()
        self.assertEqual(Notification.objects.get(dedupe_key=f'collaboration-message:{message.pk}').recipient_id, self.owner.pk)
        self.client.force_login(self.owner)
        self.assertContains(self.client.get(application.get_absolute_url()), message.body)
        self.client.force_login(self.admin)
        self.assertContains(self.client.get(application.get_absolute_url()), message.body)
        self.assertEqual(self.client.post(application.get_absolute_url(), {'body': 'پیام به جای مالک'}).status_code, 403)
        self.assertEqual(CollaborationMessage.objects.count(), 1)

    def test_withdrawn_or_declined_application_cannot_send_messages(self):
        application = self.apply()
        self.change(application, 'withdraw', self.applicant)
        response = self.client.post(application.get_absolute_url(), {'body': 'پیام تازه'})
        self.assertContains(response, 'گفت‌وگو در وضعیت فعلی بسته است')
        self.assertFalse(CollaborationMessage.objects.exists())

    def test_reports_are_deduplicated_private_and_admin_resolution_is_audited(self):
        self.client.force_login(self.applicant)
        url = reverse('artists:opportunity_report', args=[self.opportunity.pk])
        self.client.post(url, {'reason': 'ابهام در شرایط پرداخت'})
        self.client.post(url, {'reason': 'ارسال دوباره'})
        report = CollaborationReport.objects.get()
        self.assertEqual(report.reason, 'ابهام در شرایط پرداخت')
        self.client.force_login(self.owner)
        self.assertNotContains(self.client.get(reverse('artists:opportunity_manage', args=[self.opportunity.pk])), report.reason)
        self.client.force_login(self.admin)
        review = reverse('management:opportunity_detail', args=[self.opportunity.pk])
        self.assertContains(self.client.get(review), report.reason)
        self.client.post(review, {'action': 'resolve_report', 'report_id': report.pk, 'note': 'با صاحب پروژه بررسی شد.'})
        report.refresh_from_db()
        self.assertIsNotNone(report.resolved_at)
        self.assertEqual(report.resolved_by_id, self.admin.pk)
        self.assertTrue(LogEntry.objects.exists())
        self.assertTrue(Notification.objects.filter(recipient=self.applicant, dedupe_key=f'collaboration-report:{report.pk}:resolved').exists())

    def test_admin_lists_reviews_and_filters_are_not_accessible_to_regular_users(self):
        for url in (reverse('management:opportunities'), reverse('management:opportunity_detail', args=[self.opportunity.pk])):
            self.assertEqual(self.client.get(url).status_code, 302)
            self.assertEqual(self.client.post(url, {'action': 'approve'}).status_code, 302)
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(reverse('management:opportunities')).status_code, 200)
        self.assertEqual(self.client.get(reverse('management:opportunity_detail', args=[self.opportunity.pk])).status_code, 200)

    def test_application_changes_and_notifications_roll_back_together(self):
        application = self.apply()
        with self.assertRaises(ValueError), transaction.atomic():
            change_application_status(application.pk, self.owner, 'selected')
            raise ValueError('rollback')
        application.refresh_from_db()
        self.assertEqual(application.status, 'submitted')
        self.assertEqual(application.status_changes.count(), 1)
        self.assertFalse(Notification.objects.filter(dedupe_key__startswith='collaboration-status:').exists())

    def test_recommendations_use_explicit_city_and_role_and_do_not_include_own_postings(self):
        self.client.force_login(self.applicant)
        response = self.client.get(reverse('artists:opportunities'))
        self.assertEqual([item.pk for item in response.context['recommended']], [self.opportunity.pk])
        Opportunity.objects.filter(pk=self.opportunity.pk).update(city='شیراز', role='music')
        self.assertEqual(list(self.client.get(reverse('artists:opportunities')).context['recommended']), [])

    def test_application_snapshot_survives_later_profile_edits(self):
        application = self.apply()
        ArtistProfile.objects.filter(pk=self.artist.pk).update(display_name='نام تازه', skills='مهارت تازه', status='pending')
        self.client.force_login(self.owner)
        response = self.client.get(application.get_absolute_url())
        self.assertContains(response, 'هنرمند صحنه')
        self.assertContains(response, 'مدیریت پشت صحنه')
        self.assertNotContains(response, 'مهارت تازه')

    def test_write_routes_require_csrf_and_get_cannot_change_state(self):
        application = self.apply()
        csrf = Client(enforce_csrf_checks=True)
        csrf.force_login(self.owner)
        routes = [reverse('artists:opportunity_create'), reverse('artists:opportunity_edit', args=[self.opportunity.pk]),
            reverse('artists:opportunity_manage', args=[self.opportunity.pk]), application.get_absolute_url(),
            reverse('artists:application_status', args=[application.pk]), reverse('artists:opportunity_report', args=[self.opportunity.pk])]
        for url in routes:
            self.assertEqual(csrf.post(url, {'action': 'selected', 'body': 'پیام'}).status_code, 403)
        self.assertEqual(self.client.get(reverse('artists:application_status', args=[application.pk])).status_code, 405)
        self.assertEqual(self.client.get(reverse('artists:opportunity_report', args=[self.opportunity.pk])).status_code, 405)
        csrf.force_login(self.applicant)
        self.assertEqual(csrf.post(reverse('artists:opportunity_apply', args=[self.opportunity.pk]), self.application_data()).status_code, 403)
        csrf.force_login(self.admin)
        self.assertEqual(csrf.post(reverse('management:opportunity_detail', args=[self.opportunity.pk]), {'action': 'approve'}).status_code, 403)

    def test_collaboration_preview_seed_is_refused_outside_preview_database(self):
        from django.core.management import call_command
        from django.core.management.base import CommandError
        with self.assertRaises(CommandError):
            call_command('seed_collaboration_preview')
