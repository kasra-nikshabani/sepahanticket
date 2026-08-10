# tickets/models.py
import base64
import qrcode
import random  # ← اصلاح
import string  # ← اصلاح
from io import BytesIO
from django.core.files import File
from django.db import models
from django.template.loader import render_to_string
from django.utils import timezone
from weasyprint import HTML
import tempfile
import os
from django.conf import settings

from accounts.models import User
from wallet.models import Transaction as WalletTransaction


# tickets/models.py
class Ticket(models.Model):
    TICKET_STATUS = (
        ('pending', 'در انتظار پرداخت'),
        ('paid', 'پرداخت شده'),
        ('cancelled', 'لغو شده'),
        ('admin_assigned', 'تخصیص توسط ادمین'),
        ('vip_issued', 'صادرشده توسط کاربر ویژه'),
    )
    order = models.ForeignKey(
        'Order',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='tickets',
        help_text='سفارش مربوط به این بلیط'
    )
    price = models.BigIntegerField(default=0, verbose_name="قیمت (ریال)")

    # ===== فیلدهای ارتباطی =====
    user = models.ForeignKey('accounts.User', on_delete=models.CASCADE, verbose_name="کاربر")
    match = models.ForeignKey('matches.Match', on_delete=models.CASCADE, verbose_name="مسابقه")
    seat = models.ForeignKey('matches.Seat', on_delete=models.CASCADE, verbose_name="صندلی")

    # فیلد جدید MatchSeat (با اجازه NULL برای بلیط‌های قدیمی)
    match_seat = models.ForeignKey(
        'matches.MatchSeat',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        verbose_name="صندلی مسابقه (وضعیت هر مسابقه)"
    )

    # ===== اطلاعات خریدار =====
    full_name = models.CharField(max_length=200, verbose_name="نام و نام خانوادگی")
    national_code = models.CharField(max_length=10, verbose_name="کد ملی")

    # ===== وضعیت و زمان =====
    status = models.CharField(max_length=20, choices=TICKET_STATUS, default='paid')
    purchase_date = models.DateTimeField(auto_now_add=True)

    # ===== فایل‌ها و شماره بلیط =====
    qr_code = models.ImageField(upload_to='qr_codes/', blank=True, null=True)
    pdf_file = models.FileField(upload_to='ticket_pdfs/', blank=True, null=True)
    ticket_number = models.CharField(max_length=20, unique=True, blank=True, null=True)

    # ===== تخصیص توسط ادمین =====
    is_admin_assigned = models.BooleanField(default=False, verbose_name="تخصیص توسط ادمین")

    is_used = models.BooleanField(default=False, verbose_name="استفاده شده")
    used_at = models.DateTimeField(null=True, blank=True, verbose_name="زمان استفاده")

    # ===== متدها =====
    def generate_ticket_number(self):
        import random
        import string
        return ''.join(random.choices(string.digits, k=12))

    @property
    def block_type_label(self):
        """پراپرتی برای دریافت نام فارسی نوع سکو برای استفاده در PDF و سایت"""
        if self.seat and self.seat.row and self.seat.row.block:
            block = self.seat.row.block
            if getattr(block, 'is_vip', False) or block.zone_type == 'vip':
                return "VIP"
            elif getattr(block, 'is_class1', False) or block.zone_type == 'class1':
                return "کلاس ۱"
            elif block.zone_type == 'women':
                return "بانوان"
            elif block.zone_type == 'home':
                return "میزبان"
            elif block.zone_type == 'away':
                return "میهمان"
        return "نامشخص"

    def generate_qr_code(self):
        import qrcode
        from io import BytesIO
        from django.core.files import File

        ticket_data = f"Ticket:{self.ticket_number}|Match:{self.match.id}|Seat:{self.seat.id}|User:{self.user.username}"
        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_L,
            box_size=15,
            border=4,
        )
        qr.add_data(ticket_data)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")

        buffer = BytesIO()
        img.save(buffer, format='PNG')
        buffer.seek(0)
        self.qr_code.save(f'ticket_{self.ticket_number}.png', File(buffer), save=False)

    def generate_pdf(self):
        import logging
        import base64
        import os
        import tempfile
        from django.template.loader import render_to_string
        from django.conf import settings
        from weasyprint import HTML
        from django.core.files import File

        logger = logging.getLogger(__name__)

        # ===== استفاده از پراپرتی جدید برای دریافت نام سکو =====
        team_type = self.block_type_label

        qr_image_base64 = None
        if self.qr_code:
            qr_path = self.qr_code.path
            logger.info(f"QR path: {qr_path}")
            if os.path.exists(qr_path):
                try:
                    with open(qr_path, 'rb') as image_file:
                        qr_image_base64 = base64.b64encode(image_file.read()).decode('utf-8')
                    logger.info("QR read successfully, length: %d", len(qr_image_base64))
                except Exception as e:
                    logger.error(f"Error reading QR: {e}")
            else:
                logger.warning(f"QR file not found: {qr_path}")
        else:
            logger.warning("qr_code field is empty")

        context = {
            'ticket': self,
            'match': self.match,
            'seat': self.seat,
            'team_type': team_type,  # <--- این متغیر به PDF فرستاده می‌شود
            'user': self.user,
            'qr_base64': qr_image_base64,
        }

        html_string = render_to_string('tickets/ticket_pdf.html', context)
        html = HTML(string=html_string, base_url=settings.BASE_DIR)

        with tempfile.NamedTemporaryFile(delete=False, suffix='.pdf') as tmp_file:
            html.write_pdf(tmp_file.name)
            tmp_file.seek(0)
            self.pdf_file.save(f'ticket_{self.ticket_number}.pdf', File(tmp_file), save=False)
            os.remove(tmp_file.name)

    def save(self, *args, **kwargs):
        import random
        import string

        # ===== ۱. تولید شماره بلیط =====
        if not self.ticket_number:
            self.ticket_number = self.generate_ticket_number()

        # ===== ۲. محاسبه قیمت از بلوک صندلی =====
        if not self.price and self.seat and self.seat.row and self.seat.row.block:
            self.price = self.seat.row.block.price or 0

        is_new = self.pk is None

        # ===== ۳. ذخیره اولیه =====
        super().save(*args, **kwargs)

        # ===== ۴. تولید QR (سریع -> همینجا، سینک) =====
        if is_new or not self.qr_code:
            self.generate_qr_code()
            super().save(update_fields=['qr_code'])

        # ===== ۵. تولید PDF (سنگین -> صف پس‌زمینه، بعد از commit شدن تراکنش) =====
        if is_new or not self.pdf_file:
            from django.db import transaction
            from .tasks import enqueue_pdf_generation
            transaction.on_commit(lambda ticket_id=self.pk: enqueue_pdf_generation(ticket_id))

    def mark_as_used(self):
        from django.utils import timezone
        self.is_used = True
        self.used_at = timezone.now()
        self.save(update_fields=['is_used', 'used_at'])

    def __str__(self):
        return f"بلیط {self.ticket_number} - {self.user.username}"

    class Meta:
        verbose_name = "بلیط"
        verbose_name_plural = "بلیط‌ها"


class VIPQuota(models.Model):
    """تخصیص ظرفیت صدور بلیط به کاربران ویژه برای هر مسابقه"""
    user = models.ForeignKey('accounts.User', on_delete=models.CASCADE, related_name='vip_quotas')
    match = models.ForeignKey('matches.Match', on_delete=models.CASCADE, related_name='vip_quotas')
    quota = models.IntegerField(verbose_name="ظرفیت مجاز")
    used = models.IntegerField(default=0, verbose_name="تعداد استفاده‌شده")

    class Meta:
        unique_together = ('user', 'match')
        verbose_name = "تخصیص ظرفیت"
        verbose_name_plural = "تخصیص ظرفیت‌ها"

    @property
    def remaining(self):
        return self.quota - self.used

    def __str__(self):
        return f"{self.user.username} - {self.match} - باقی‌مانده: {self.remaining}"


class DiscountCode(models.Model):
    code = models.CharField(max_length=20, unique=True, verbose_name="کد تخفیف")
    match = models.ForeignKey(
        'matches.Match',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        verbose_name="مسابقه",
        help_text="این کد تخفیف فقط برای این مسابقه معتبر است."
    )
    block = models.ForeignKey(
        'matches.Block',
        on_delete=models.CASCADE,
        null=True, blank=True,
        verbose_name="بلوک (اختیاری)"
    )
    discount_percent = models.IntegerField(verbose_name="درصد تخفیف")
    max_uses = models.IntegerField(default=1, verbose_name="حداکثر استفاده")
    used_count = models.IntegerField(default=0, verbose_name="تعداد استفاده شده")
    is_active = models.BooleanField(default=True, verbose_name="فعال")
    expires_at = models.DateTimeField(null=True, blank=True, verbose_name="تاریخ انقضا")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "کد تخفیف"
        verbose_name_plural = "کدهای تخفیف"

    def is_valid(self, match=None, block=None):
        from django.utils import timezone
        if not self.is_active:
            return False, "کد تخفیف غیرفعال است"
        if self.used_count >= self.max_uses:
            return False, "کد تخفیف به حداکثر استفاده رسیده است"
        if self.expires_at and self.expires_at < timezone.now():
            return False, "کد تخفیف منقضی شده است"
        if self.match and match and self.match != match:
            return False, "این کد تخفیف برای این مسابقه معتبر نیست"
        if self.block and block and self.block != block:
            return False, "این کد تخفیف برای این بلوک معتبر نیست"
        return True, "معتبر"


class Transaction(WalletTransaction):
    """
    Proxy Model برای نمایش تراکنش‌ها در بخش tickets
    """

    class Meta:
        proxy = True
        verbose_name = 'تراکنش'
        verbose_name_plural = 'تراکنش‌ها (Tickets)'


class Order(models.Model):
    """
    مدل ثبت سفارش/فاکتور برای هر خرید بلیط
    """
    PAYMENT_METHODS = (
        ('wallet', 'کیف پول'),
        ('zibal', 'درگاه زیبال'),
        ('mixed', 'ترکیبی (کیف پول + زیبال)'),
        ('vip', 'صدور بلیط ویژه'),
        ('admin', 'تخصیص ادمین'),
    )

    ORDER_STATUS = (
        ('pending', 'در انتظار پرداخت'),
        ('paid', 'پرداخت شده'),
        ('failed', 'ناموفق'),
        ('cancelled', 'لغو شده'),
    )

    # اطلاعات اصلی
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='orders')
    match = models.ForeignKey('matches.Match', on_delete=models.CASCADE, related_name='orders')
    order_number = models.CharField(max_length=50, unique=True, editable=False)

    # اطلاعات مالی
    subtotal = models.BigIntegerField(default=0, help_text='مبلغ کل قبل از تخفیف (ریال)')
    discount_percent = models.IntegerField(default=0, help_text='درصد تخفیف')
    discount_amount = models.BigIntegerField(default=0, help_text='مبلغ تخفیف (ریال)')
    total_amount = models.BigIntegerField(default=0, help_text='مبلغ نهایی (ریال)')

    # اطلاعات کیف پول
    wallet_amount = models.BigIntegerField(default=0, help_text='مبلغ پرداخت شده از کیف پول (ریال)')
    wallet_balance_before = models.BigIntegerField(default=0, help_text='موجودی کیف پول قبل از خرید')
    wallet_balance_after = models.BigIntegerField(default=0, help_text='موجودی کیف پول بعد از خرید')

    # اطلاعات پرداخت
    payment_method = models.CharField(max_length=20, choices=PAYMENT_METHODS, default='wallet')
    payment_status = models.CharField(max_length=20, choices=ORDER_STATUS, default='pending')
    track_id = models.CharField(max_length=100, blank=True, null=True, help_text='شناسه تراکنش درگاه')

    # اطلاعات تخفیف
    discount_code = models.CharField(max_length=50, blank=True, null=True, help_text='کد تخفیف استفاده شده')
    discount_code_id = models.IntegerField(blank=True, null=True, help_text='شناسه کد تخفیف')

    # اطلاعات خریدار
    full_name = models.CharField(max_length=200, blank=True, help_text='نام خریدار')
    phone_number = models.CharField(max_length=11, blank=True, help_text='شماره تلفن خریدار')

    # زمان‌ها
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    paid_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'سفارش'
        verbose_name_plural = 'سفارش‌ها'

    def save(self, *args, **kwargs):
        if not self.order_number:
            self.order_number = f"ORD-{timezone.now().strftime('%Y%m%d')}-{''.join(random.choices(string.ascii_uppercase + string.digits, k=6))}"
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.order_number} - {self.user.username} - {self.total_amount:,} ریال"

    @property
    def ticket_count(self):
        """تعداد بلیط‌های این سفارش"""
        return self.tickets.count()
