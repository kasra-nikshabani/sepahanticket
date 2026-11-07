from django.urls import reverse
from django.test import TestCase

from . import tests_events as fixtures
from .models import MatchSeat, Row, Seat
from .seating import purchase_rows


class PurchaseSeatingTests(TestCase):
    setUp = fixtures.EventTests.setUp

    def page(self):
        session = self.client.session
        session['selected_block_id'] = self.block.pk
        session.save()
        return self.client.get(reverse('matches:block_map', args=[self.first.pk]))

    def save_layout(self, **row_options):
        self.venue.seating_layout = {'version': 1, 'direction': 'ltr', 'stage': 'bottom', 'sections': [
            {'id': 'main', 'name': self.block.name, 'rows': [
                {'number': 1, 'alignment': 'center', 'curvature': 100,
                 'seats': [3, None, 1, 2], **row_options}]}]}
        self.venue.save(update_fields=['seating_layout'])

    def test_purchase_preserves_physical_order_aisles_curve_and_live_ids(self):
        self.save_layout()
        response = self.page()
        row = response.context['map_data'][0]
        self.assertEqual([cell['number'] if cell else None for cell in row['cells']], [3, None, 1, 2])
        ids = dict(MatchSeat.objects.filter(match=self.first).values_list('seat__number', 'pk'))
        self.assertEqual([cell['id'] for cell in row['cells'] if cell], [ids[3], ids[1], ids[2]])
        self.assertEqual(row['bottom'], 48)
        self.assertEqual(row['cells'][2]['y'], 43)
        self.assertEqual(row['alignment'], 'center')
        self.assertEqual(response.context['seat_total'], 3)
        self.assertEqual(response.context['seat_available'], 3)
        self.assertContains(response, 'class="purchase-seat-gap"', count=1)

    def test_saved_direction_and_stage_are_rendered_on_shared_canvas(self):
        self.save_layout()
        response = self.page()
        self.assertEqual(response.context['map_stage'], 'bottom')
        self.assertEqual(response.context['map_direction'], 'ltr')
        self.assertContains(response, 'class="purchase-seat-canvas" dir="ltr"')
        html = response.content.decode()
        self.assertGreater(html.index('class="purchase-stage-row stage-bottom"'), html.index('data-seat-id="'))

    def test_unspecified_layout_centers_straight_rows_and_places_stage_first(self):
        response = self.page()
        row = response.context['map_data'][0]
        self.assertEqual([cell['number'] for cell in row['cells']], [1, 2, 3])
        self.assertEqual(row['alignment'], 'center')
        self.assertTrue(all(cell['y'] == cell['angle'] == 0 for cell in row['cells']))
        html = response.content.decode()
        self.assertLess(html.index('class="purchase-stage-row"'), html.index('data-seat-id="'))

    def test_offsets_negative_curvature_and_disabled_seats_survive_projection(self):
        self.save_layout(alignment='start', offset=2, curvature=-100)
        item = self.first.match_seats.get(seat=self.seats[0])
        item.is_enabled = False
        item.save(update_fields=['is_enabled'])
        response = self.page()
        row = response.context['map_data'][0]
        self.assertEqual(row['top'], 48)
        self.assertEqual(row['bottom'], 0)
        self.assertLess(row['cells'][2]['y'], 0)
        self.assertFalse(row['cells'][2]['is_available'])
        self.assertContains(response, '--row-offset:2;')
        self.assertEqual(response.context['seat_available'], 2)

    def test_saved_plan_does_not_resurrect_inactive_rows_or_missing_inventory(self):
        self.save_layout(seats=[1, None, 999, 2])
        inactive = Row.objects.create(block=self.block, number=2, is_active=False)
        Seat.objects.create(row=inactive, number=1)
        response = self.page()
        self.assertEqual(len(response.context['map_data']), 1)
        cells = response.context['map_data'][0]['cells']
        self.assertIsNone(cells[2])
        self.assertEqual([cell['number'] for cell in cells if cell], [1, 2, 3])
        self.assertEqual(response.context['seat_total'], 3)

    def test_geometry_does_not_modify_prices_or_inventory_data(self):
        rows = [{'row_number': 1, 'seats': [
            {'number': 1, 'id': 7, 'price': 0, 'is_available': False},
            {'number': 2, 'id': 8, 'price': 200000, 'is_available': True}]}]
        original = [dict(seat) for seat in rows[0]['seats']]
        mapped = purchase_rows(rows, {}, self.block.name)
        self.assertEqual(rows[0]['seats'], original)
        self.assertEqual(mapped[0]['cells'][0]['price'], 0)
        self.assertFalse(mapped[0]['cells'][0]['is_available'])
        self.assertEqual(mapped[0]['cells'][1]['price'], 200000)
