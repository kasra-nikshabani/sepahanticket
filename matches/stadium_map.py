"""نقشه‌ی کلیک‌شدنی ورزشگاه نقش جهان -- ساخت هندسه از روی شماره‌ی بلوک.

چرا ساختنی است، نه کشیدنی
--------------------------
بلوک‌ها دور کاسه‌ی ورزشگاه پشت سر هم شماره‌گذاری شده‌اند، پس لازم نیست کسی
هفتاد شکل را دستی روی نقشه بکشد و نگه‌دارد؛ جای هر بلوک از روی شماره‌اش
حساب می‌شود. اگر روزی بلوکی اضافه یا کم شود، نقشه خودش را می‌سازد.

هندسه از روی نقشه‌ی رسمی باشگاه درآمده:

* شماره‌ها **ساعت‌گرد** می‌روند.
* بلوک ۹ در ضلع غربی (چپِ تصویر)، بلوک ۱۹ در ضلع شمالی (بالا)، بلوک ۲۸ در
  ضلع شرقی (راست) و جایگاه‌های VIP و کلاس ۱ در ضلع جنوبی (پایین) هستند.
* بلوک‌های ۱ و ۶ در سیستم تعریف نشده‌اند و روی نقشه‌ی رسمی هم جای آن‌ها
  ورودی/تونل است. جایشان در حلقه **رزرو** می‌ماند و خالی رسم می‌شود --
  اگر رزرو نمی‌شد، همه‌ی بلوک‌های بعدی یک خانه جابه‌جا می‌شدند و تماشاگر
  به ضلع اشتباه راهنمایی می‌شد.
"""
import math
import re

# ترتیب ساعت‌گردِ خانه‌های حلقه. هر عضو یک «کلید» است که به بلوک وصل می‌شود؛
# None یعنی خانه‌ای که در سیستم بلوکی ندارد (ورودی/تونل) و خالی می‌ماند.
RING = (
    [None]                                   # جای بلوک ۱ (بین VIP1 و بلوک ۲)
    + [f'n{i}' for i in range(2, 6)]         # ۲ تا ۵
    + [None]                                 # جای بلوک ۶ -- تونل
    + [f'n{i}' for i in range(7, 34)]        # ۷ تا ۳۳
    + ['class3', 'class2', 'class1']         # کلاس ۱، از راست به چپ
    + [None]                                 # VIP4 روی نقشه هست ولی در سیستم نه
    + ['vip3', 'vip2', 'vip1']
)

SLOT_COUNT = len(RING)                       # ۴۰ خانه
SLOT_DEG = 360.0 / SLOT_COUNT                # ۹ درجه

# لنگرِ زاویه: بلوک ۹ باید بیفتد روی ضلع غربی (۱۸۰ درجه در دستگاه SVG که
# در آن ۰=راست، ۹۰=پایین، ۱۸۰=چپ، ۲۷۰=بالا و افزایشِ زاویه ساعت‌گرد است).
ANCHOR_INDEX = RING.index('n9')
ANCHOR_DEG = 180.0

# فاصله‌ی بین دو بلوک، تا مرزها دیده شوند.
GAP_DEG = 1.4

ZONE_COLORS = {
    'home':       {'fill': '#D4AF37', 'label': 'میزبان'},
    'away':       {'fill': '#c0392b', 'label': 'میهمان'},
    'women':      {'fill': '#b5379b', 'label': 'بانوان میزبان'},
    'women_away': {'fill': '#7d3c98', 'label': 'بانوان میهمان'},
    'class1':     {'fill': '#17a2b8', 'label': 'کلاس ۱'},
    'vip':        {'fill': '#8e6b13', 'label': 'VIP'},
}
DEFAULT_COLOR = {'fill': '#8a8a9a', 'label': 'نامشخص'}

_FA_DIGITS = str.maketrans('۰۱۲۳۴۵۶۷۸۹', '0123456789')


def block_slot_key(block):
    """کلیدِ خانه‌ی حلقه را از روی نام بلوک درمی‌آورد.

    نام‌ها الگوی ثابتی دارند («بلوک ۱۴»، «بلوک کلاس ۱ (۲)»، «بلوک VIP3»)
    و پسوند «(طبقه دوم)» فقط طبقه را می‌گوید، نه جای بلوک را -- هر دو طبقه
    روی هم قرار دارند و ترتیبشان یکی است.
    """
    name = (block.name or '').replace('(طبقه دوم)', '').strip()

    m = re.search(r'VIP\s*([0-9۰-۹]+)', name, re.IGNORECASE)
    if m:
        return 'vip' + m.group(1).translate(_FA_DIGITS)

    if 'کلاس' in name:
        m = re.search(r'\(\s*([0-9۰-۹]+)\s*\)', name)
        if m:
            return 'class' + m.group(1).translate(_FA_DIGITS)
        return None

    m = re.search(r'بلوک\s*([0-9۰-۹]+)', name)
    if m:
        return 'n' + m.group(1).translate(_FA_DIGITS)
    return None


def _point(cx, cy, rx, ry, deg):
    a = math.radians(deg)
    return cx + rx * math.cos(a), cy + ry * math.sin(a)


def _wedge_path(cx, cy, rx_out, ry_out, rx_in, ry_in, deg_from, deg_to):
    """یک قاچ از حلقه‌ی بیضی، به‌شکل مسیر SVG."""
    x1, y1 = _point(cx, cy, rx_out, ry_out, deg_from)
    x2, y2 = _point(cx, cy, rx_out, ry_out, deg_to)
    x3, y3 = _point(cx, cy, rx_in, ry_in, deg_to)
    x4, y4 = _point(cx, cy, rx_in, ry_in, deg_from)
    return (f'M {x1:.2f} {y1:.2f} '
            f'A {rx_out:.2f} {ry_out:.2f} 0 0 1 {x2:.2f} {y2:.2f} '
            f'L {x3:.2f} {y3:.2f} '
            f'A {rx_in:.2f} {ry_in:.2f} 0 0 0 {x4:.2f} {y4:.2f} Z')


def build_map(blocks, zone_map=None, seat_stats=None,
              cx=500.0, cy=340.0,
              rx_out=470.0, ry_out=310.0, rx_in=330.0, ry_in=185.0):
    """هندسه‌ی نقشه را برای مجموعه‌ای از بلوک‌ها می‌سازد.

    blocks     -- بلوک‌های همان طبقه‌ای که کاربر انتخاب کرده
    zone_map   -- {block_id: zone} مخصوص همین مسابقه (نه zone_type گلوبال)
    seat_stats -- {block_id: (خالی, کل)} برای رنگ‌آمیزی بر اساس ظرفیت

    خروجی: فهرستی از dict که تمپلیت مستقیم رسمشان می‌کند.
    """
    zone_map = zone_map or {}
    seat_stats = seat_stats or {}
    by_key = {}
    for b in blocks:
        key = block_slot_key(b)
        if key:
            by_key[key] = b

    out = []
    for index, key in enumerate(RING):
        block = by_key.get(key) if key else None
        if block is None:
            continue

        center = ANCHOR_DEG + (index - ANCHOR_INDEX) * SLOT_DEG
        deg_from = center - (SLOT_DEG - GAP_DEG) / 2
        deg_to = center + (SLOT_DEG - GAP_DEG) / 2

        zone = zone_map.get(block.id)
        color = ZONE_COLORS.get(zone, DEFAULT_COLOR)
        free, total = seat_stats.get(block.id, (None, None))

        # برچسب روی خودِ قاچ: وسط حلقه، تا هم روی رنگ خوانا باشد هم جا بگیرد.
        lx, ly = _point(cx, cy, (rx_out + rx_in) / 2, (ry_out + ry_in) / 2, center)

        out.append({
            'block': block,
            'path': _wedge_path(cx, cy, rx_out, ry_out, rx_in, ry_in, deg_from, deg_to),
            'fill': color['fill'],
            'zone': zone,
            'zone_label': color['label'],
            'free': free,
            'total': total,
            'sold_out': (free == 0) if free is not None else False,
            'label': _short_label(block),
            'label_x': round(lx, 1),
            'label_y': round(ly, 1),
            'label_rotate': round(center + 90, 1),
        })
    return out


def _short_label(block):
    """روی قاچ فقط شماره می‌نشیند؛ «بلوک» و «(طبقه دوم)» جا نمی‌شوند."""
    name = (block.name or '').replace('(طبقه دوم)', '').strip()
    m = re.search(r'بلوک\s*([0-9۰-۹]+)$', name)
    if m:
        return m.group(1)
    if 'کلاس' in name:
        m = re.search(r'\(\s*([0-9۰-۹]+)\s*\)', name)
        return 'کلاس ' + (m.group(1) if m else '')
    m = re.search(r'VIP\s*([0-9۰-۹]+)', name, re.IGNORECASE)
    if m:
        return 'VIP' + m.group(1)
    return name
