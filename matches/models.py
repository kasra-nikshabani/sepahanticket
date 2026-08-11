from datetime import timedelta

from django.db import models
from django.db.models import Sum
from django.utils import timezone


# BLOCK_TYPES = (
#         ('home', 'میزبان'),
#         ('away', 'مهمان'),
#         ('class1', 'کلاس ۱'),
#         ('vip', 'VIP'),
#         ('women', 'بانوان'),
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
    ('vip', 'VIP'),
)


# ============================================================
#  مدل Block
# ============================================================
class Block(models.Model):
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
            'women': 'بانوان',
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


class MatchSeat(models.Model):
    """وضعیت یک صندلی برای یک مسابقه خاص"""
    match = models.ForeignKey(Match, on_delete=models.CASCADE, related_name='match_seats')
    seat = models.ForeignKey(Seat, on_delete=models.CASCADE, related_name='match_seats')
    is_available = models.BooleanField(default=True, verbose_name="موجود")
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
        """
        seat_qs = Seat.objects.filter(
            row__block__stadium=match.stadium,
            row__block__is_active=True,
            row__is_active=True,
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
