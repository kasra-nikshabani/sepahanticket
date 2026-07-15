import transaction
from django.db import models
from django.conf import settings
from django.utils import timezone


class Wallet(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='wallet'
    )
    balance = models.BigIntegerField(default=0, verbose_name="موجودی (ریال)")  # ← به ریال
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"کیف پول {self.user.username} - {self.balance:,} ریال"

    def add_balance(self, amount, description="", reference_id=None):
        """
        افزایش موجودی و ثبت تراکنش
        amount: مبلغ به ریال
        """
        if amount <= 0:
            return False

        # ===== افزایش موجودی (به ریال) =====
        self.balance += amount
        self.save()

        # ===== ثبت تراکنش =====
        tx = Transaction.objects.create(
            user=self.user,
            amount=amount,  # به ریال
            transaction_type='deposit',
            description=description or f"شارژ کیف پول به مبلغ {amount:,} ریال",
            reference_id=reference_id,
            balance_after=self.balance,
            is_wallet=True,
        )

        print(f"✅ Transaction created: {tx.id} - {tx.transaction_type} - Amount: {amount} ریال")
        return True

    # wallet/models.py
    def deduct_balance(self, amount, description="", reference_id=None, tx_type='withdraw'):
        """
        کسر از موجودی و ثبت تراکنش
        amount: مبلغ به ریال
        """
        print(f"🔍 deduct_balance called")
        print(f"🔍 amount: {amount} ریال")
        print(f"🔍 current balance: {self.balance} ریال")

        # ===== بررسی مقدار =====
        if amount <= 0:
            print(f"❌ amount <= 0")
            raise ValueError("مبلغ باید بزرگتر از صفر باشد")

        if self.balance < amount:
            print(f"❌ balance insufficient: {self.balance} < {amount}")
            raise ValueError(f"موجودی کیف پول ({self.balance:,} ریال) کافی نیست")

        # ===== کسر از موجودی =====
        self.balance -= amount
        self.save()

        print(f"✅ balance after deduction: {self.balance}")

        # ===== ثبت تراکنش =====
        tx = Transaction.objects.create(
            user=self.user,
            amount=amount,
            transaction_type=tx_type,
            description=description or f"برداشت از کیف پول به مبلغ {amount:,} ریال",
            reference_id=reference_id,
            balance_after=self.balance,
            is_wallet=True,
        )

        print(f"✅ Transaction created: {tx.id}")
        print(f"✅ Transaction type: {tx.transaction_type}")
        print(f"✅ Amount: {tx.amount}")

        return True


class Transaction(models.Model):
    TRANSACTION_TYPES = (
        ('deposit', 'شارژ'),
        ('withdraw', 'برداشت'),
        ('refund', 'بازگشت'),
        ('ticket_purchase', 'خرید بلیط'),  # ← اضافه کنید

    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='transactions'
    )
    amount = models.DecimalField(max_digits=12, decimal_places=0, verbose_name="مبلغ")
    transaction_type = models.CharField(max_length=20, choices=TRANSACTION_TYPES, verbose_name="نوع تراکنش")
    description = models.CharField(max_length=255, verbose_name="توضیحات")
    reference_id = models.CharField(max_length=100, blank=True, null=True, verbose_name="شناسه مرجع")
    balance_after = models.DecimalField(max_digits=12, decimal_places=0, verbose_name="موجودی بعد از تراکنش")
    created_at = models.DateTimeField(auto_now_add=True)
    is_wallet = models.BooleanField(
        default=True,
        verbose_name="تراکنش کیف پول",
        help_text="آیا این تراکنش مستقیماً به کیف پول مربوط می‌شود؟"
    )

    class Meta:
        ordering = ['-created_at']
        verbose_name = "تراکنش"
        verbose_name_plural = "تراکنش‌ها"

    def __str__(self):
        return f"{self.get_transaction_type_display()} - {self.amount} تومان - {self.user.username}"
