import io
import json
import tempfile
from pathlib import Path
from PIL import Image
from django.test import TestCase, override_settings
from django.urls import reverse
from django.core.files.uploadedfile import SimpleUploadedFile
from .models import User, EventSubmission, SubmissionPhoto
from .submission_forms import BasicForm, DetailsForm, SalesForm


class SubmissionWizardTests(TestCase):
    def setUp(self):
        self.upload_dir = tempfile.TemporaryDirectory()
        self.settings_override = override_settings(SUBMISSION_UPLOAD_ROOT=self.upload_dir.name)
        self.settings_override.enable()
        self.addCleanup(self.settings_override.disable)
        self.addCleanup(self.upload_dir.cleanup)
        self.user = User.objects.create_user(username='organizer', phone_number='09121111111')
        self.other = User.objects.create_user(username='other-organizer', phone_number='09122222222')
        self.client.force_login(self.user)

    def image(self, name='poster.png'):
        buffer = io.BytesIO()
        Image.new('RGB', (40, 60), 'green').save(buffer, format='PNG')
        return SimpleUploadedFile(name, buffer.getvalue(), content_type='image/png')

    def url(self, step, submission=None):
        return reverse('accounts:event_submission_step', args=[(submission or self.submission).pk, step])

    def create_draft(self, **extra):
        response = self.client.post(reverse('accounts:event_submission_start'), {
            'category': 'theater', 'prefix': 'نمایش', 'title': 'یک دیدار تازه',
            'action': 'next', **extra,
        })
        self.submission = EventSubmission.objects.get(owner=self.user)
        self.assertRedirects(response, self.url(2))
        return self.submission

    def details(self, **extra):
        return {'start_date': '۱۴۰۵/۰۸/۲۰', 'end_date': '۱۴۰۵/۰۸/۲۱', 'time': '19:30',
                'duration': '۹۰', 'summary': 'روایتی از یک دیدار', 'city': 'تهران',
                'venue': 'سالن نمایش', 'address': 'خیابان هنر', 'venue_mode': 'custom',
                'seat_layout': json.dumps({'version': 1, 'stage': 'top', 'direction': 'rtl', 'sections': [
                    {'id': 'main', 'name': 'همکف', 'rows': [{'number': 1, 'offset': 0, 'seats': [1, 2, None, 3]}]}]}),
                'themes': 'تئاتر', 'styles': 'درام', 'action': 'next', **extra}

    def advance(self):
        self.create_draft(poster=self.image(), cover=self.image('cover.png'), photos=[self.image('scene.png')])
        self.assertRedirects(self.client.post(self.url(2), self.details()), self.url(3))
        self.assertRedirects(self.client.post(self.url(3), {'credits': 'کارگردان: مریم احمدی', 'action': 'next'}), self.url(4))
        self.assertRedirects(self.client.post(self.url(4), {'prices': '۳۵۰٬۰۰۰ تومان', 'license_image': self.image('license.png'), 'action': 'next'}), self.url(5))

    def test_complete_wizard_persists_private_proposal_without_publishing(self):
        from matches.models import Event
        count = Event.objects.count()
        self.advance()
        self.submission.refresh_from_db()
        self.assertEqual(self.submission.data['duration'], 90)
        self.assertEqual(self.submission.photos.count(), 1)
        self.assertTrue(Path(self.submission.poster.path).is_relative_to(self.upload_dir.name))
        response = self.client.get(self.url(5))
        self.assertContains(response, '۱۴۰۵/۰۸/۲۰')
        self.assertContains(response, 'پیش‌نمایش اطلاعات برنامه')
        response = self.client.post(self.url(5), {'organizer_role': 'تهیه‌کننده', 'confirm': 'on', 'action': 'submit', 'owner': self.other.pk, 'status': 'active'})
        self.assertRedirects(response, self.url(5))
        self.submission.refresh_from_db()
        self.assertEqual(self.submission.status, 'submitted')
        self.assertEqual(self.submission.owner, self.user)
        self.assertIsNotNone(self.submission.submitted_at)
        self.assertEqual(Event.objects.count(), count)
        self.assertContains(self.client.get(self.url(5)), 'در انتظار بررسی')
        # Repeated submission and edits cannot change a submitted proposal.
        self.client.post(self.url(1), {'title': 'changed', 'category': 'concert', 'prefix': 'کنسرت'})
        self.submission.refresh_from_db()
        self.assertEqual(self.submission.title, 'یک دیدار تازه')

    def test_ownership_step_order_and_anonymous_access(self):
        self.create_draft()
        self.assertEqual(self.client.get(self.url(5)).status_code, 200)
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(self.url(1)).status_code, 404)
        self.assertEqual(self.client.post(self.url(2), self.details()).status_code, 404)
        self.client.logout()
        self.assertEqual(self.client.get(reverse('accounts:event_submission_start')).status_code, 302)

    def test_invalid_and_malicious_uploads_preserve_values(self):
        response = self.client.post(reverse('accounts:event_submission_start'), {'category': 'sport', 'title': '', 'prefix': ''})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(EventSubmission.objects.exists())
        self.create_draft()
        response = self.client.post(self.url(2), self.details(end_date='۱۴۰۵/۰۸/۱۹'))
        self.assertIn('end_date', response.context['form'].errors)
        self.submission.refresh_from_db()
        self.assertEqual(self.submission.completed_step, 1)
        bad_file = SimpleUploadedFile('poster.png', b'not an image', content_type='image/png')
        form = BasicForm({'category': 'event', 'title': 'جلسه', 'prefix': 'رویداد'}, {'poster': bad_file})
        self.assertFalse(form.is_valid())
        fake_video = SimpleUploadedFile('teaser.mp4', b'not a video')
        form = BasicForm({'category': 'event', 'title': 'جلسه', 'prefix': 'رویداد'}, {'teaser': fake_video})
        self.assertFalse(form.is_valid())

    def test_resume_previous_and_preserve_uploads(self):
        self.create_draft(poster=self.image())
        filename = self.submission.poster.name
        self.assertContains(self.client.get(reverse('accounts:event_submission_start')), 'یک دیدار تازه')
        self.assertRedirects(self.client.post(self.url(2), self.details(action='previous')), self.url(1))
        self.assertRedirects(self.client.post(self.url(1), {'title': 'نام جدید', 'category': 'concert', 'prefix': 'کنسرت', 'action': 'save'}), self.url(1))
        self.submission.refresh_from_db()
        self.assertEqual(self.submission.poster.name, filename)
        self.assertEqual(self.submission.data['duration'], 90)
        self.assertEqual(self.submission.title, 'نام جدید')

    def test_final_confirmation_and_draft_save(self):
        self.advance()
        response = self.client.post(self.url(5), {'organizer_role': 'برگزارکننده', 'action': 'submit'})
        self.assertIn('confirm', response.context['form'].errors)
        self.submission.refresh_from_db()
        self.assertEqual(self.submission.status, 'draft')
        self.assertRedirects(self.client.post(self.url(5), {'organizer_role': 'برگزارکننده', 'action': 'save'}), self.url(5))
        self.submission.refresh_from_db()
        self.assertEqual(self.submission.data['organizer_role'], 'برگزارکننده')
        self.assertEqual(self.submission.status, 'draft')

    def test_asset_access_is_owner_or_staff_only_including_license(self):
        self.advance()
        url = reverse('accounts:event_submission_asset', args=[self.submission.pk, 'license_image'])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertIn('no-store', response['Cache-Control'])
        response.close()
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(url).status_code, 404)
        self.other.is_staff = True
        self.other.save()
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        response.close()

    def test_discount_validation_and_persian_numerals(self):
        form = SalesForm({'prices': 'بلیط عمومی: ۳۰۰۰۰۰', 'group_discount': 'on', 'group_percent': '۲۰', 'group_minimum': '۵'})
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data['group_percent'], 20)
        form = SalesForm({'prices': 'بلیط عمومی', 'group_discount': 'on', 'group_percent': '۱۰۱', 'group_minimum': '۱'})
        self.assertFalse(form.is_valid())
        self.assertIn('group_percent', form.errors)
        self.assertIn('group_minimum', form.errors)
        form = SalesForm({'prices': 'بلیط عمومی', 'student_percent': '۲۰'})
        self.assertTrue(form.is_valid())
        self.assertIsNone(form.cleaned_data['student_percent'])

    def test_scene_photo_removal_is_scoped_and_total_is_limited(self):
        self.create_draft(photos=[self.image('scene.png')])
        photo_id = self.submission.photos.get().pk
        other = EventSubmission.objects.create(owner=self.other, title='دیگر', category='event')
        other_photo = SubmissionPhoto.objects.create(submission=other, image=self.image())
        self.client.post(self.url(1), {'title': 'نمایش', 'prefix': 'نمایش', 'category': 'theater', 'action': 'save',
                                     'remove_photos': [str(photo_id), str(other_photo.pk), 'invalid']})
        self.assertFalse(self.submission.photos.exists())
        self.assertTrue(other.photos.exists())
        uploads = [self.image(f'scene{i}.png') for i in range(11)]
        response = self.client.post(self.url(1), {'title': 'نمایش', 'prefix': 'نمایش', 'category': 'theater', 'photos': uploads})
        self.assertIn('photos', response.context['form'].errors)

    def test_csrf_required_on_creation(self):
        from django.test import Client
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.user)
        self.assertEqual(client.post(reverse('accounts:event_submission_start'), {'title': 'رویداد'}).status_code, 403)
        self.assertFalse(EventSubmission.objects.exists())

    def test_final_submission_rechecks_saved_required_information(self):
        self.advance()
        self.submission.data['styles'] = ''
        self.submission.save()
        response = self.client.post(self.url(5), {'organizer_role': 'تهیه‌کننده', 'confirm': 'on', 'action': 'submit'})
        self.assertRedirects(response, self.url(2))
        self.submission.refresh_from_db()
        self.assertEqual(self.submission.status, 'draft')

    def test_incomplete_draft_sections_can_be_saved_in_any_order(self):
        response = self.client.post(reverse('accounts:event_submission_start'), {
            'category': 'concert', 'title': '', 'prefix': '', 'action': 'save',
        })
        self.submission = EventSubmission.objects.get(owner=self.user)
        self.assertRedirects(response, self.url(1))
        for step in range(1, 6):
            self.assertEqual(self.client.get(self.url(step)).status_code, 200)
        response = self.client.post(self.url(4), {'group_discount': 'on', 'action': 'save'})
        self.assertRedirects(response, self.url(4))
        response = self.client.post(self.url(3), {'credits': 'خواننده: مریم', 'target_step': '2'})
        self.assertRedirects(response, self.url(2))
        response = self.client.post(self.url(2), {'start_date': '۱۴۰۵/۰۹/۲۰', 'action': 'save'})
        self.assertRedirects(response, self.url(2))
        self.submission.refresh_from_db()
        self.assertEqual(self.submission.data['credits'], 'خواننده: مریم')
        self.assertTrue(self.submission.data['group_discount'])
        self.assertEqual(self.submission.data['start_date'], '2026-12-11')
        response = self.client.post(self.url(5), {'organizer_role': 'مدیر گروه', 'confirm': 'on', 'action': 'submit'})
        self.assertRedirects(response, self.url(1))
        self.submission.refresh_from_db()
        self.assertEqual(self.submission.status, 'draft')
        self.assertEqual(self.submission.data['organizer_role'], 'مدیر گروه')

    def test_reopen_preserves_identity_and_locks_category_after_submission(self):
        self.advance()
        self.client.post(self.url(5), {'organizer_role': 'تهیه‌کننده', 'confirm': 'on', 'action': 'submit'})
        self.submission.refresh_from_db()
        original_time = self.submission.submitted_at
        self.assertRedirects(self.client.post(self.url(1), {'action': 'reopen'}), self.url(1))
        self.submission.refresh_from_db()
        self.assertEqual(self.submission.status, 'draft')
        self.assertEqual(self.submission.submitted_at, original_time)
        response = self.client.post(self.url(1), {'title': 'نام تازه', 'category': 'concert', 'prefix': 'نمایش',
                                                 'action': 'save', 'owner': self.other.pk, 'status': 'submitted'})
        self.assertRedirects(response, self.url(1))
        self.submission.refresh_from_db()
        self.assertEqual(self.submission.title, 'نام تازه')
        self.assertEqual(self.submission.category, 'theater')
        self.assertEqual(self.submission.owner, self.user)
        self.assertEqual(self.submission.status, 'draft')
        self.assertRedirects(self.client.post(self.url(5), {'organizer_role': 'تهیه‌کننده', 'confirm': 'on', 'action': 'submit'}), self.url(5))
        self.submission.refresh_from_db()
        self.assertEqual(self.submission.status, 'submitted')

    def test_invalid_supplied_values_are_rejected_even_on_partial_save(self):
        self.create_draft()
        response = self.client.post(self.url(2), {'duration': 'منفی', 'action': 'save'})
        self.assertIn('duration', response.context['form'].errors)
        self.submission.refresh_from_db()
        self.assertNotIn('duration', self.submission.data)

    def test_partial_post_does_not_erase_previously_supplied_text(self):
        self.create_draft()
        self.client.post(self.url(3), {'credits': 'عوامل برنامه', 'related_pages': 'https://example.com', 'action': 'save'})
        self.client.post(self.url(3), {'credits': 'عوامل تازه', 'action': 'save'})
        self.submission.refresh_from_db()
        self.assertEqual(self.submission.data['related_pages'], 'https://example.com')
