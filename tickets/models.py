# tickets/models.py
import base64
import qrcode
from io import BytesIO
from django.core.files import File
from django.db import models
from django.template.loader import render_to_string
from weasyprint import HTML
import tempfile
import os
from django.conf import settings


class Ticket(models.Model):
    TICKET_STATUS = (
        ('pending', 'در انتظار پرداخت'),
        ('paid', 'پرداخت شده'),
        ('cancelled', 'لغو شده'),
        ('admin_assigned', 'تخصیص توسط ادمین'),
        ('vip_issued', 'صادرشده توسط کاربر ویژه'),
    )

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

    def generate_qr_code(self):
        ticket_data = f"Ticket:{self.ticket_number}|Match:{self.match.id}|Seat:{self.seat.id}|User:{self.user.username}"
        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_L,
            box_size=15,  # ← از ۱۰ به ۱۵ یا ۲۰ افزایش دهید
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
        """تولید فایل PDF با QR Code جاسازی‌شده به صورت Base64"""
        import logging
        logger = logging.getLogger(__name__)

        team_type = self.seat.row.zone_label

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
            'team_type': team_type,  # ← اینجا
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
        if not self.ticket_number:
            self.ticket_number = self.generate_ticket_number()

        is_new = self.pk is None

        # ذخیره اولیه برای دریافت id
        super().save(*args, **kwargs)

        # تولید QR و PDF فقط در صورت نیاز
        if is_new or not self.qr_code:
            self.generate_qr_code()
            super().save(update_fields=['qr_code'])

        if is_new or not self.pdf_file:
            self.generate_pdf()
            super().save(update_fields=['pdf_file'])

    def mark_as_used(self):
        from django.utils import timezone
        self.is_used = True
        self.used_at = timezone.now()
        self.save(update_fields=['is_used', 'used_at'])

    def __str__(self):
        return f"بلیط {self.ticket_number} - {self.user.username}"


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
    block = models.ForeignKey(
        'matches.Block',
        on_delete=models.CASCADE,
        null=True, blank=True,
        verbose_name="بلوک (خالی = همه بلوک‌ها)"
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

    def is_valid(self, block=None):
        from django.utils import timezone
        if not self.is_active:
            return False, "کد تخفیف غیرفعال است"
        if self.used_count >= self.max_uses:
            return False, "کد تخفیف به حداکثر استفاده رسیده است"
        if self.expires_at and self.expires_at < timezone.now():
            return False, "کد تخفیف منقضی شده است"
        if self.block and block and self.block != block:
            return False, "این کد تخفیف برای این بلوک معتبر نیست"
        return True, "معتبر"

    def __str__(self):
        block_name = self.block.name if self.block else "همه بلوک‌ها"
        return f"{self.code} - {self.discount_percent}% - {block_name}"