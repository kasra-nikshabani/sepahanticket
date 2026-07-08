from django.db import models
from django.conf import settings
from django.utils import timezone

class Wallet(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='wallet'
    )
    balance = models.DecimalField(
        max_digits=12,
        decimal_places=0,
        default=0,
        verbose_name="موجودی (تومان)"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"کیف پول {self.user.username} - {self.balance} تومان"

    def add_balance(self, amount, description="", reference_id=None):
        """افزایش موجودی و ثبت تراکنش"""
        if amount <= 0:
            return False
        self.balance += amount
        self.save()
        Transaction.objects.create(
            user=self.user,
            amount=amount,
            transaction_type='deposit',
            description=description or f"شارژ کیف پول به مبلغ {amount} تومان",
            reference_id=reference_id,
            balance_after=self.balance,
        )
        return True

    def deduct_balance(self, amount, description="", reference_id=None):
        """کسر از موجودی و ثبت تراکنش"""
        if amount <= 0:
            return False
        if self.balance < amount:
            return False
        self.balance -= amount
        self.save()
        Transaction.objects.create(
            user=self.user,
            amount=amount,
            transaction_type='withdraw',
            description=description or f"برداشت از کیف پول به مبلغ {amount} تومان",
            reference_id=reference_id,
            balance_after=self.balance,
        )
        return True


class Transaction(models.Model):
    TRANSACTION_TYPES = (
        ('deposit', 'شارژ'),
        ('withdraw', 'برداشت'),
        ('refund', 'بازگشت'),
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='transactions'
    )
    amount = models.DecimalField(max_digits=12, decimal_places=0, verbose_name="مبلغ")
    transaction_type = models.CharField(max_length=10, choices=TRANSACTION_TYPES, verbose_name="نوع تراکنش")
    description = models.CharField(max_length=255, verbose_name="توضیحات")
    reference_id = models.CharField(max_length=100, blank=True, null=True, verbose_name="شناسه مرجع")
    balance_after = models.DecimalField(max_digits=12, decimal_places=0, verbose_name="موجودی بعد از تراکنش")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = "تراکنش"
        verbose_name_plural = "تراکنش‌ها"

    def __str__(self):
        return f"{self.get_transaction_type_display()} - {self.amount} تومان - {self.user.username}"