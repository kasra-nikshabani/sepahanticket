from datetime import timedelta
from tempfile import TemporaryDirectory
from django.contrib.admin.models import LogEntry
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import transaction
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from accounts.models import User, Notification
from matches.models import Event, Match, Stadium, Block, Row, Seat
from tickets.models import Ticket
from .models import ArtistProfile, ArtistCredit, ArtistFollow
from .services import notify_artist_event


@override_settings(CULTURAL_PLATFORM=True)
class ArtistTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = User.objects.create_user(username='artist-owner', first_name='نام حساب', email='private@example.com', phone_number='09121110000')
        cls.fan = User.objects.create_user(username='artist-fan')
        cls.other = User.objects.create_user(username='artist-other')
        cls.admin = User.objects.create_user(username='artist-admin', is_staff=True)
        cls.artist = ArtistProfile.objects.create(owner=cls.owner, display_name='مهتاب هنر', discipline='actor',
            biography='بیوگرافی هنری برای معرفی فعالیت‌های نمایشی.', status='approved', city='تهران')
        cls.venue = Stadium.objects.create(name='سالن هنر', capacity=2)
        cls.block = Block.objects.create(stadium=cls.venue, name='همکف', price=100000)
        cls.row = Row.objects.create(block=cls.block, number=1)
        Seat.objects.create(row=cls.row, number=1)
        Seat.objects.create(row=cls.row, number=2)
        cls.event = Event.objects.create(title='اجرای هنری', category='theater', is_active=False)
        cls.session = Match.objects.create(event=cls.event, stadium=cls.venue,
            date_time=timezone.now()+timedelta(days=2), ticket_sales_enabled=False)

    def setUp(self):
        self.media = TemporaryDirectory()
        self.addCleanup(self.media.cleanup)
        override = override_settings(MEDIA_ROOT=self.media.name)
        override.enable()
        self.addCleanup(override.disable)
        self.client.force_login(self.fan)

    def credit(self, **kwargs):
        return ArtistCredit.objects.create(artist=self.artist, event=self.event, role='بازیگر', created_by=self.admin, **kwargs)

    def publish(self):
        self.event.is_active = True
        self.event.save()

    def form_data(self, **kwargs):
        return {'display_name': 'مهتاب هنر', 'discipline': 'actor', 'biography': self.artist.biography,
                'action': 'save', **kwargs}

    def test_public_pages_hide_unapproved_suspended_and_inactive_profiles_and_private_account_data(self):
        url = self.artist.get_absolute_url()
        response = self.client.get(url)
        self.assertContains(response, 'مهتاب هنر')
        self.assertNotContains(response, self.owner.email)
        self.assertNotContains(response, self.owner.phone_number)
        self.assertNotContains(response, self.owner.username)
        self.assertNotContains(response, 'نام حساب')
        self.assertEqual(self.client.get(reverse('artists:directory'), {'q': 'مهتاب'}).context['page_obj'].paginator.count, 1)
        for state in ('pending', 'draft', 'revision'):
            ArtistProfile.objects.filter(pk=self.artist.pk).update(status=state)
            self.assertEqual(self.client.get(url).status_code, 404)
            self.assertEqual(self.client.get(reverse('artists:directory')).context['page_obj'].paginator.count, 0)
        ArtistProfile.objects.filter(pk=self.artist.pk).update(status='approved', is_visible=False)
        self.assertEqual(self.client.get(url).status_code, 404)
        ArtistProfile.objects.filter(pk=self.artist.pk).update(is_visible=True)
        User.objects.filter(pk=self.owner.pk).update(is_active=False)
        self.assertEqual(self.client.get(url).status_code, 404)

    def test_get_does_not_create_profile_and_owner_cannot_approve_or_change_visibility(self):
        url = reverse('artists:edit')
        before = ArtistProfile.objects.count()
        self.assertEqual(self.client.get(url).status_code, 200)
        self.assertEqual(ArtistProfile.objects.count(), before)
        data = self.form_data(display_name='هنرمند تازه', action='submit', status='approved', owner=self.owner.pk, is_visible='on')
        self.assertRedirects(self.client.post(url, data), url)
        profile = ArtistProfile.objects.get(owner=self.fan)
        self.assertEqual(profile.status, 'pending')
        self.assertEqual(profile.owner_id, self.fan.pk)
        self.assertEqual(profile.owner.user_type, 'normal')
        ArtistProfile.objects.filter(pk=profile.pk).update(is_visible=False)
        self.client.post(url, data)
        profile.refresh_from_db()
        self.assertFalse(profile.is_visible)

    def test_review_requires_biography_and_valid_images_and_web_links(self):
        url = reverse('artists:edit')
        for extra, field in [({'action': 'submit', 'biography': ''}, 'biography'),
            ({'website': 'javascript:alert(1)'}, 'website'), ({'website': 'ftp://example.com/'}, 'website'),
            ({'avatar': SimpleUploadedFile('photo.jpg', b'not an image', content_type='image/jpeg')}, 'avatar')]:
            response = self.client.post(url, self.form_data(**extra))
            self.assertEqual(response.status_code, 200)
            self.assertIn(field, response.context['form'].errors)
            self.assertFalse(ArtistProfile.objects.filter(owner=self.fan).exists())

    def test_approved_artist_can_edit_bio_but_name_change_requires_review_and_keeps_followers(self):
        ArtistFollow.objects.create(user=self.fan, artist=self.artist)
        self.client.force_login(self.owner)
        url = reverse('artists:edit')
        self.client.post(url, self.form_data(biography='معرفی تازه‌ای از تجربه‌های هنری خودم.'))
        self.artist.refresh_from_db()
        self.assertEqual(self.artist.status, 'approved')
        self.client.post(url, self.form_data(display_name='نام هنری تازه'))
        self.artist.refresh_from_db()
        self.assertEqual(self.artist.status, 'pending')
        self.assertEqual(self.artist.follows.count(), 1)
        self.assertEqual(self.client.get(self.artist.get_absolute_url()).status_code, 404)

    def test_follow_is_idempotent_post_only_csrf_protected_and_cannot_follow_self(self):
        url = reverse('artists:follow', args=[self.artist.pk])
        self.assertEqual(self.client.get(url).status_code, 405)
        csrf = Client(enforce_csrf_checks=True)
        csrf.force_login(self.fan)
        self.assertEqual(csrf.post(url, {'action': 'follow'}).status_code, 403)
        for _ in range(2):
            self.assertRedirects(self.client.post(url, {'action': 'follow'}), self.artist.get_absolute_url())
        self.assertEqual(ArtistFollow.objects.count(), 1)
        self.client.post(url, {'action': 'notifications'})
        self.assertFalse(ArtistFollow.objects.get().notify_events)
        self.client.post(url, {'action': 'notifications', 'notify_events': 'on'})
        self.assertTrue(ArtistFollow.objects.get().notify_events)
        self.client.post(url, {'action': 'unfollow'})
        self.assertFalse(ArtistFollow.objects.exists())
        self.client.force_login(self.owner)
        self.assertEqual(self.client.post(url, {'action': 'follow'}).status_code, 400)

    def test_confirmation_is_owner_only_pending_only_and_does_not_edit_programme(self):
        credit = self.credit()
        url = reverse('artists:confirm_credit', args=[credit.pk])
        self.assertEqual(self.client.post(url, {'action': 'accept'}).status_code, 404)
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get(url).status_code, 405)
        self.assertRedirects(self.client.post(url, {'action': 'accept'}), reverse('artists:edit'))
        credit.refresh_from_db()
        self.assertEqual(credit.status, 'accepted')
        self.assertIsNotNone(credit.confirmed_at)
        self.assertEqual(self.client.post(url, {'action': 'decline'}).status_code, 400)
        self.event.refresh_from_db()
        self.assertFalse(self.event.is_active)
        self.assertEqual(self.event.artists, '')

    def test_only_confirmed_credits_appear_on_event_and_artist_pages(self):
        self.publish()
        credit = self.credit()
        url = reverse('matches:event_detail', args=[self.event.pk])
        self.assertNotContains(self.client.get(url), self.artist.get_absolute_url())
        credit.status = 'accepted'
        credit.save()
        response = self.client.get(url)
        self.assertContains(response, self.artist.get_absolute_url())
        self.assertContains(self.client.get(self.artist.get_absolute_url()), self.event.title)
        ArtistProfile.objects.filter(pk=self.artist.pk).update(is_visible=False)
        self.assertNotContains(self.client.get(url), self.artist.get_absolute_url())

    def test_following_feed_contains_only_my_followed_confirmed_public_future_programmes_without_duplicates(self):
        self.publish()
        ArtistFollow.objects.create(user=self.fan, artist=self.artist)
        self.credit(status='accepted')
        ArtistCredit.objects.create(artist=self.artist, event=self.event, role='نویسنده', status='accepted')
        other_event = Event.objects.create(title='برنامه خصوصی', category='event', is_active=False)
        ArtistCredit.objects.create(artist=self.artist, event=other_event, role='بازیگر', status='accepted')
        response = self.client.get(reverse('artists:following'))
        self.assertEqual(response.context['page_obj'].paginator.count, 1)
        self.assertContains(response, self.event.title)
        self.assertNotContains(response, 'برنامه خصوصی')
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(reverse('artists:following')).context['page_obj'].paginator.count, 0)
        self.client.force_login(self.fan)
        Match.objects.filter(pk=self.session.pk).update(date_time=timezone.now()-timedelta(days=1))
        self.assertEqual(self.client.get(reverse('artists:following')).context['page_obj'].paginator.count, 0)

    def test_staff_review_requires_complete_pending_profile_and_is_audited_with_private_feedback(self):
        ArtistProfile.objects.filter(pk=self.artist.pk).update(status='pending')
        url = reverse('management:artist_detail', args=[self.artist.pk])
        self.assertEqual(self.client.get(url).status_code, 302)
        self.assertEqual(self.client.post(url, {'action': 'approve'}).status_code, 302)
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(reverse('management:artists')).status_code, 200)
        self.assertEqual(self.client.get(url).status_code, 200)
        self.client.post(url, {'action': 'revision'})
        self.artist.refresh_from_db()
        self.assertEqual(self.artist.status, 'pending')
        self.client.post(url, {'action': 'revision', 'note': 'نمونه‌کار را اضافه کنید.'})
        self.artist.refresh_from_db()
        self.assertEqual(self.artist.status, 'revision')
        notice = Notification.objects.get(recipient=self.owner)
        self.assertEqual(notice.action_url, reverse('artists:edit'))
        self.assertTrue(LogEntry.objects.exists())
        self.client.post(url, {'action': 'approve'})
        self.artist.refresh_from_db()
        self.assertEqual(self.artist.status, 'revision')
        ArtistProfile.objects.filter(pk=self.artist.pk).update(status='pending')
        self.client.post(url, {'action': 'approve'})
        self.artist.refresh_from_db()
        self.assertTrue(self.artist.is_public)
        self.assertEqual(self.artist.reviewed_by_id, self.admin.pk)

    def test_staff_credit_addition_does_not_publish_until_artist_accepts_and_can_be_removed(self):
        self.publish()
        self.client.force_login(self.admin)
        url = reverse('management:artist_detail', args=[self.artist.pk])
        data = {'action': 'add_credit', 'event': self.event.pk, 'role': 'بازیگر'}
        self.client.post(url, data)
        self.client.post(url, data)
        credit = ArtistCredit.objects.get()
        self.assertEqual(credit.status, 'pending')
        self.assertEqual(Notification.objects.filter(recipient=self.owner).count(), 1)
        self.assertNotContains(self.client.get(reverse('matches:event_detail', args=[self.event.pk])), self.artist.get_absolute_url())
        remove_url = reverse('management:artist_credit_remove', args=[credit.pk])
        self.assertEqual(self.client.get(remove_url).status_code, 405)
        self.client.post(remove_url)
        self.assertFalse(ArtistCredit.objects.exists())

    def test_new_publication_notifies_only_enabled_followers_once_and_rolls_back(self):
        self.credit(status='accepted')
        ArtistFollow.objects.create(user=self.fan, artist=self.artist)
        ArtistFollow.objects.create(user=self.other, artist=self.artist, notify_events=False)
        with self.assertRaises(ValueError), transaction.atomic():
            self.publish()
            self.assertEqual(Notification.objects.filter(recipient=self.fan).count(), 1)
            raise ValueError('rollback')
        self.assertFalse(Notification.objects.exists())
        self.publish()
        self.event.save()
        notify_artist_event(self.event)
        self.assertEqual(Notification.objects.filter(recipient=self.fan, dedupe_key=f'artist-program:{self.event.pk}').count(), 1)
        self.assertFalse(Notification.objects.filter(recipient=self.other).exists())
        self.assertFalse(Notification.objects.filter(recipient=self.owner).exists())

    def test_opening_sales_notifies_once_and_hidden_artists_do_not_notify(self):
        self.credit(status='accepted')
        ArtistFollow.objects.create(user=self.fan, artist=self.artist)
        self.publish()
        Notification.objects.all().delete()
        self.session.ticket_sales_enabled = True
        self.session.save()
        self.assertEqual(Notification.objects.get().dedupe_key, f'artist-sale:{self.session.pk}')
        self.session.ticket_sales_enabled = False
        self.session.save()
        self.session.ticket_sales_enabled = True
        self.session.save()
        self.assertEqual(Notification.objects.count(), 1)
        ArtistProfile.objects.filter(pk=self.artist.pk).update(is_visible=False)
        Notification.objects.all().delete()
        self.session.ticket_sales_enabled = False
        self.session.save()
        self.session.ticket_sales_enabled = True
        self.session.save()
        self.assertFalse(Notification.objects.exists())

    def test_multiple_followed_artists_in_one_event_generate_one_notice(self):
        self.credit(status='accepted')
        another = ArtistProfile.objects.create(owner=self.other, display_name='هنرمند دیگر', status='approved')
        ArtistCredit.objects.create(artist=another, event=self.event, role='کارگردان', status='accepted')
        ArtistFollow.objects.create(user=self.fan, artist=self.artist)
        ArtistFollow.objects.create(user=self.fan, artist=another)
        self.publish()
        self.assertEqual(Notification.objects.filter(recipient=self.fan).count(), 1)

    def test_sales_notice_requires_enabled_inventory(self):
        self.credit(status='accepted')
        self.publish()
        ArtistFollow.objects.create(user=self.fan, artist=self.artist)
        self.session.match_seats.update(is_enabled=False)
        self.session.ticket_sales_enabled = True
        self.session.save()
        self.assertFalse(Notification.objects.exists())

    def test_sales_notice_excludes_sold_seats_even_with_stale_availability_flags(self):
        self.credit(status='accepted')
        self.publish()
        ArtistFollow.objects.create(user=self.fan, artist=self.artist)
        Ticket.objects.bulk_create([
            Ticket(user=self.other, match=self.session, seat=inventory.seat, match_seat=inventory,
                full_name='خریدار', national_code='', price=100000, status='paid')
            for inventory in self.session.match_seats.all()
        ])
        self.assertTrue(self.session.match_seats.filter(is_available=True).exists())
        self.session.ticket_sales_enabled = True
        self.session.save()
        self.assertFalse(Notification.objects.exists())

    def test_sales_notice_does_not_claim_temporarily_reserved_seats_are_purchasable(self):
        self.credit(status='accepted')
        self.publish()
        ArtistFollow.objects.create(user=self.fan, artist=self.artist)
        self.session.match_seats.update(is_available=False, reserved_until=timezone.now()+timedelta(minutes=10))
        self.session.ticket_sales_enabled = True
        self.session.save()
        self.assertFalse(Notification.objects.exists())

    def test_sales_notice_allows_seats_with_expired_reservations(self):
        self.credit(status='accepted')
        self.publish()
        ArtistFollow.objects.create(user=self.fan, artist=self.artist)
        self.session.match_seats.update(is_available=False, reserved_until=timezone.now()-timedelta(minutes=1))
        self.session.ticket_sales_enabled = True
        self.session.save()
        self.assertEqual(Notification.objects.get().dedupe_key, f'artist-sale:{self.session.pk}')

    def test_new_open_session_notifies_after_its_inventory_is_created(self):
        self.credit(status='accepted')
        self.publish()
        ArtistFollow.objects.create(user=self.fan, artist=self.artist)
        new_session = Match.objects.create(event=self.event, stadium=self.venue,
            date_time=timezone.now()+timedelta(days=3), ticket_sales_enabled=True)
        self.assertEqual(new_session.match_seats.count(), 2)
        self.assertEqual(Notification.objects.get().dedupe_key, f'artist-sale:{new_session.pk}')

    def test_preview_seed_is_refused_outside_the_named_preview_database(self):
        from django.core.management import call_command
        from django.core.management.base import CommandError
        with self.assertRaises(CommandError):
            call_command('seed_artist_preview')

    def test_can_stop_following_hidden_artist_without_exposing_profile_to_other_users(self):
        ArtistFollow.objects.create(user=self.fan, artist=self.artist)
        ArtistProfile.objects.filter(pk=self.artist.pk).update(is_visible=False)
        self.assertContains(self.client.get(reverse('artists:following')), 'صفحه فعلاً در دسترس نیست')
        url = reverse('artists:follow', args=[self.artist.pk])
        self.assertRedirects(self.client.post(url, {'action': 'unfollow'}), reverse('artists:following'))
        self.assertFalse(ArtistFollow.objects.exists())
        self.client.force_login(self.other)
        self.assertEqual(self.client.post(url, {'action': 'unfollow'}).status_code, 404)
