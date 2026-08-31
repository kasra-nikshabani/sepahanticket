# wallet/models.py
from django.db import models, transaction
from django.db.models import F
from django.contrib.auth import get_user_model

User = get_user_model()

# پیامی که همه‌جا -- شارژ، خرید بلیط، درگاه -- به کاربر نشان داده می‌شود تا
# دلیلِ کار نکردن کیف پول یکسان و روشن باشد.
WALLET_DISABLED_MESSAGE = (
    'کیف پول در حال حاضر توسط مدیریت غیرفعال شده است؛ '
    'امکان شارژ یا پرداخت از کیف پول وجود ندارد.'
)


def is_wallet_enabled():
    """
    آیا کیف پول برای استفاده (شارژ و پرداخت) فعال است؟

    تک‌منبعِ حقیقت برای همه‌ی مسیرها -- ویوی شارژ، درگاه پرداخت و خرید بلیط --
    تا اگر ادمین کیف پول را خاموش کند هیچ راه فرعی‌ای باز نماند.
    توجه: این فقط جلوی *استفاده* را می‌گیرد، نه واریزهای برگشتی؛ بازگشت وجه
    باید حتی در حالت غیرفعال هم انجام شود وگرنه پول واقعیِ کاربر گم می‌شود.
    """
    from accounts.models import SiteSettings
    return SiteSettings.get_solo().wallet_enabled


class Wallet(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='wallet')
    balance = models.BigIntegerField(default=0)  # به ریال
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"کیف پول {self.user.username} - {self.balance:,} ریال"

    def deduct_balance(self, amount, description="", reference_id="", tx_type="ticket_purchase"):
        """
        کسر از کیف پول با ثبت تراکنش.

        با یک UPDATE شرطی در سطح دیتابیس (نه خواندن self.balance در پایتون و
        نوشتن دوباره) انجام می‌شود تا در برابر دو درخواست همزمان (مثلاً دو تب یا
        دو دستگاه) امن باشد؛ در غیر این صورت هر دو می‌توانستند همان موجودی
        قدیمی را ببینند و هر دو کسر را با موفقیت انجام دهند.
        """
        if amount <= 0:
            return False

        with transaction.atomic():
            updated = Wallet.objects.filter(pk=self.pk, balance__gte=amount).update(
                balance=F('balance') - amount
            )
            if not updated:
                return False

            self.refresh_from_db(fields=['balance'])

            Transaction.objects.create(
                user=self.user,
                amount=-amount,
                transaction_type=tx_type,
                description=description,
                reference_id=reference_id,
                balance_after=self.balance,
                is_wallet=True,
            )
        return True

    def add_balance(self, amount, description="", reference_id="", tx_type="deposit"):
        """افزایش atomic موجودی کیف پول (همان دلیل deduct_balance) با ثبت تراکنش"""
        if amount <= 0:
            return False

        with transaction.atomic():
            Wallet.objects.filter(pk=self.pk).update(balance=F('balance') + amount)
            self.refresh_from_db(fields=['balance'])

            Transaction.objects.create(
                user=self.user,
                amount=amount,
                transaction_type=tx_type,
                description=description,
                reference_id=reference_id,
                balance_after=self.balance,
                is_wallet=True,
            )
        return True


# ===== مدل Transaction را اضافه کنید =====
class Transaction(models.Model):
    TRANSACTION_TYPES = [
        ('deposit', 'شارژ'),
        ('withdraw', 'برداشت'),
        ('ticket_purchase', 'خرید بلیط'),
        ('refund', 'بازگشت وجه'),
    ]
    reference_id = models.CharField(max_length=100, blank=True, null=True)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='transactions')
    amount = models.BigIntegerField()  # به ریال (مثبت برای شارژ، منفی برای برداشت)
    transaction_type = models.CharField(max_length=20, choices=TRANSACTION_TYPES)
    description = models.TextField(blank=True)
    reference_id = models.CharField(max_length=100, blank=True)
    balance_after = models.BigIntegerField()  # موجودی بعد از تراکنش
    is_wallet = models.BooleanField(default=True)  # برای تشخیص تراکنش‌های کیف پول
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.get_transaction_type_display()} - {self.user.username} - {self.amount:,} ریال"