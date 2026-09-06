# wallet/models.py
from django.db import models, transaction
from django.db.models import F, Q, Sum
from django.contrib.auth import get_user_model
from django.utils import timezone

User = get_user_model()

# پیامی که همه‌جا -- شارژ، خرید بلیط، درگاه -- به کاربر نشان داده می‌شود تا
# دلیلِ کار نکردن کیف پول یکسان و روشن باشد.
WALLET_DISABLED_MESSAGE = (
    'کیف پول در حال حاضر توسط مدیریت غیرفعال شده است؛ '
    'امکان شارژ یا پرداخت از کیف پول وجود ندارد.'
)


def is_wallet_enabled():
    """
    آیا *خرج کردن* موجودی کیف پول مجاز است؟ (پرداخت بخشی از هزینه‌ی بلیط)

    تک‌منبعِ حقیقت برای مسیرهای پرداخت، تا اگر ادمین کیف پول را خاموش کند
    هیچ راه فرعی‌ای باز نماند.
    توجه: این فقط جلوی *استفاده* را می‌گیرد، نه واریزهای برگشتی؛ بازگشت وجه
    باید حتی در حالت غیرفعال هم انجام شود وگرنه پول واقعیِ کاربر گم می‌شود.
    """
    from accounts.models import SiteSettings
    return SiteSettings.get_solo().wallet_enabled


def is_wallet_charge_enabled():
    """آیا کاربر می‌تواند کیف پولش را *شارژ* کند؟

    از is_wallet_enabled جداست چون این دو تصمیم مستقل‌اند: ممکن است بخواهیم
    موجودیِ موجود خرج شود ولی پول تازه‌ای وارد کیف پول نشود. شارژ علاوه بر
    کلید خودش، به روشن بودن کیف پول هم نیاز دارد -- وقتی کیف پول کلاً خاموش
    است، شارژ کردنش بی‌معنی است.
    """
    from accounts.models import SiteSettings
    s = SiteSettings.get_solo()
    return s.wallet_enabled and s.wallet_charge_enabled


WALLET_CHARGE_DISABLED_MESSAGE = (
    'شارژ کیف پول در حال حاضر غیرفعال است. موجودی فعلی شما همچنان برای '
    'خرید بلیط قابل استفاده است.'
)


def is_withdrawal_enabled():
    """آیا کاربر می‌تواند درخواست *برداشت* پول ثبت کند؟

    عمداً به is_wallet_enabled وابسته نیست: اگر روزی کیف پول برای خرید بسته
    شود، پولِ مردم نباید همان لحظه بی‌راه خروج بماند.
    """
    from accounts.models import SiteSettings
    return SiteSettings.get_solo().withdrawal_enabled


WITHDRAWAL_DISABLED_MESSAGE = (
    'برداشت وجه در حال حاضر غیرفعال است. موجودی شما محفوظ است و همچنان '
    'برای خرید بلیط قابل استفاده است.'
)


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


# ============================================================
#  برداشت وجه از کیف پول
# ============================================================
# چرا این بخش وجود دارد
# ---------------------
# بعد از دربی، پولِ ۴۰۰+ کاربری که بلیط نگرفته بودند به کیف پولشان برگشت.
# تا قبل از این، تنها راهِ خارج شدن آن پول «خرید بلیط بعدی» بود -- یعنی
# کسی که دیگر نمی‌خواست بلیط بخرد، پولش عملاً پیش باشگاه گیر می‌کرد. این
# مدل همان راه خروج است.
#
# دو تصمیمِ کلیدی که این پیاده‌سازی را شکل داده‌اند:
#
# ۱) واریز *دستی* انجام می‌شود، نه خودکار. سیستم فقط درخواست را می‌گیرد،
#    موجودی را نگه می‌دارد و صف بررسی می‌سازد؛ خزانه‌دار با اینترنت‌بانک
#    (پایا) واریز می‌کند و شماره پیگیری را ثبت می‌کند. نقطه‌ی اتصال به API
#    تسویه‌ی خودکار عمداً در همین مسیر (approve → mark_paid) باز گذاشته شده
#    تا هر وقت قرارداد تسویه گرفته شد، فقط همان یک مرحله جایگزین شود.
#
# ۲) فقط پولی قابل برداشت است که *باشگاه به کاربر برگردانده* -- جبران
#    دربی، بازگشت وجه، پرداخت دوباره. پولی که خودِ کاربر از درگاه شارژ
#    کرده قابل برداشت نیست. دلیلش امنیتی است: در غیر این صورت می‌شد با
#    کارتِ الف شارژ کرد و به حسابِ ب برداشت کرد، یعنی سایت تبدیل به کانال
#    انتقال پول می‌شد.

MIN_WITHDRAWAL_AMOUNT = 100_000  # ریال (۱۰ هزار تومان)

# پیشوند reference_id همه‌ی مسیرهایی که پول را از سمت باشگاه به کیف پول
# کاربر برگردانده‌اند. عمداً با COMPENSATION_PREFIXES در دستور
# audit_payment_ticket_balance یکی است -- هر دو یک سؤال را می‌پرسند:
# «کدام بخش از این موجودی، پولِ خودِ کاربر بوده که باشگاه نگه داشته؟»
WITHDRAWABLE_PREFIXES = ('compensate-', 'SHORTFALL-', 'OVERPAY-', 'refund-')

_DIGIT_MAP = str.maketrans('۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩', '01234567890123456789')


def normalize_iban(raw):
    """ورودی کاربر را به شکل استاندارد «IR + ۲۴ رقم» درمی‌آورد.

    کاربر شبا را از هر جایی کپی می‌کند: با فاصله، با خط تیره، با ارقام
    فارسی، با یا بدون IR. همه‌ی این‌ها معتبرند و نباید به‌خاطر شکل ظاهری رد
    شوند.
    """
    if not raw:
        return ''
    s = str(raw).translate(_DIGIT_MAP)
    s = ''.join(ch for ch in s if ch.isalnum()).upper()
    if s.startswith('IR'):
        s = s[2:]
    return f'IR{s}' if s else ''


def is_valid_iban(iban):
    """اعتبارسنجی رقم کنترلی شبا (استاندارد IBAN، mod-97).

    این فقط می‌گوید «چنین شماره‌ای می‌تواند وجود داشته باشد»؛ نمی‌گوید حساب
    مالِ همین کاربر است. تطبیق نام صاحب حساب با نام کاربر، بر عهده‌ی
    خزانه‌دار در لحظه‌ی واریز است.
    """
    if not iban or len(iban) != 26 or not iban.startswith('IR'):
        return False
    if not iban[2:].isdigit():
        return False
    rearranged = iban[4:] + iban[:4]
    digits = ''.join(ch if ch.isdigit() else str(ord(ch) - 55) for ch in rearranged)
    return int(digits) % 97 == 1


def get_withdrawable_amount(user):
    """چقدر از موجودی این کاربر قابل برداشت است (ریال).

        قابل برداشت = min( موجودی فعلی ، پولِ برگشتی از باشگاه − برداشت‌های ثبت‌شده )

    سقفِ «موجودی فعلی» یعنی نمی‌شود بیشتر از آنچه واقعاً در کیف پول هست
    برداشت کرد. جمله‌ی دوم یعنی خرجِ بلیط اول از پولِ شارژیِ خود کاربر کم
    می‌شود و بعد از پول جبرانی -- که به نفع کاربر است و ساده‌ترین قاعده‌ای
    است که هم‌زمان از دو طرف نشتی ندارد.
    """
    balance = Wallet.objects.filter(user=user).values_list('balance', flat=True).first() or 0
    if balance <= 0:
        return 0

    prefix_q = Q()
    for pre in WITHDRAWABLE_PREFIXES:
        prefix_q |= Q(reference_id__startswith=pre)

    credited = Transaction.objects.filter(
        prefix_q, user=user, is_wallet=True, amount__gt=0
    ).aggregate(s=Sum('amount'))['s'] or 0

    committed = WithdrawalRequest.objects.filter(
        user=user, status__in=WithdrawalRequest.COMMITTED_STATUSES
    ).aggregate(s=Sum('amount'))['s'] or 0

    return max(0, min(balance, credited - committed))


class WithdrawalRequest(models.Model):
    STATUS_CHOICES = (
        ('pending', 'در انتظار بررسی'),
        ('approved', 'تأیید شده — در انتظار واریز'),
        ('paid', 'واریز شد'),
        ('rejected', 'رد شد'),
    )
    # درخواستی که هنوز سرنوشتش روشن نشده -- کاربر نمی‌تواند هم‌زمان دومی ثبت کند.
    OPEN_STATUSES = ('pending', 'approved')
    # درخواست‌هایی که پولشان از کیف پول کسر شده و برنگشته. مبنای محاسبه‌ی
    # «چقدر دیگر قابل برداشت است».
    COMMITTED_STATUSES = ('pending', 'approved', 'paid')

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='withdrawal_requests')
    amount = models.BigIntegerField(verbose_name='مبلغ (ریال)')
    iban = models.CharField(max_length=26, verbose_name='شماره شبا')
    account_holder = models.CharField(max_length=120, verbose_name='نام صاحب حساب')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending', db_index=True)

    # شماره پیگیریِ واریز بانکی (پایا/ساتنا) که خزانه‌دار ثبت می‌کند
    bank_reference = models.CharField(max_length=80, blank=True, verbose_name='شماره پیگیری واریز')
    admin_note = models.TextField(blank=True, verbose_name='یادداشت مدیر / دلیل رد')
    processed_by = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL, related_name='processed_withdrawals'
    )

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)
    processed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'درخواست برداشت'
        verbose_name_plural = 'درخواست‌های برداشت'

    def __str__(self):
        return f"برداشت #{self.pk} - {self.user.username} - {self.amount:,} ریال - {self.get_status_display()}"

    @property
    def iban_display(self):
        """شبا را چهارتاچهارتا جدا نشان می‌دهد تا مقایسه‌ی چشمی خطا نداشته باشد."""
        body = self.iban[2:]
        return 'IR ' + ' '.join(body[i:i + 4] for i in range(0, len(body), 4))

    # ------------------------------------------------------------------
    @classmethod
    def create_for(cls, user, amount, iban, account_holder):
        """ثبت درخواست + کسر فوری موجودی، هر دو با هم یا هیچ‌کدام.

        کسر همین‌جا (نه موقع واریز) انجام می‌شود چون در فاصله‌ی ثبت تا واریز،
        کاربر می‌تواند همان پول را خرج بلیط کند و آن‌وقت باشگاه پولی را واریز
        می‌کند که دیگر وجود ندارد.
        """
        with transaction.atomic():
            req = cls.objects.create(
                user=user, amount=amount, iban=iban, account_holder=account_holder,
            )
            wallet, _ = Wallet.objects.get_or_create(user=user)
            ok = wallet.deduct_balance(
                amount=amount,
                description=f'درخواست برداشت به شبا {iban[-6:]}',
                reference_id=f'WD-{req.pk}',
                tx_type='withdraw',
            )
            if not ok:
                # موجودی بین نمایش فرم و ثبت آن تغییر کرده -- کل تراکنش برمی‌گردد.
                raise ValueError('موجودی کافی نیست.')
        return req

    def _finish(self, status, by, note='', bank_reference=''):
        """تغییر وضعیت با قفل ردیف، تا دو کلیکِ هم‌زمان ادمین دوبار اجرا نشود."""
        with transaction.atomic():
            fresh = WithdrawalRequest.objects.select_for_update().get(pk=self.pk)
            if fresh.status not in self.OPEN_STATUSES:
                return False, f'این درخواست قبلاً «{fresh.get_status_display()}» شده است.'

            if status == 'rejected':
                # پول باید برگردد وگرنه کاربر هم بلیط ندارد هم پول.
                # نکته: پیشوند reference عمداً 'WD-REJECT-' است و نه '-refund'؛
                # اگر با 'refund-' شروع می‌شد، دستور audit_payment_ticket_balance
                # آن را «جبران پرداخت‌شده» حساب می‌کرد و یک بدهیِ واقعی را پنهان
                # می‌کرد.
                wallet, _ = Wallet.objects.get_or_create(user=fresh.user)
                wallet.add_balance(
                    amount=fresh.amount,
                    description=f'بازگشت مبلغ درخواست برداشت #{fresh.pk} (رد شد)',
                    reference_id=f'WD-REJECT-{fresh.pk}',
                    tx_type='refund',
                )

            fresh.status = status
            fresh.processed_by = by
            fresh.processed_at = timezone.now()
            if note:
                fresh.admin_note = note
            if bank_reference:
                fresh.bank_reference = bank_reference
            fresh.save(update_fields=[
                'status', 'processed_by', 'processed_at', 'admin_note',
                'bank_reference', 'updated_at',
            ])
        self.refresh_from_db()
        return True, ''

    def approve(self, by, note=''):
        """تأیید مدیر: پول هنوز واریز نشده، فقط وارد صف خزانه‌داری می‌شود.

        اگر روزی API تسویه‌ی خودکار وصل شود، جای درستِ فراخوانی‌اش همین‌جاست:
        پس از تأیید، به‌جای انتظار برای خزانه‌دار، مستقیم mark_paid صدا زده شود.
        """
        return self._finish('approved', by, note=note)

    def mark_paid(self, by, bank_reference='', note=''):
        return self._finish('paid', by, note=note, bank_reference=bank_reference)

    def reject(self, by, reason=''):
        return self._finish('rejected', by, note=reason)