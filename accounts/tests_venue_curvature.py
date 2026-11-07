from types import SimpleNamespace
from django.test import TestCase
from django.urls import reverse
from accounts.venue_layout import curve_point, curve_padding
from accounts.program_seating import map_rows
from accounts import tests_programs as fixtures


class VenueCurvatureTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        fixtures.OrganizerProgramTests.setUpTestData.__func__(cls)

    def test_curve_geometry_is_symmetric_and_single_seat_is_straight(self):
        self.assertEqual(curve_point(100, 0, 5)['y'], 0)
        self.assertEqual(curve_point(100, 2, 5)['y'], 48)
        self.assertEqual(curve_point(-100, 2, 5)['y'], -48)
        self.assertEqual(curve_point(100, 1, 5)['y'], curve_point(100, 3, 5)['y'])
        self.assertEqual(curve_point(100, 0, 1), {'y': 0, 'angle': 0})
        self.assertEqual(curve_padding(-100, 5), {'top': 48, 'bottom': 0})
        self.assertEqual(curve_point(0, 2, 5), {'y': 0, 'angle': 0})

    def test_paginated_seats_keep_their_original_curve_positions(self):
        # Seat 3 stays at the center of a five-position row, even on a partial page.
        row = {'number': 1, 'seats': [1, 2, 3, None, 4], 'curvature': 100}
        item = SimpleNamespace(seat=self.seats[2])
        mapped = map_rows([item], {'rows': [row]})
        self.assertEqual(item.curve_y, 48)
        self.assertEqual(item.curve_angle, 0)
        self.assertEqual(mapped[0]['curve_bottom'], 48)

    def test_program_map_uses_saved_admin_hall_geometry(self):
        self.venue.seating_layout = {'stage': 'bottom', 'direction': 'rtl', 'sections': [
            {'name': self.block.name, 'rows': [{'number': 1, 'alignment': 'center', 'curvature': -100,
                                               'seats': list(range(1, 9))}]}]}
        self.venue.save()
        self.client.force_login(self.owner)
        response = self.client.get(reverse('accounts:program_session', args=[self.proposal.pk, self.first.pk]))
        row = response.context['seat_map']['rows'][0]
        self.assertEqual(row['curve_top'], 48)
        self.assertEqual(row['cells'][0].curve_y, 0)
        self.assertLess(row['cells'][3].curve_y, -40)
        self.assertEqual(response.context['seat_map']['stage'], 'bottom')
        self.assertContains(response, 'padding-top:48px')
        self.assertEqual(response.context['stats']['revenue'], 1200000)
