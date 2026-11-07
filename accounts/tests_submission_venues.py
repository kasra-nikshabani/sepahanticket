import json
import tempfile
from copy import deepcopy
from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings
from django.urls import reverse
from accounts.models import User, EventSubmission
from .tests_submissions import SubmissionWizardTests
from accounts.venue_layout import validate_layout, layout_capacity
from matches.models import Stadium, Block, Row, Seat


def plan():
    return {'version': 1, 'stage': 'top', 'direction': 'rtl', 'sections': [
        {'id': 'main', 'name': 'همکف', 'rows': [{'number': 1, 'offset': 0, 'seats': [1, 2, None, 3]},
                                            {'number': 2, 'offset': 1, 'seats': [1, None, 2]}]}]}


class SubmissionVenueTests(TestCase):
    image = SubmissionWizardTests.image
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        settings = override_settings(SUBMISSION_UPLOAD_ROOT=directory.name)
        settings.enable()
        self.addCleanup(directory.cleanup)
        self.addCleanup(settings.disable)
        self.user = User.objects.create_user(username='venue-organizer')
        self.other = User.objects.create_user(username='venue-other')
        self.client.force_login(self.user)
        self.venue = Stadium.objects.create(name='سالن آماده', city='اصفهان', address='خیابان هنر', capacity=3)
        self.block = Block.objects.create(stadium=self.venue, name='همکف')
        self.row = Row.objects.create(block=self.block, number=1)
        Seat.objects.bulk_create([Seat(row=self.row, number=1), Seat(row=self.row, number=2),
                                 Seat(row=self.row, number=3, is_available=False)])
        self.submission = EventSubmission.objects.create(owner=self.user, title='نمایش', category='theater',
            data={'prefix': 'نمایش', 'title': 'نمایش', 'category': 'theater'}, license_image=self.image('license.png'))

    def url(self, step=2):
        return reverse('accounts:event_submission_step', args=[self.submission.pk, step])

    def details(self, **extra):
        return {'venue_mode': 'preset', 'venue_preset': str(self.venue.pk), 'start_date': '۱۴۰۵/۰۸/۲۰',
                'end_date': '۱۴۰۵/۰۸/۲۱', 'time': '19:00', 'duration': '۹۰', 'summary': 'معرفی نمایش',
                'themes': 'تئاتر', 'styles': 'درام', 'action': 'save', **extra}

    def test_select_preset_uses_server_metadata_and_never_changes_live_layout(self):
        response = self.client.post(self.url(), self.details(city='شهر جعلی', venue='نام جعلی', address='نشانی جعلی', capacity='9999'))
        self.assertRedirects(response, self.url())
        self.submission.refresh_from_db()
        self.assertEqual(self.submission.venue, self.venue)
        self.assertEqual(self.submission.data['venue'], self.venue.name)
        self.assertEqual(self.submission.data['city'], self.venue.city)
        self.assertEqual(self.submission.data['address'], self.venue.address)
        self.assertNotIn('capacity', self.submission.data)
        self.venue.refresh_from_db()
        self.assertEqual(self.venue.capacity, 3)
        self.assertEqual(Seat.objects.count(), 3)
        self.assertFalse(Seat.objects.get(number=3).is_available)
        # Another partial edit preserves the chosen reference if the selector wasn't sent.
        self.client.post(self.url(), {'venue_mode': 'preset', 'summary': 'معرفی تازه', 'action': 'save'})
        self.submission.refresh_from_db()
        self.assertEqual(self.submission.venue, self.venue)

    def test_preset_endpoint_is_authenticated_and_read_only(self):
        url = reverse('accounts:venue_preset', args=[self.venue.pk])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['seat_count'], 3)
        self.assertEqual(data['sections'][0]['rows'][0]['seats'][-1], {'number': 3, 'enabled': False})
        self.assertEqual(self.client.post(url).status_code, 405)
        self.client.logout()
        self.assertEqual(self.client.get(url).status_code, 302)

    def test_preset_preview_is_bounded_and_ignores_inactive_rows(self):
        row = Row.objects.create(block=self.block, number=2)
        Seat.objects.bulk_create([Seat(row=row, number=i) for i in range(1, 1301)])
        inactive = Row.objects.create(block=self.block, number=3, is_active=False)
        Seat.objects.create(row=inactive, number=1)
        data = self.client.get(reverse('accounts:venue_preset', args=[self.venue.pk])).json()
        self.assertTrue(data['truncated'])
        self.assertEqual(data['seat_count'], 1303)
        self.assertEqual(sum(len(row['seats']) for section in data['sections'] for row in section['rows']), 1200)

    def test_custom_plan_is_owner_scoped_and_does_not_create_public_hall_or_seats(self):
        response = self.client.post(self.url(), self.details(venue_mode='custom', venue='سالن تازه',
            city='تهران', address='نشانی سالن تازه', seat_layout=json.dumps(plan())))
        self.assertRedirects(response, self.url())
        self.submission.refresh_from_db()
        self.assertIsNone(self.submission.venue)
        self.assertEqual(self.submission.data['seat_layout'], plan())
        self.assertEqual(layout_capacity(self.submission.data['seat_layout']), 5)
        self.assertEqual(Stadium.objects.count(), 1)
        self.assertEqual(Seat.objects.count(), 3)
        self.assertContains(self.client.get(self.url()), 'طراح سالن')
        self.assertContains(self.client.get(self.url(5)), 'چیدمان سالن پیشنهادی')
        self.client.force_login(self.other)
        self.assertEqual(self.client.post(self.url(), {'venue_mode': 'custom', 'seat_layout': '{}'}).status_code, 404)

    def test_switch_to_preset_keeps_custom_plan_for_future_editing(self):
        self.client.post(self.url(), self.details(venue_mode='custom', venue='سالن تازه', city='تهران', address='نشانی', seat_layout=json.dumps(plan())))
        self.client.post(self.url(), self.details())
        self.submission.refresh_from_db()
        self.assertEqual(self.submission.venue, self.venue)
        self.assertEqual(self.submission.data['seat_layout'], plan())
        self.client.post(self.url(), {'venue_mode': 'custom', 'venue': 'سالن تازه', 'action': 'save'})
        self.submission.refresh_from_db()
        self.assertIsNone(self.submission.venue)
        self.assertEqual(self.submission.data['seat_layout'], plan())

    def test_invalid_layout_does_not_overwrite_saved_plan(self):
        self.client.post(self.url(), {'venue_mode': 'custom', 'seat_layout': json.dumps(plan()), 'action': 'save'})
        bad = plan(); bad['sections'][0]['rows'][0]['seats'] = [1, 1]
        response = self.client.post(self.url(), {'venue_mode': 'custom', 'seat_layout': json.dumps(bad), 'action': 'save'})
        self.assertIn('seat_layout', response.context['form'].errors)
        self.submission.refresh_from_db()
        self.assertEqual(self.submission.data['seat_layout'], plan())

    def test_missing_layout_is_allowed_in_draft_but_blocks_submission(self):
        response = self.client.post(self.url(), self.details(venue_mode='custom', city='تهران', venue='سالن تازه', address='نشانی'))
        self.assertRedirects(response, self.url())
        self.client.post(self.url(3), {'credits': 'کارگردان: مریم', 'action': 'save'})
        self.client.post(self.url(4), {'prices': '۳۰۰۰۰۰ تومان', 'action': 'save'})
        response = self.client.post(self.url(5), {'organizer_role': 'مدیر', 'confirm': 'on', 'action': 'submit'})
        self.assertRedirects(response, self.url())
        self.submission.refresh_from_db()
        self.assertEqual(self.submission.status, 'draft')

    def test_online_program_does_not_require_a_physical_hall(self):
        self.submission.data['is_online'] = True
        self.submission.save()
        self.client.post(self.url(), self.details(venue='بستر آنلاین'))
        self.client.post(self.url(3), {'credits': 'هنرمند: مریم', 'action': 'save'})
        self.client.post(self.url(4), {'prices': '۳۰۰۰۰۰ تومان', 'action': 'save'})
        response = self.client.post(self.url(5), {'organizer_role': 'مدیر', 'confirm': 'on', 'action': 'submit'})
        self.assertRedirects(response, self.url(5))
        self.submission.refresh_from_db()
        self.assertEqual(self.submission.status, 'submitted')
        self.assertEqual(self.submission.data['venue_mode'], 'online')
        self.assertIsNone(self.submission.venue)

    def test_nonexistent_preset_cannot_be_saved(self):
        response = self.client.post(self.url(), self.details(venue_preset='999999'))
        self.assertIn('venue_preset', response.context['form'].errors)
        self.submission.refresh_from_db()
        self.assertIsNone(self.submission.venue)

    def test_centered_rows_persist_and_render_in_review(self):
        layout = plan()
        layout['sections'][0]['rows'][0]['alignment'] = 'center'
        layout['sections'][0]['rows'][1]['alignment'] = 'end'
        response = self.client.post(self.url(), self.details(venue_mode='custom', venue='سالن تازه',
            city='تهران', address='نشانی', seat_layout=json.dumps(layout)))
        self.assertRedirects(response, self.url())
        self.submission.refresh_from_db()
        self.assertEqual(self.submission.data['seat_layout'], layout)
        self.assertEqual(layout_capacity(self.submission.data['seat_layout']), 5)
        self.assertContains(self.client.get(self.url(5)), 'venue-row-track align-center')
        self.assertContains(self.client.get(self.url(5)), 'venue-row-track align-end')

    def test_curved_rows_save_reopen_and_render_in_review(self):
        layout = plan()
        layout['sections'][0]['rows'][0]['curvature'] = 100
        layout['sections'][0]['rows'][1]['curvature'] = -50
        response = self.client.post(self.url(), self.details(venue_mode='custom', venue='سالن خمیده',
            city='تهران', address='نشانی', seat_layout=json.dumps(layout)))
        self.assertRedirects(response, self.url())
        self.submission.refresh_from_db()
        self.assertEqual(self.submission.data['seat_layout'], layout)
        self.assertContains(self.client.get(self.url()), 'data-layout-curvature')
        review = self.client.get(self.url(5))
        self.assertContains(review, 'padding-bottom:48px')
        self.assertContains(review, 'padding-top:24px')
        self.assertEqual(layout_capacity(self.submission.data['seat_layout']), 5)

    def test_final_submission_accepts_preset_without_custom_map(self):
        self.client.post(self.url(), self.details())
        self.client.post(self.url(3), {'credits': 'هنرمند: مریم', 'action': 'save'})
        self.client.post(self.url(4), {'prices': '۳۰۰۰۰۰ تومان', 'action': 'save'})
        response = self.client.post(self.url(5), {'organizer_role': 'مدیر', 'confirm': 'on', 'action': 'submit'})
        self.assertRedirects(response, self.url(5))
        self.submission.refresh_from_db()
        self.assertEqual(self.submission.status, 'submitted')
        self.assertEqual(self.submission.venue, self.venue)

    def test_quantity_submission_needs_no_map_and_accepts_persian_capacity_and_free_price(self):
        self.client.post(self.url(), self.details(venue_mode='custom', venue='فضای آزاد',
            city='تهران', address='خیابان هنر', admission_mode='quantity', ticket_capacity='۲۰۰'))
        self.client.post(self.url(3), {'credits': 'هنرمند: مریم', 'action': 'save'})
        self.client.post(self.url(4), {'ticket_price': '۰', 'action': 'save'})
        response = self.client.post(self.url(5), {'organizer_role': 'مدیر', 'confirm': 'on', 'action': 'submit'})
        self.assertRedirects(response, self.url(5))
        self.submission.refresh_from_db()
        self.assertEqual(self.submission.status, 'submitted')
        self.assertEqual(self.submission.data['ticket_capacity'], 200)
        self.assertEqual(self.submission.data['ticket_price'], 0)
        self.assertEqual(Seat.objects.count(), 3)
        self.assertContains(self.client.get(self.url(5)), 'انتخاب تعداد بلیط')
        self.assertNotContains(self.client.get(self.url(5)), 'چیدمان سالن پیشنهادی')

    def test_quantity_draft_can_be_incomplete_but_capacity_and_price_required_on_submit(self):
        from .submission_forms import DetailsForm, SalesForm
        data = self.details(venue_mode='custom', venue='فضای آزاد', city='تهران', address='نشانی', admission_mode='quantity')
        self.assertTrue(DetailsForm(data, partial=True).is_valid())
        details = DetailsForm(data)
        self.assertFalse(details.is_valid())
        self.assertIn('ticket_capacity', details.errors)
        self.assertNotIn('seat_layout', details.errors)
        sales = SalesForm({'prices': 'متن قدیمی'}, initial={'admission_mode': 'quantity'})
        self.assertFalse(sales.is_valid())
        self.assertIn('ticket_price', sales.errors)
        self.assertTrue(SalesForm({}, initial={'admission_mode': 'quantity'}, partial=True).is_valid())

    def test_quantity_capacity_cannot_exceed_preset_or_be_negative(self):
        for value in ('۴', '-۱', '۰'):
            response = self.client.post(self.url(), self.details(admission_mode='quantity', ticket_capacity=value))
            self.assertIn('ticket_capacity', response.context['form'].errors)

    def test_switching_admission_modes_preserves_saved_map_and_quantity_fields(self):
        self.client.post(self.url(), self.details(venue_mode='custom', venue='سالن تازه',
            city='تهران', address='نشانی', seat_layout=json.dumps(plan())))
        self.client.post(self.url(), {'venue_mode': 'custom', 'admission_mode': 'quantity', 'ticket_capacity': '۲۰', 'action': 'save'})
        self.client.post(self.url(4), {'ticket_price': '۳۵۰٬۰۰۰', 'action': 'save'})
        self.client.post(self.url(), {'venue_mode': 'custom', 'admission_mode': 'seated', 'action': 'save'})
        self.submission.refresh_from_db()
        self.assertEqual(self.submission.data['seat_layout'], plan())
        self.assertEqual(self.submission.data['ticket_capacity'], 20)
        self.assertEqual(self.submission.data['ticket_price'], 350000)
        self.assertContains(self.client.get(self.url(5)), 'چیدمان سالن پیشنهادی')
        self.assertNotContains(self.client.get(self.url(5)), 'قیمت هر بلیط (تومان)')


class SeatLayoutValidationTests(TestCase):
    def test_layout_shape_numbers_and_size_are_validated(self):
        invalid = []
        invalid.append('not JSON')
        invalid.append({'version': 2})
        for mutate in (
            lambda p: p.update(stage='unknown'),
            lambda p: p['sections'][0]['rows'][0].update(seats=[1, True]),
            lambda p: p['sections'][0]['rows'][0].update(seats=[1, -2]),
            lambda p: p['sections'][0]['rows'][0].update(offset=21),
            lambda p: p['sections'][0]['rows'][0].update(alignment='invalid'),
            *[lambda p, value=value: p['sections'][0]['rows'][0].update(curvature=value)
              for value in (-101, 101, True, '50', 1.5, None)],
            lambda p: p['sections'][0]['rows'][1].update(number=1),
            lambda p: p['sections'].append(deepcopy(p['sections'][0])),
            lambda p: p['sections'][0].update(rows=[{'number': i, 'seats': list(range(1, 81))} for i in range(1, 62)]),
        ):
            value = plan(); mutate(value); invalid.append(value)
        for value in invalid:
            with self.subTest(value=str(value)[:80]), self.assertRaises(ValidationError):
                validate_layout(value)
        self.assertEqual(validate_layout(plan()), plan())
        self.assertEqual(validate_layout('{}'), {})

    def test_excessive_total_positions_are_rejected(self):
        value = plan()
        value['sections'] = [
            {'id': str(i), 'name': f'بخش {i}', 'rows': [{'number': n, 'seats': list(range(1, 81))} for n in range(1, 41)]}
            for i in range(2)]
        with self.assertRaises(ValidationError):
            validate_layout(value)
