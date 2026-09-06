import random
import string
from django.db import models
from django.conf import settings


class Payment(models.Model):
    """
    رکورد هر تراکنشی که قراره از درگاه زیبال بگذره (شارژ کیف پول یا باقی‌مانده‌ی خرید بلیط).

    نکته‌ی کلیدی: verify هیچ‌وقت از سشن جنگو چیزی نمی‌خونه؛ فقط با track_id
    (که زیبال همیشه توی querystring برمی‌گردونه، مستقل از کوکی/سشن) همین رکورد
    رو پیدا می‌کنه و از روی خودش (نه سشن) عملیات رو انجام می‌ده.
    """

    PURPOSE_CHOICES = (
        ('wallet_charge', 'شارژ کیف پول'),
        ('ticket_purchase', 'پرداخت باقی‌مانده‌ی خرید بلیط'),
    )
    STATUS_CHOICES = (
        ('pending', 'در انتظار بازگشت از درگاه'),
        ('success', 'موفق'),
        ('failed', 'ناموفق'),
    )

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='payments')
    purpose = models.CharField(max_length=20, choices=PURPOSE_CHOICES)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')

    # ===== شناسه‌های درگاه =====
    track_id = models.CharField(max_length=100, unique=True, null=True, blank=True, db_index=True)
    gateway_amount = models.BigIntegerField(default=0, help_text='مبلغی که به درگاه فرستاده شده (ریال)')

    # ===== فقط برای purpose == ticket_purchase =====
    match = models.ForeignKey('matches.Match', null=True, blank=True, on_delete=models.SET_NULL)
    # {"<match_seat_id>": {"full_name": "...", "national_code": "..."}}
    buyer_info = models.JSONField(default=dict, blank=True)
    seat_ids = models.JSONField(default=list, blank=True)  # لیست match_seat_id ها، برای رول‌بک آسون
    discount_code = models.CharField(max_length=50, blank=True)
    discount_percent = models.IntegerField(default=0)
    subtotal = models.BigIntegerField(default=0, help_text='قیمت کل قبل از تخفیف (ریال)')
    discount_amount = models.BigIntegerField(default=0, help_text='مبلغ تخفیف (ریال)')
    wallet_amount_used = models.BigIntegerField(default=0, help_text='مبلغی که قراره از کیف پول کسر بشه (ریال)')

    order = models.OneToOneField(
        'tickets.Order', null=True, blank=True, on_delete=models.SET_NULL, related_name='payment'
    )

    next_url = models.CharField(max_length=255, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    processed_at = models.DateTimeField(null=True, blank=True)

    # ===== چرا status برای «آیا پول گرفته شد؟» کافی نیست =====
    # status سرنوشتِ *سفارش* را می‌گوید، نه سرنوشتِ *پول* را. سه حالت واقعی
    # وجود دارد که status نمی‌تواند از هم جدا کند:
    #   ۱) کاربر پرداخت کرد و برنگشت -> برای همیشه 'pending' می‌ماند، در حالی
    #      که پول در زیبال گرفته شده. (دو کاربر در بازی ۶۶ دقیقاً همین شدند.)
    #   ۲) پول گرفته شد ولی صدور بلیط شکست خورد -> 'failed' می‌شود، عیناً شبیه
    #      کسی که اصلاً پرداخت نکرده.
    #   ۳) کاربر واقعاً پرداخت نکرد -> 'pending' یا 'failed'.
    # هر گزارشی که «پول گرفته‌شده» را با status='success' حساب می‌کرد، حالت‌های
    # ۱ و ۲ را نمی‌دید -- و همین باعث شد بدهیِ دربی ساعت‌ها پنهان بماند.
    # این فیلد فقط و فقط یک چیز می‌گوید: زیبال تأیید کرده که پول گرفته شده.
    gateway_captured_at = models.DateTimeField(
        null=True, blank=True, db_index=True,
        help_text='لحظه‌ای که زیبال تأیید کرد پول از کاربر گرفته شده -- مستقل از اینکه بلیط صادر شد یا نه',
    )

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'پرداخت'
        verbose_name_plural = 'پرداخت‌ها'

    def __str__(self):
        return f"Payment#{self.id} - {self.get_purpose_display()} - {self.get_status_display()} - {self.gateway_amount:,} ریال"