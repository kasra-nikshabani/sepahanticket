"""تست‌های نقشه‌ی ورزشگاه.

هندسه‌ی نقشه از روی شماره‌ی بلوک ساخته می‌شود، پس یک اشتباه کوچک در
محاسبه یعنی نقشه‌ی قشنگی که تماشاگر را به ضلع اشتباه می‌فرستد. این
تست‌ها همان چیزی را قفل می‌کنند که با نقشه‌ی رسمی باشگاه تطبیق داده شد.
"""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from .models import Block, Match, Stadium
from .stadium_map import (ANCHOR_DEG, ANCHOR_INDEX, RING, SLOT_DEG,
                          ZONE_COLORS, block_slot_key, build_map)

User = get_user_model()


def angle_of(key):
    return (ANCHOR_DEG + (RING.index(key) - ANCHOR_INDEX) * SLOT_DEG) % 360


def side_of(deg):
    """در دستگاه SVG: ۰=راست، ۹۰=پایین، ۱۸۰=چپ، ۲۷۰=بالا."""
    if 45 <= deg < 135:
        return 'south'
    if 135 <= deg < 225:
        return 'west'
    if 225 <= deg < 315:
        return 'north'
    return 'east'


class RingGeometryTests(TestCase):
    """چیدمان باید با نقشه‌ی رسمی بخواند."""

    def test_anchor_blocks_sit_on_the_right_sides(self):
        self.assertEqual(side_of(angle_of('n9')), 'west')
        self.assertEqual(side_of(angle_of('n19')), 'north')
        self.assertEqual(side_of(angle_of('n28')), 'east')
        self.assertEqual(side_of(angle_of('vip2')), 'south')
        self.assertEqual(side_of(angle_of('class1')), 'south')

    def test_numbers_run_clockwise(self):
        """در دستگاه SVG، ساعت‌گرد یعنی زاویه زیاد می‌شود."""
        # ۶ عمداً نیست (تونل)، پس از فهرست کنار گذاشته می‌شود
        seq = [angle_of(f'n{i}') for i in range(2, 34) if i != 6]
        unwrapped = [seq[0]]
        for a in seq[1:]:
            prev = unwrapped[-1]
            while a < prev:
                a += 360
            unwrapped.append(a)
        self.assertEqual(unwrapped, sorted(unwrapped))

    def test_missing_blocks_keep_their_slot(self):
        """بلوک ۱ و ۶ در سیستم نیستند ولی خانه‌شان باید رزرو بماند.

        اگر رزرو نمی‌شد، همه‌ی بلوک‌های بعدی یک خانه جابه‌جا می‌شدند و
        تماشاگر به ضلع اشتباه راهنمایی می‌شد.
        """
        self.assertIsNone(RING[0])                      # جای بلوک ۱
        self.assertIsNone(RING[RING.index('n5') + 1])   # جای بلوک ۶
        self.assertEqual(len(RING), 40)

    def test_block_names_map_to_slots(self):
        class B:
            def __init__(self, name):
                self.name = name
        self.assertEqual(block_slot_key(B('بلوک ۱۴')), 'n14')
        self.assertEqual(block_slot_key(B('بلوک ۹ (طبقه دوم)')), 'n9')
        self.assertEqual(block_slot_key(B('بلوک کلاس ۱ (۲)')), 'class2')
        self.assertEqual(block_slot_key(B('بلوک VIP3')), 'vip3')
        self.assertEqual(block_slot_key(B('بلوک VIP1 (طبقه دوم)')), 'vip1')

    def test_every_zone_declares_a_gender(self):
        """جنسیت مهم‌ترین چیزی است که کاربر نباید اشتباه بگیرد؛
        هیچ جایگاهی نباید بی‌برچسب بماند."""
        for key, z in ZONE_COLORS.items():
            self.assertIn(z['gender']['key'], ('men', 'women'), key)
        self.assertEqual(ZONE_COLORS['women']['gender']['key'], 'women')
        self.assertEqual(ZONE_COLORS['women_away']['gender']['key'], 'women')
        self.assertEqual(ZONE_COLORS['home']['gender']['key'], 'men')
        self.assertEqual(ZONE_COLORS['class1']['gender']['key'], 'men')


class MapBuildTests(TestCase):
    def setUp(self):
        self.stadium = Stadium.objects.create(name='نقش جهان', capacity=75000)
        self.blocks = [
            Block.objects.create(stadium=self.stadium, name=f'بلوک {n}',
                                 order=n, floor='ground', price=1000000)
            for n in (2, 9, 19, 28)
        ]

    def test_each_block_gets_a_path_and_a_pop_vector(self):
        pieces = build_map(self.blocks)
        self.assertEqual(len(pieces), 4)
        for p in pieces:
            self.assertTrue(p['path'].startswith('M '))
            self.assertIn('A ', p['path'])
            # بردار بیرون‌آمدن با هاور نباید صفر باشد، وگرنه حرکتی دیده نمی‌شود
            self.assertNotEqual((p['pop_x'], p['pop_y']), (0, 0))

    def test_unknown_blocks_are_skipped_not_misplaced(self):
        Block.objects.create(stadium=self.stadium, name='سکوی آزمایشی',
                             order=99, floor='ground', price=0)
        pieces = build_map(list(Block.objects.filter(stadium=self.stadium)))
        self.assertEqual(len(pieces), 4)

    def test_occupancy_is_derived_from_seat_stats(self):
        b = self.blocks[0]
        pieces = build_map([b], seat_stats={b.id: (25, 100)})
        self.assertEqual(pieces[0]['occupancy'], 75)
        self.assertFalse(pieces[0]['sold_out'])

        pieces = build_map([b], seat_stats={b.id: (0, 100)})
        self.assertTrue(pieces[0]['sold_out'])


class SelectBlockPageTests(TestCase):
    """صفحه‌ی انتخاب بلوک -- به‌ویژه تعویض طبقه."""

    def setUp(self):
        from accounts.models import SiteSettings
        s = SiteSettings.get_solo()
        s.block_foreign_ips = False
        s.save()
        self.user = User.objects.create_user(username='fan', password='pw12345')
        self.stadium = Stadium.objects.create(name='نقش جهان', capacity=75000)
        for floor in ('ground', 'second'):
            for n in (9, 19, 28):
                Block.objects.create(stadium=self.stadium, order=n, floor=floor,
                                     price=1000000, zone_type='home',
                                     name=f'بلوک {n}' + (' (طبقه دوم)' if floor == 'second' else ''))
        self.match = Match.objects.create(
            home_team='سپاهان', away_team='حریف', stadium=self.stadium,
            date_time=timezone.now() + timedelta(days=3))
        self.client.force_login(self.user)

    def _page(self):
        return self.client.get(f'/matches/select-block/{self.match.id}/', follow=True)

    def test_both_floors_are_rendered_so_switching_needs_no_reload(self):
        resp = self._page()
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()
        self.assertIn('data-floor="ground"', body)
        self.assertIn('data-floor="second"', body)

    def test_svg_layers_hide_with_a_class_not_the_hidden_attribute(self):
        """`hidden` روی SVG کار نمی‌کند.

        hidden فقط روی HTMLElement تعریف شده؛ روی <g> نه به‌صورت خودکار
        مخفی می‌کند و -- مهم‌تر -- `g.hidden = true` در جاوااسکریپت اصلاً
        به DOM نمی‌رسد و بی‌صدا بی‌اثر می‌ماند. یک بار همین باعث شد تعویض
        طبقه اصلاً کار نکند.
        """
        body = self._page().content.decode()
        self.assertNotIn('class="floor-layer" data-floor="second" hidden', body)
        self.assertIn('floor-layer', body)
        self.assertIn('.floor-layer.off', body)
        self.assertIn("classList.toggle('off'", body)

    def test_the_old_boxes_and_stadium_photo_are_gone(self):
        body = self._page().content.decode()
        for gone in ('block-card', 'stadium-image', 'lightbox'):
            self.assertNotIn(gone, body)

    def test_no_script_targets_an_element_that_does_not_exist(self):
        """ارجاع به عنصرِ حذف‌شده، کلِ اسکریپت صفحه را متوقف می‌کند."""
        import re
        body = self._page().content.decode()
        ids = set(re.findall(r'id="([A-Za-z][\w-]*)"', body))
        used = set(re.findall(r"getElementById\('([^']+)'\)", body))
        # آنچه در قالب پایه است و داخل شرط صدا زده می‌شود، از این بررسی خارج
        allowed = {'sidebarToggle', 'sidebarBackdrop'}
        self.assertEqual(sorted(used - ids - allowed), [])
