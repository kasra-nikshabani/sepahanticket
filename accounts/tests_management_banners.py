import io
import tempfile
from PIL import Image
from django.contrib.admin.models import LogEntry
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from accounts.models import User
from matches.models import Event, HomeBanner


@override_settings(CULTURAL_PLATFORM=True)
class ManagementBannerTests(TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        settings = override_settings(MEDIA_ROOT=directory.name)
        settings.enable()
        self.addCleanup(directory.cleanup)
        self.addCleanup(settings.disable)
        self.admin = User.objects.create_user(username='banner-manager', is_staff=True)
        self.user = User.objects.create_user(username='banner-user')
        self.event = Event.objects.create(title='نمایش تازه', category='theater')
        self.client.force_login(self.admin)

    def image(self, name='banner.png', format='PNG'):
        buffer = io.BytesIO()
        Image.new('RGB', (400, 84), '#365f4c').save(buffer, format=format)
        return SimpleUploadedFile(name, buffer.getvalue(), content_type='image/png')

    def create(self, **extra):
        data = {'title': 'بنر تازه', 'image': self.image(), 'order': '۲', 'is_active': 'on', 'event': self.event.pk}
        data.update(extra)
        return self.client.post(reverse('management:banner_create'), data)

    def test_upload_real_image_and_show_uploaded_media_link_in_homepage(self):
        self.assertRedirects(self.create(), reverse('management:banners'))
        banner = HomeBanner.objects.get()
        self.assertEqual(banner.order, 2)
        self.assertTrue(banner.image.storage.exists(banner.image.name))
        self.assertEqual(LogEntry.objects.count(), 1)
        self.client.logout()
        response = self.client.get(reverse('matches:home'))
        self.assertContains(response, banner.image.url)
        self.assertContains(response, reverse('matches:event_detail', args=[self.event.pk]))
        self.assertNotContains(response, 'patience-of-sea-banner.jpg')
        self.assertNotContains(response, 'banner-caption')
        self.assertEqual(len(response.context['featured_banners']), 1)

    def test_order_inactive_visibility_and_no_link_to_inactive_event(self):
        self.create(title='دوم', order='۲')
        self.create(title='اول', order='۱')
        self.create(title='خاموش', order='۰', is_active='')
        response = self.client.get(reverse('matches:home'))
        self.assertEqual([item['title'] for item in response.context['featured_banners']], ['اول', 'دوم'])
        self.assertNotContains(response, 'خاموش')
        self.event.is_active = False
        self.event.save()
        response = self.client.get(reverse('matches:home'))
        self.assertTrue(all(item['url'] is None for item in response.context['featured_banners']))
        self.assertNotContains(response, reverse('matches:event_detail', args=[self.event.pk]))

    def test_edit_preserves_uploaded_file_and_inactive_checkbox_state(self):
        self.create(is_active='')
        banner = HomeBanner.objects.get()
        url = reverse('management:banner_edit', args=[banner.pk])
        response = self.client.get(url)
        self.assertFalse(response.context['form']['is_active'].value())
        original = banner.image.name
        self.assertRedirects(self.client.post(url, {'title': 'نام جدید', 'order': '۵', 'event': self.event.pk}), reverse('management:banners'))
        banner.refresh_from_db()
        self.assertEqual(banner.image.name, original)
        self.assertEqual(banner.title, 'نام جدید')
        self.assertFalse(banner.is_active)
        self.assertEqual(banner.order, 5)

    def test_toggle_is_post_only_and_disabling_all_banners_hides_the_slider(self):
        self.create()
        banner = HomeBanner.objects.get()
        url = reverse('management:banner_toggle', args=[banner.pk])
        self.assertEqual(self.client.get(url).status_code, 405)
        self.assertEqual(self.client.post(url, {'action': 'invalid'}).status_code, 404)
        self.assertRedirects(self.client.post(url, {'action': 'deactivate'}), reverse('management:banners'))
        self.assertNotContains(self.client.get(reverse('matches:home')), 'data-slider')
        self.assertEqual(HomeBanner.objects.count(), 1)
        self.assertRedirects(self.client.post(url, {'action': 'activate'}), reverse('management:banners'))
        self.assertContains(self.client.get(reverse('matches:home')), 'data-slider')

    def test_invalid_files_and_values_cannot_create_or_replace_banners(self):
        sport = Event.objects.create(title='ورزش', category='sport')
        for data in [dict(image=SimpleUploadedFile('bad.png', b'not an image')), dict(image=self.image('bad.png', 'GIF')),
                     dict(image=self.image('bad.svg')), dict(order='-۱'), dict(order='۱۰۰۰۰'), dict(event=sport.pk)]:
            with self.subTest(data=list(data)):
                response = self.create(**data)
                self.assertEqual(response.status_code, 200)
                self.assertTrue(response.context['form'].errors)
                self.assertFalse(HomeBanner.objects.exists())
        self.create()
        banner = HomeBanner.objects.get()
        response = self.client.post(reverse('management:banner_edit', args=[banner.pk]),
            {'title': 'خراب', 'order': '۱', 'image': SimpleUploadedFile('bad.png', b'bad'), 'is_active': 'on'})
        self.assertTrue(response.context['form'].errors)
        banner.refresh_from_db()
        self.assertEqual(banner.title, 'بنر تازه')

    def test_oversized_upload_rejected(self):
        upload = self.image()
        oversized = SimpleUploadedFile('large.png', upload.read() + b'0' * (8 * 1024 * 1024), content_type='image/png')
        response = self.create(image=oversized)
        self.assertIn('image', response.context['form'].errors)
        self.assertFalse(HomeBanner.objects.exists())

    def test_access_and_csrf_are_enforced(self):
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(reverse('management:banners')).status_code, 302)
        self.assertEqual(self.create().status_code, 302)
        self.assertFalse(HomeBanner.objects.exists())
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.admin)
        self.assertEqual(client.post(reverse('management:banner_create'), {'title': 'بنر'}).status_code, 403)
        self.assertFalse(HomeBanner.objects.exists())

    def test_initial_banners_remain_until_admin_creates_managed_banners_and_list_is_read_only(self):
        home = self.client.get(reverse('matches:home'))
        self.assertContains(home, 'patience-of-sea-banner.jpg')
        self.assertContains(home, '68-seconds-banner.jpg')
        response = self.client.get(reverse('management:banners'))
        self.assertTrue(response.context['using_defaults'])
        self.assertFalse(HomeBanner.objects.exists())
        self.assertFalse(LogEntry.objects.exists())
        self.assertContains(self.client.get(reverse('management:banner_create')), 'data-banner-preview')

    def test_default_images_visible_and_import_creates_editable_media_banners(self):
        from matches.banner_defaults import DEFAULT_BANNERS
        response = self.client.get(reverse('management:banners'))
        for _, image in DEFAULT_BANNERS:
            self.assertContains(response, '/static/events/uploads/' + image)
        self.assertFalse(HomeBanner.objects.exists())
        url = reverse('management:banner_import_defaults')
        self.assertEqual(self.client.get(url).status_code, 405)
        self.assertRedirects(self.client.post(url), reverse('management:banners'))
        self.assertEqual(HomeBanner.objects.count(), 2)
        self.assertEqual(LogEntry.objects.count(), 2)
        for banner in HomeBanner.objects.all():
            self.assertTrue(banner.image.storage.exists(banner.image.name))
            self.assertContains(self.client.get(reverse('management:banners')), banner.image.url)
            self.assertContains(self.client.get(reverse('management:banner_edit', args=[banner.pk])), banner.image.url)
            self.assertContains(self.client.get(reverse('matches:home')), banner.image.url)
        response = self.client.get(reverse('management:banners'))
        self.assertFalse(response.context['using_defaults'])
        self.client.post(url)
        self.assertEqual(HomeBanner.objects.count(), 2)
        self.assertEqual(LogEntry.objects.count(), 2)

    def test_default_import_preserves_existing_banners_and_enforces_permissions(self):
        url = reverse('management:banner_import_defaults')
        self.client.force_login(self.user)
        self.assertEqual(self.client.post(url).status_code, 302)
        self.assertFalse(HomeBanner.objects.exists())
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.admin)
        self.assertEqual(csrf_client.post(url).status_code, 403)
        self.client.force_login(self.admin)
        self.create(is_active='')
        original = HomeBanner.objects.get()
        self.client.post(url)
        self.assertEqual(HomeBanner.objects.count(), 1)
        original.refresh_from_db()
        self.assertFalse(original.is_active)
