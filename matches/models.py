from django.db import models
from django.utils import timezone


# BLOCK_TYPES = (
#         ('home', 'میزبان'),
#         ('away', 'مهمان'),
#         ('class1', 'کلاس ۱'),
#         ('vip', 'VIP'),
#         ('women', 'بانوان'),
#     )

class Stadium(models.Model):
    name = models.CharField(max_length=100, verbose_name="نام ورزشگاه")
    capacity = models.IntegerField(verbose_name="ظرفیت کل")

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
        verbose_name="قیمت (تومان)"
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
    created_by = models.ForeignKey('accounts.User', on_delete=models.SET_NULL, null=True)
    total_capacity = models.IntegerField(default=0, verbose_name="ظرفیت کل")
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
    def available_capacity(self):
        """ظرفیت باقی‌مانده"""
        return self.total_capacity - self.sold_tickets

    @property
    def occupancy_percent(self):
        """درصد اشغال"""
        if self.total_capacity == 0:
            return 0
        return round((self.sold_tickets / self.total_capacity) * 100, 1)

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

    class Meta:
        unique_together = ('match', 'seat')
        verbose_name = "صندلی مسابقه"
        verbose_name_plural = "صندلی‌های مسابقه"

    def __str__(self):
        return f"{self.match} - {self.seat}"
