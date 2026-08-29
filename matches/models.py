from datetime import timedelta

from django.db import models
from django.db.models import Sum
from django.utils import timezone


# BLOCK_TYPES = (
#         ('home', 'میزبان'),
#         ('away', 'مهمان'),
#         ('class1', 'کلاس ۱'),
#         ('vip', 'VIP'),
#         ('women', 'بانوان میزبان'),
#     )
class MatchCost(models.Model):
    """هزینه‌های هر مسابقه"""
    match = models.ForeignKey('Match', on_delete=models.CASCADE, related_name='costs')
    description = models.CharField(max_length=255, verbose_name="توضیح هزینه")
    amount = models.BigIntegerField(verbose_name="مبلغ (ریال)")  # ← به ریال
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = "هزینه مسابقه"
        verbose_name_plural = "هزینه‌های مسابقه"

    def __str__(self):
        return f"{self.match} - {self.description} - {self.amount:,} ریال"


class MatchRevenue(models.Model):
    """درآمدهای اضافی هر مسابقه (غیر از فروش بلیط)"""
    match = models.ForeignKey('Match', on_delete=models.CASCADE, related_name='revenues')
    description = models.CharField(max_length=255, verbose_name="توضیح درآمد")
    amount = models.BigIntegerField(verbose_name="مبلغ (ریال)")  # ← به ریال
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = "درآمد اضافی مسابقه"
        verbose_name_plural = "درآمدهای اضافی مسابقه"

    def __str__(self):
        return f"{self.match} - {self.description} - {self.amount:,} ریال"


class MatchFinancialReport(models.Model):
    """گزارش مالی نهایی هر مسابقه"""
    match = models.OneToOneField('Match', on_delete=models.CASCADE, related_name='financial_report')
    total_ticket_revenue = models.BigIntegerField(default=0, verbose_name="درآمد فروش بلیط")
    total_ticket_sold = models.IntegerField(default=0, verbose_name="تعداد بلیط فروخته شده")
    total_vip_tickets = models.IntegerField(default=0, verbose_name="تعداد بلیط ویژه")
    total_used_tickets = models.IntegerField(default=0, verbose_name="تعداد بلیط استفاده شده")
    total_wallet_usage = models.BigIntegerField(default=0, verbose_name="مبلغ استفاده شده از کیف پول")  # ← اضافه شد
    total_costs = models.BigIntegerField(default=0, verbose_name="مجموع هزینه‌ها")
    total_revenues = models.BigIntegerField(default=0, verbose_name="مجموع درآمدهای اضافی")
    net_profit = models.BigIntegerField(default=0, verbose_name="سود خالص")
    generated_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "گزارش مالی مسابقه"
        verbose_name_plural = "گزارش‌های مالی مسابقات"

    def __str__(self):
        return f"گزارش مالی {self.match}"

    # matches/models.py
    def calculate(self):
        """محاسبه گزارش مالی"""
        from tickets.models import Ticket, Order
        from matches.models import MatchCost, MatchRevenue
        from django.db.models import Sum

        # ===== ۱. درآمد فروش بلیط =====
        tickets = Ticket.objects.filter(match=self.match, status='paid')
        total_ticket_revenue = sum(t.price for t in tickets if t.price) or 0

        # ===== ۲. مصرف از کیف پول =====
        # مقدار مصرف کیف پول مستقیماً از روی سفارش‌ها (Order.wallet_amount) خوانده
        # می‌شود که منبع درست و قطعی است. روش قبلی سعی می‌کرد با یافتن یک
        # تراکنش کیف پول با reference_id برابر ticket_number حدس بزند، اما
        # تراکنش‌های کیف پول همیشه با reference_id برابر order_number یا
        # PAY-{payment.id} ثبت می‌شوند (نه ticket_number) و برای کل سفارش یک
        # تراکنش واحد است، نه یکی به‌ازای هر بلیط -- پس آن روش هیچ‌وقت درست
        # تطبیق پیدا نمی‌کرد و برای خریدهای ترکیبی (بخشی از درگاه + بخشی از
        # کیف پول) هم کل قیمت بلیط را به‌جای سهم واقعی کیف پول حساب می‌کرد.
        # جمع زدن روی order_id های distinct لازم است چون یک سفارش می‌تواند
        # چند بلیط داشته باشد و نباید wallet_amount آن سفارش چند بار جمع زده شود.
        order_ids = tickets.exclude(order__isnull=True).values_list('order_id', flat=True).distinct()
        total_wallet_usage = Order.objects.filter(
            id__in=order_ids, payment_status='paid'
        ).aggregate(total=Sum('wallet_amount'))['total'] or 0

        # ===== ۳. تعداد بلیط فروخته شده =====
        total_ticket_sold = tickets.count()

        # ===== ۴. بلیط‌های VIP =====
        total_vip_tickets = Ticket.objects.filter(
            match=self.match,
            status__in=['admin_assigned', 'vip_issued']
        ).count()

        # ===== ۵. بلیط‌های استفاده شده =====
        total_used_tickets = Ticket.objects.filter(
            match=self.match,
            is_used=True
        ).count()

        # ===== ۶. هزینه‌ها =====
        total_costs = MatchCost.objects.filter(match=self.match).aggregate(total=Sum('amount'))['total'] or 0

        # ===== ۷. درآمدهای اضافی =====
        total_revenues = MatchRevenue.objects.filter(match=self.match).aggregate(total=Sum('amount'))['total'] or 0

        # ===== ۸. سود خالص =====
        net_profit = total_ticket_revenue + total_revenues - total_costs

        # ذخیره در مدل
        self.total_ticket_revenue = total_ticket_revenue
        self.total_ticket_sold = total_ticket_sold
        self.total_vip_tickets = total_vip_tickets
        self.total_used_tickets = total_used_tickets
        self.total_wallet_usage = total_wallet_usage
        self.total_costs = total_costs
        self.total_revenues = total_revenues
        self.net_profit = net_profit
        self.save()

        return self


class Stadium(models.Model):
    name = models.CharField(max_length=100, verbose_name="نام ورزشگاه")
    capacity = models.IntegerField(verbose_name="ظرفیت کل")
    image = models.ImageField(
        upload_to='stadium_images/',
        null=True,
        blank=True,
        verbose_name="تصویر ورزشگاه"
    )

    def __str__(self): return self.name


# ===== انتخاب‌های نوع جایگاه =====
ZONE_CHOICES = (
    ('home', 'میزبان'),
    ('away', 'میهمان'),
    ('class1', 'کلاس ۱'),
    ('women', 'بانوان'),
    # جایگاه بانوانِ هوادار تیم میهمان. عمداً یک نوع جداست (نه ترکیب
    # «بانوان»+«میهمان»)، چون در این مدل هر سکو فقط یک نوع جایگاه دارد و
    # گیت هم بلیط را با همین یک مقدار کنترل می‌کند.
    ('women_away', 'بانوان میهمان'),
    ('vip', 'VIP'),
)

# جایگاه‌هایی که متعلق به تیم میهمان‌اند -- در انتخاب سکو، خریدارِ «میهمان»
# فقط این‌ها را می‌بیند و خریدارِ «میزبان» هیچ‌کدام را نمی‌بیند.
AWAY_ZONE_TYPES = ('away', 'women_away')


# ============================================================
#  مدل Block
# ============================================================
class Block(models.Model):
    FLOOR_CHOICES = (
        ('ground', 'طبقه پایین'),
        ('second', 'طبقه دوم'),
    )
    stadium = models.ForeignKey(
        'Stadium',
        on_delete=models.CASCADE,
        related_name='blocks',
        null=True,
        blank=True,
        verbose_name="ورزشگاه"
    )
    name = models.CharField(max_length=50, verbose_name="نام سکو")
    order = models.IntegerField(default=0, verbose_name="ترتیب")
    floor = models.CharField(max_length=10, choices=FLOOR_CHOICES, default='ground', verbose_name="طبقه")
    is_vip = models.BooleanField(default=False, verbose_name="VIP")
    is_class1 = models.BooleanField(default=False, verbose_name="کلاس ۱")
    is_active = models.BooleanField(default=True, verbose_name="فعال")
    price = models.DecimalField(
        max_digits=10,
        decimal_places=0,
        default=50000,
        verbose_name="قیمت (ریال)"
    )
    zone_type = models.CharField(
        max_length=10,
        choices=ZONE_CHOICES,  # ← از ZONE_CHOICES استفاده می‌کند
        default='home',
        verbose_name="نوع جایگاه"
    )

    class Meta:
        unique_together = ('stadium', 'name',)
        ordering = ['order']
        verbose_name = "بلوک"
        verbose_name_plural = "بلوک‌ها"

    def __str__(self):
        return f"{self.name} ({self.get_zone_type_display()})"


class Row(models.Model):
    block = models.ForeignKey(Block, on_delete=models.CASCADE, related_name='rows')
    number = models.IntegerField()
    is_active = models.BooleanField(default=True)

    class Meta:
        unique_together = ('block', 'number')
        ordering = ['block__order', 'number']

    @property
    def zone_label(self):
        # اولویت با VIP
        if self.block.is_vip:
            return "VIP"
        # سپس کلاس ۱
        if self.block.is_class1:
            return "کلاس ۱"
        # در غیر این صورت از zone_type استفاده کن
        labels = {
            'home': 'میزبان',
            'away': 'میهمان',
            'women': 'بانوان میزبان',
            'women_away': 'بانوان میهمان',
        }
        return labels.get(self.block.zone_type, 'میزبان')

    @property
    def is_home(self):
        away_block_ids = [2, 3, 4, 5]
        return self.block.id not in away_block_ids

    @property
    def name(self):
        return f"{self.block.name} - ردیف {self.number}"

    @property
    def zone_type(self):
        return self.block.zone_type

    def __str__(self):
        return self.name


class Seat(models.Model):
    row = models.ForeignKey(Row, on_delete=models.CASCADE, verbose_name="ردیف", related_name='seats')
    number = models.IntegerField(verbose_name="شماره صندلی")
    is_available = models.BooleanField(default=True, verbose_name="موجود")

    class Meta:
        unique_together = ('row', 'number')
        verbose_name = "صندلی"
        verbose_name_plural = "صندلی‌ها"

    def __str__(self):
        return f"{self.row.name} - صندلی {self.number}"


class Match(models.Model):
    home_team = models.CharField(max_length=100, verbose_name="تیم میزبان")
    away_team = models.CharField(max_length=100, verbose_name="تیم میهمان")
    home_team_logo = models.ImageField(upload_to='team_logos/', blank=True, null=True)
    away_team_logo = models.ImageField(upload_to='team_logos/', blank=True, null=True)
    stadium = models.ForeignKey(Stadium, on_delete=models.CASCADE)
    date_time = models.DateTimeField(verbose_name="تاریخ و ساعت برگزاری")
    is_active = models.BooleanField(default=True)
    ticket_sales_enabled = models.BooleanField(default=True, verbose_name="فروش بلیط فعال")
    is_cancelled = models.BooleanField(default=False, verbose_name="لغو شده")
    cancelled_at = models.DateTimeField(null=True, blank=True, verbose_name="زمان لغو")
    created_by = models.ForeignKey('accounts.User', on_delete=models.SET_NULL, null=True)
    sold_tickets = models.IntegerField(default=0, verbose_name="تعداد بلیط‌های فروخته‌شده")
    # ===== انتخاب‌های رشته ورزشی =====
    SPORT_CHOICES = (
        ('football', 'فوتبال'),
        ('volleyball', 'والیبال'),
        ('handball', 'هندبال'),
        ('basketball', 'بسکتبال'),
        ('futsal', 'فوتسال'),
        ('other', 'سایر'),
    )
    sport_type = models.CharField(
        max_length=20,
        choices=SPORT_CHOICES,
        default='football',
        verbose_name="رشته ورزشی"
    )

    @property
    def status(self):
        """وضعیت مسابقه"""
        now = timezone.now()
        if self.date_time > now:
            return 'upcoming'
        elif self.date_time <= now and self.date_time + timedelta(hours=2) > now:
            return 'live'
        else:
            return 'finished'

    def __str__(self):
        return f"{self.home_team} vs {self.away_team} - {self.date_time}"


class MatchBlockPrice(models.Model):
    """
    قیمت اختصاصی یک بلوک برای یک مسابقهٔ خاص. اگر برای جفت (مسابقه، بلوک)
    رکوردی اینجا نباشد، قیمت پیش‌فرض همان Block.price استفاده می‌شود که بین
    همهٔ مسابقات آن ورزشگاه مشترک است.
    """
    match = models.ForeignKey(Match, on_delete=models.CASCADE, related_name='block_price_overrides')
    block = models.ForeignKey(Block, on_delete=models.CASCADE, related_name='match_price_overrides')
    price = models.DecimalField(max_digits=10, decimal_places=0, verbose_name="قیمت (ریال)")

    class Meta:
        unique_together = ('match', 'block')
        verbose_name = "قیمت اختصاصی بلوک برای مسابقه"
        verbose_name_plural = "قیمت‌های اختصاصی بلوک برای مسابقات"

    def __str__(self):
        return f"{self.match} - {self.block.name}: {self.price}"


def get_block_price_map(match):
    """قیمت هر بلوک برای این مسابقه: {block_id: price} -- قیمت اختصاصی مسابقه
    در صورت وجود، در غیر این صورت Block.price. یک کوئری برای همهٔ بلوک‌های
    آن ورزشگاه + یک کوئری برای override های همین مسابقه (بدون N+1)."""
    prices = {
        block_id: price
        for block_id, price in Block.objects.filter(stadium=match.stadium_id).values_list('id', 'price')
    }
    overrides = MatchBlockPrice.objects.filter(match=match).values_list('block_id', 'price')
    prices.update(dict(overrides))
    return prices


def get_block_price_for_match(match, block):
    """قیمت یک بلوک مشخص برای یک مسابقهٔ مشخص (قیمت اختصاصی در صورت وجود)."""
    override = MatchBlockPrice.objects.filter(match=match, block=block).values_list('price', flat=True).first()
    return override if override is not None else block.price


class MatchBasaDiscount(models.Model):
    """درصد تخفیف اعضای باسا برای یک مسابقهٔ خاص. اگر برای مسابقه‌ای رکوردی
    اینجا نباشد یعنی تخفیف باسا برای آن مسابقه فعال نیست."""
    match = models.OneToOneField(Match, on_delete=models.CASCADE, related_name='basa_discount')
    discount_percent = models.PositiveSmallIntegerField(verbose_name="درصد تخفیف باسا")

    class Meta:
        verbose_name = "تخفیف باسا برای مسابقه"
        verbose_name_plural = "تخفیف‌های باسا برای مسابقات"

    def __str__(self):
        return f"{self.match} - {self.discount_percent}٪ باسا"


def get_basa_discount_percent(match):
    """درصد تخفیف باسای این مسابقه، یا صفر اگر برای این مسابقه تعیین نشده باشد."""
    return MatchBasaDiscount.objects.filter(match=match).values_list('discount_percent', flat=True).first() or 0


# ============================================================
#  فعال/غیرفعال بودنِ اختصاصیِ هر مسابقه (بلوک / ردیف / صندلی)
# ============================================================
# مسئله: Block.is_active و Row.is_active و Seat.is_available روی خودِ
# بلوک/ردیف/صندلی ذخیره می‌شن، و اون‌ها متعلق به «ورزشگاه»ن نه «مسابقه».
# پس هر تغییری بین همه‌ی مسابقاتِ اون ورزشگاه مشترک بود -- اگر بلوکی برای
# یک مسابقه غیرفعال می‌شد، برای بقیه‌ی مسابقات هم غیرفعال می‌شد.
#
# راه‌حل: دقیقاً همون الگوی MatchBlockPrice -- یک جدول override به‌ازای
# (مسابقه، بلوک/ردیف). اگر رکوردی نباشه، مقدار پیش‌فرضِ گلوبال استفاده
# می‌شه؛ برای همین این تغییر کاملاً backward-compatible است و تا وقتی
# ادمین عمداً برای یک مسابقه چیزی رو تغییر نده، هیچ رفتاری عوض نمی‌شود.
#
# برای صندلی، جدول جدا نساختیم چون MatchSeat از قبل دقیقاً همون جدولِ
# «وضعیت هر صندلی در هر مسابقه» است -- فقط یک فیلد is_enabled به آن اضافه
# شده (جدا از is_available که معنی «فروخته/رزرو نشده» می‌دهد).

class MatchBlockActive(models.Model):
    """فعال/غیرفعال بودن یک بلوک فقط برای یک مسابقهٔ خاص. نبودِ رکورد یعنی
    از Block.is_active پیش‌فرض پیروی کن."""
    match = models.ForeignKey(Match, on_delete=models.CASCADE, related_name='block_active_overrides')
    block = models.ForeignKey(Block, on_delete=models.CASCADE, related_name='match_active_overrides')
    is_active = models.BooleanField(verbose_name="فعال")

    class Meta:
        unique_together = ('match', 'block')
        verbose_name = "وضعیت اختصاصی بلوک برای مسابقه"
        verbose_name_plural = "وضعیت‌های اختصاصی بلوک برای مسابقات"

    def __str__(self):
        return f"{self.match} - {self.block.name}: {'فعال' if self.is_active else 'غیرفعال'}"


class MatchRowActive(models.Model):
    """فعال/غیرفعال بودن یک ردیف فقط برای یک مسابقهٔ خاص. نبودِ رکورد یعنی
    از Row.is_active پیش‌فرض پیروی کن."""
    match = models.ForeignKey(Match, on_delete=models.CASCADE, related_name='row_active_overrides')
    row = models.ForeignKey(Row, on_delete=models.CASCADE, related_name='match_active_overrides')
    is_active = models.BooleanField(verbose_name="فعال")

    class Meta:
        unique_together = ('match', 'row')
        verbose_name = "وضعیت اختصاصی ردیف برای مسابقه"
        verbose_name_plural = "وضعیت‌های اختصاصی ردیف برای مسابقات"

    def __str__(self):
        return f"{self.match} - {self.row}: {'فعال' if self.is_active else 'غیرفعال'}"


class MatchBlockZone(models.Model):
    """نوع جایگاه (میزبان/میهمان/بانوان/کلاس۱/VIP) یک بلوک فقط برای یک
    مسابقهٔ خاص. نبودِ رکورد یعنی از zone_type/is_vip/is_class1 پیش‌فرضِ
    خود بلوک پیروی کن.

    کاربرد واقعی: سهمیه‌ی تیم میهمان معمولاً از مسابقه‌ای به مسابقه‌ی دیگر
    فرق می‌کند؛ قبلاً چون zone_type روی خود بلوک بود، تغییرش برای یک بازی
    روی همه‌ی بازی‌های آن ورزشگاه اثر می‌گذاشت."""
    match = models.ForeignKey(Match, on_delete=models.CASCADE, related_name='block_zone_overrides')
    block = models.ForeignKey(Block, on_delete=models.CASCADE, related_name='match_zone_overrides')
    zone_type = models.CharField(max_length=10, choices=ZONE_CHOICES, verbose_name="نوع جایگاه")

    class Meta:
        unique_together = ('match', 'block')
        verbose_name = "نوع جایگاه اختصاصی بلوک برای مسابقه"
        verbose_name_plural = "نوع جایگاه‌های اختصاصی بلوک برای مسابقات"

    def __str__(self):
        return f"{self.match} - {self.block.name}: {self.get_zone_type_display()}"


def get_block_zone_map(match):
    """{block_id: zone_type} -- نوع جایگاه مؤثرِ هر بلوک برای این مسابقه.

    نکته: is_vip/is_class1 روی خود بلوک اولویت دارند (همان ترتیبی که
    Ticket.block_type_label و gate API استفاده می‌کنند)، مگر اینکه برای این
    مسابقه override تعریف شده باشد که در آن صورت override برنده است."""
    state = {}
    for bid, ztype, is_vip, is_class1 in Block.objects.filter(
        stadium=match.stadium_id
    ).values_list('id', 'zone_type', 'is_vip', 'is_class1'):
        if is_vip:
            state[bid] = 'vip'
        elif is_class1:
            state[bid] = 'class1'
        else:
            state[bid] = ztype
    state.update(dict(
        MatchBlockZone.objects.filter(match=match).values_list('block_id', 'zone_type')
    ))
    return state


def get_block_zone_for_match(match, block):
    """نوع جایگاه یک بلوک برای یک مسابقهٔ مشخص."""
    override = MatchBlockZone.objects.filter(
        match=match, block=block
    ).values_list('zone_type', flat=True).first()
    if override is not None:
        return override
    if block.is_vip:
        return 'vip'
    if block.is_class1:
        return 'class1'
    return block.zone_type


def get_block_ids_by_zone(match, zone_type):
    """شناسه‌ی بلوک‌هایی که برای این مسابقه از این نوع جایگاه‌اند."""
    return [bid for bid, z in get_block_zone_map(match).items() if z == zone_type]


def get_block_active_map(match):
    """{block_id: bool} -- وضعیت مؤثرِ فعال/غیرفعالِ هر بلوکِ ورزشگاهِ این
    مسابقه (override اختصاصی در صورت وجود، وگرنه Block.is_active)."""
    state = dict(
        Block.objects.filter(stadium=match.stadium_id).values_list('id', 'is_active')
    )
    state.update(dict(
        MatchBlockActive.objects.filter(match=match).values_list('block_id', 'is_active')
    ))
    return state


def get_active_block_ids(match):
    """شناسه‌ی بلوک‌هایی که برای این مسابقهٔ خاص فعال‌اند."""
    return [bid for bid, active in get_block_active_map(match).items() if active]


def get_row_active_map(match, block=None):
    """{row_id: bool} -- وضعیت مؤثرِ هر ردیف برای این مسابقه (اختیاری: فقط
    ردیف‌های یک بلوک)."""
    rows = Row.objects.filter(block__stadium=match.stadium_id)
    overrides = MatchRowActive.objects.filter(match=match)
    if block is not None:
        rows = rows.filter(block=block)
        overrides = overrides.filter(row__block=block)
    state = dict(rows.values_list('id', 'is_active'))
    state.update(dict(overrides.values_list('row_id', 'is_active')))
    return state


def get_active_row_ids(match, block=None):
    """شناسه‌ی ردیف‌هایی که برای این مسابقهٔ خاص فعال‌اند."""
    return [rid for rid, active in get_row_active_map(match, block).items() if active]


def find_new_orphan_seats(match, selected_match_seat_ids):
    """صندلی‌هایی که اگر انتخابِ داده‌شده نهایی شود، «تکی» جا می‌مانند.

    مسئله: وقتی چند نفر کنار هم می‌خرند، ممکن است وسط یا کنارشان دقیقاً یک
    صندلی خالی بماند. آن صندلی عملاً دیگر فروش نمی‌رود (کسی تنها نمی‌نشیند و
    به گروه‌ها هم نمی‌خورد) -- روی یک مسابقه‌ی واقعی ۷۵ صندلی این‌طور از
    دست رفته بود.

    قاعده: فقط تکی‌هایی که همین انتخاب *ایجاد* می‌کند مهم‌اند. اگر صندلی
    تکی از قبل خالی مانده باشد، خریدش کاملاً آزاد است (چون دارد مشکل را حل
    می‌کند، نه ایجاد).

    مجاورت بر اساس ترتیب صندلی‌های *موجود* در همان ردیف حساب می‌شود، نه
    تفاضل عددی شماره‌ها -- چون ممکن است بعضی شماره‌ها اصلاً صندلی نداشته
    باشند و همسایه‌ی فیزیکی، صندلی بعدیِ موجود باشد.

    خروجی: لیستی از MatchSeat هایی که تکی می‌شوند (خالی یعنی مشکلی نیست).
    """
    selected = set(selected_match_seat_ids)
    if not selected:
        return []

    rows_of_interest = set(
        MatchSeat.objects.filter(id__in=selected).values_list('seat__row_id', flat=True)
    )
    if not rows_of_interest:
        return []

    active_block_ids = set(get_active_block_ids(match))
    active_row_ids = set(get_active_row_ids(match))

    seats_by_row = {}
    for ms in (
        MatchSeat.objects.filter(match=match, seat__row_id__in=rows_of_interest)
        .select_related('seat__row')
        .order_by('seat__row_id', 'seat__number')
    ):
        seats_by_row.setdefault(ms.seat.row_id, []).append(ms)

    def sellable(ms):
        """آیا این صندلی الان برای فروش در دسترس است (یعنی «خالی» حساب می‌شود)."""
        return (
            ms.is_available
            and ms.is_enabled
            and ms.seat.is_available
            and ms.seat.row_id in active_row_ids
            and ms.seat.row.block_id in active_block_ids
        )

    def orphan_ids(free_flags, seats):
        """شناسه‌ی صندلی‌هایی که در یک دنباله‌ی خالیِ به‌طول دقیقاً ۱ هستند."""
        out = set()
        run = []
        for ms, is_free in zip(seats, free_flags):
            if is_free:
                run.append(ms)
            else:
                if len(run) == 1:
                    out.add(run[0].id)
                run = []
        if len(run) == 1:
            out.add(run[0].id)
        return out

    new_orphans = []
    for row_id, seats in seats_by_row.items():
        before = [sellable(ms) for ms in seats]
        after = [sellable(ms) and ms.id not in selected for ms in seats]
        created = orphan_ids(after, seats) - orphan_ids(before, seats)
        if created:
            by_id = {ms.id: ms for ms in seats}
            new_orphans.extend(by_id[i] for i in created)

    return new_orphans


def is_block_active_for_match(match, block):
    """آیا این بلوک برای این مسابقهٔ خاص فعال است؟"""
    override = MatchBlockActive.objects.filter(
        match=match, block=block
    ).values_list('is_active', flat=True).first()
    return block.is_active if override is None else override


def is_row_active_for_match(match, row):
    """آیا این ردیف برای این مسابقهٔ خاص فعال است؟"""
    override = MatchRowActive.objects.filter(
        match=match, row=row
    ).values_list('is_active', flat=True).first()
    return row.is_active if override is None else override


class MatchSeat(models.Model):
    """وضعیت یک صندلی برای یک مسابقه خاص"""
    match = models.ForeignKey(Match, on_delete=models.CASCADE, related_name='match_seats')
    seat = models.ForeignKey(Seat, on_delete=models.CASCADE, related_name='match_seats')
    is_available = models.BooleanField(default=True, verbose_name="موجود")
    # ===== «آیا ادمین این صندلی را برای همین مسابقه فعال گذاشته؟» -- کاملاً
    # جدا از is_available که معنی «فروخته/رزرو نشده» می‌دهد. یک صندلی وقتی
    # برای خرید قابل انتخاب است که هم is_enabled باشد و هم is_available.
    # بدون این فیلد، غیرفعال‌کردن یک صندلی مجبور بود روی Seat.is_available
    # (که بین همه‌ی مسابقات مشترک است) نوشته شود و به بقیه‌ی مسابقات سرایت
    # می‌کرد. =====
    is_enabled = models.BooleanField(default=True, verbose_name="فعال برای این مسابقه")
    reserved_until = models.DateTimeField(null=True, blank=True)

    @classmethod
    def get_or_create_for_match_seat(cls, match, seat):
        obj, created = cls.objects.get_or_create(match=match, seat=seat, defaults={'is_available': True})
        return obj

    @classmethod
    def ensure_for_match(cls, match, block=None, batch_size=2000):
        """
        پیش‌ساخت تمام MatchSeatهای یک مسابقه (یا یک بلوک).
        قبل از شروع فروش اجرا شود تا get_or_create در مسیر خرید نباشد.

        فیلترِ فعال‌بودن بلوک/ردیف مخصوصِ همین مسابقه است (نه گلوبال).
        """
        seat_qs = Seat.objects.filter(
            row__block__stadium=match.stadium,
            row__block_id__in=get_active_block_ids(match),
            row_id__in=get_active_row_ids(match),
        )
        if block is not None:
            seat_qs = seat_qs.filter(row__block=block)

        existing = set(
            cls.objects.filter(match=match, seat_id__in=seat_qs.values_list('id', flat=True))
            .values_list('seat_id', flat=True)
        )
        to_create = [
            cls(match=match, seat_id=sid, is_available=True)
            for sid in seat_qs.values_list('id', flat=True)
            if sid not in existing
        ]
        created = 0
        for i in range(0, len(to_create), batch_size):
            batch = to_create[i:i + batch_size]
            cls.objects.bulk_create(batch, ignore_conflicts=True)
            created += len(batch)
        return created

    class Meta:
        unique_together = ('match', 'seat')
        verbose_name = "صندلی مسابقه"
        verbose_name_plural = "صندلی‌های مسابقه"

    def __str__(self):
        return f"{self.match} - {self.seat}"
