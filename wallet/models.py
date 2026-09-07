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
WITHDRAWABLE_PREFIXES = (
    'compensate-',      # جبران دستی (دستورهای مدیریتی)
    'SHORTFALL-',       # بلیط کمتر از آنچه پولش داده شده
    'OVERPAY-',         # پرداخت دوباره
    'refund-',          # بازگشت خودکار وقتی صدور بلیط شکست خورد
    'CANCEL-MATCH-',    # لغو مسابقه از سمت باشگاه
    'ADMIN-CREDIT-',    # شارژ جبرانیِ دستی از پنل
)

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

        قابل برداشت = min( موجودی فعلی ,
                           پولِ برگشتی از باشگاه − خرجِ بلیط − برداشت‌های ثبت‌شده )

    ===== چرا «خرجِ بلیط» هم کم می‌شود =====
    نسخه‌ی اول این تابع خرج را کم نمی‌کرد، یعنی خرج عملاً اول از پولِ شارژیِ
    خود کاربر برداشته می‌شد. آن قاعده به نظر به نفع کاربر می‌آمد ولی یک راهِ
    دور برای بیرون‌کشیدنِ پولِ شارژی باز می‌گذاشت:

        ۳ میلیون جبرانی می‌گیرد -> با همان بلیط می‌خرد -> ۳ میلیون از کارت
        خودش شارژ می‌کند -> حالا همان ۳ میلیون «قابل برداشت» شمرده می‌شود.

    نتیجه‌اش دقیقاً همان چیزی بود که نباید ممکن باشد: پول با کارتِ الف وارد
    شود و به حسابِ ب برگردد. حالا خرج *اول از سهمِ جبرانی* کم می‌شود، پس
    هر ریالی که کاربر خودش شارژ کرده تا آخر غیرقابل‌برداشت می‌ماند.

    این نه سخت‌گیرانه است و نه دست‌ودل‌بازانه -- فقط درست است: اگر کسی
    ۳ میلیون جبرانی و ۵ میلیون شارژِ خودش داشته باشد و ۵ میلیون بلیط بخرد،
    باقی‌مانده‌ی ۳ میلیونیِ کیف پولش تماماً پولِ خودش است، نه جبرانی.
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

    # هر برداشتِ ثبت‌شده یک تراکنش منفیِ 'withdraw' هم ساخته؛ آن‌ها اینجا
    # کنار گذاشته می‌شوند تا با `committed` دوبار شمرده نشوند.
    spent = Transaction.objects.filter(
        user=user, is_wallet=True, amount__lt=0
    ).exclude(transaction_type='withdraw').aggregate(s=Sum('amount'))['s'] or 0

    committed = WithdrawalRequest.objects.filter(
        user=user, status__in=WithdrawalRequest.COMMITTED_STATUSES
    ).aggregate(s=Sum('amount'))['s'] or 0

    # spent عددی منفی است، پس جمع می‌شود نه تفریق.
    return max(0, min(balance, credited + spent - committed))


def withdrawable_totals():
    """جمعِ کلِ قابل برداشت در سیستم -> (تعداد کاربر، مبلغ).

    همان قاعده‌ی get_withdrawable_amount، ولی به‌صورت انبوه: صفحه‌ی تنظیمات
    باید این عدد را پیش از روشن‌کردن کلید نشان بدهد و فراخوانی تک‌به‌تک برای
    صدها کیف پول یعنی هزاران کوئری. عمداً کنار همان تابع نوشته شده تا اگر
    قاعده عوض شد، هر دو با هم دیده شوند.
    """
    balances = dict(Wallet.objects.filter(balance__gt=0).values_list('user_id', 'balance'))
    if not balances:
        return 0, 0

    prefix_q = Q()
    for pre in WITHDRAWABLE_PREFIXES:
        prefix_q |= Q(reference_id__startswith=pre)

    credited = dict(Transaction.objects.filter(prefix_q, is_wallet=True, amount__gt=0)
                    .values_list('user_id').annotate(s=Sum('amount'))
                    .values_list('user_id', 's'))
    spent = dict(Transaction.objects.filter(is_wallet=True, amount__lt=0)
                 .exclude(transaction_type='withdraw')
                 .values_list('user_id').annotate(s=Sum('amount'))
                 .values_list('user_id', 's'))
    committed = dict(WithdrawalRequest.objects
                     .filter(status__in=WithdrawalRequest.COMMITTED_STATUSES)
                     .values_list('user_id').annotate(s=Sum('amount'))
                     .values_list('user_id', 's'))

    users = total = 0
    for uid, bal in balances.items():
        amount = min(bal, (credited.get(uid, 0) or 0)
                     + (spent.get(uid, 0) or 0) - (committed.get(uid, 0) or 0))
        if amount > 0:
            users += 1
            total += amount
    return users, total


class WithdrawalRequest(models.Model):
    # ===== چرخه‌ی عمر یک درخواست =====
    #
    #   در انتظار تأیید ──ادمین تأیید──▶ در حال پرداخت ──ثبت واریز──▶ پرداخت انجام شد
    #        │  ▲                             │
    #        │  │                             │ (بانک برگرداند یا مغایرت دیده شد)
    #        │  └──── کاربر اصلاح کرد ◀───── نیاز به اصلاح اطلاعات
    #        │                                     ▲
    #        └─────────────────────────────────────┘
    #
    # کاربر فقط در دو حالتِ «در انتظار تأیید» و «نیاز به اصلاح اطلاعات»
    # می‌تواند ویرایش کند. به‌محض تأیید، خزانه‌داری ممکن است در حال واریز
    # باشد و تغییر شبا در آن لحظه یعنی واریز به حساب اشتباه.
    STATUS_CHOICES = (
        ('pending', 'در انتظار تأیید'),
        ('needs_correction', 'نیاز به اصلاح اطلاعات'),
        ('approved', 'در حال پرداخت'),
        ('paid', 'پرداخت انجام شد'),
        ('rejected', 'رد شد'),
        ('cancelled', 'لغو شده توسط شما'),
    )
    # درخواستی که هنوز سرنوشتش روشن نشده -- کاربر نمی‌تواند هم‌زمان دومی ثبت کند.
    OPEN_STATUSES = ('pending', 'needs_correction', 'approved')
    # حالت‌هایی که کاربر می‌تواند اطلاعات را عوض کند.
    EDITABLE_STATUSES = ('pending', 'needs_correction')
    # درخواست‌هایی که پولشان از کیف پول کسر شده و برنگشته. مبنای محاسبه‌ی
    # «چقدر دیگر قابل برداشت است». «نیاز به اصلاح» عمداً اینجاست: پول همچنان
    # نگه داشته می‌شود تا کاربر در فاصله‌ی اصلاح آن را خرج بلیط نکند.
    COMMITTED_STATUSES = ('pending', 'needs_correction', 'approved', 'paid')

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='withdrawal_requests')
    amount = models.BigIntegerField(verbose_name='مبلغ (ریال)')
    iban = models.CharField(max_length=26, verbose_name='شماره شبا')
    account_holder = models.CharField(max_length=120, verbose_name='نام صاحب حساب')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending', db_index=True)

    # ===== نتیجه‌ی استعلام شبا از بانک =====
    # None یعنی نپرسیدیم یا نتوانستیم بپرسیم (توکن نبود، سرویس قطع بود).
    # عمداً با False یکی نیست: «نمی‌دانیم» نباید مثل «مغایرت دارد» رفتار شود،
    # وگرنه یک قطعیِ موقتِ سرویس، درخواست‌های درست را هم متوقف می‌کند.
    iban_verified = models.BooleanField(
        null=True, blank=True, verbose_name='تطابق نام با بانک')
    iban_owner_name = models.CharField(
        max_length=120, blank=True, verbose_name='نام صاحب حساب نزد بانک')

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

            if status in ('rejected', 'cancelled'):
                # پول باید برگردد وگرنه کاربر هم بلیط ندارد هم پول.
                # نکته: پیشوند reference عمداً 'WD-REJECT-' است و نه '-refund'؛
                # اگر با 'refund-' شروع می‌شد، دستور audit_payment_ticket_balance
                # آن را «جبران پرداخت‌شده» حساب می‌کرد و یک بدهیِ واقعی را پنهان
                # می‌کرد.
                wallet, _ = Wallet.objects.get_or_create(user=fresh.user)
                _what = 'لغو شد' if status == 'cancelled' else 'رد شد'
                wallet.add_balance(
                    amount=fresh.amount,
                    description=f'بازگشت مبلغ درخواست برداشت #{fresh.pk} ({_what})',
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
        ok, err = self._finish('paid', by, note=note, bank_reference=bank_reference)
        if ok and bank_reference:
            # ===== شناسه‌ی واریز باید در تاریخچه‌ی خودِ کاربر بنشیند =====
            # تراکنشِ کسر، لحظه‌ی ثبتِ درخواست ساخته شده و آن موقع هنوز
            # شناسه‌ای وجود نداشت. اگر همان‌جا به‌روز نشود، کاربر در تاریخچه‌ی
            # کیف پولش فقط یک «برداشت» می‌بیند بدون هیچ شماره‌ی پیگیری‌ای که
            # بتواند با آن به بانک مراجعه کند.
            Transaction.objects.filter(
                user=self.user, reference_id=f'WD-{self.pk}'
            ).update(description=(
                f'برداشت به شبا {self.iban[-6:]} — واریز شد، '
                f'شناسه پیگیری: {bank_reference}'))
        return ok, err

    def reject(self, by, reason=''):
        return self._finish('rejected', by, note=reason)

    def record_iban_check(self, check, *candidate_names):
        """نتیجه‌ی استعلام بانک را روی درخواست می‌نشاند.

        اگر نام مغایر بود، درخواست خودکار به «نیاز به اصلاح اطلاعات» می‌رود --
        بدون معطلیِ اپراتور و بدون بن‌بست: کاربر همان لحظه می‌بیند حساب به نام
        چه کسی است و می‌تواند اصلاح کند، و مدیر هم اگر مطمئن باشد می‌تواند
        همان را تأیید کند (مثلاً املای متفاوتِ یک نام).

        خروجی: پیامی برای نشان‌دادن به کاربر (یا رشته‌ی خالی).
        """
        from .iban_inquiry import OK, BAD_IBAN, names_match

        status = check.get('status')
        bank_name = (check.get('name') or '').strip()
        ownership = check.get('ownership')

        # ===== تطابق کد ملی، اگر جواب داده باشد، حرفِ آخر است =====
        # مقایسه‌ی نام حدسی است: دو نفر می‌توانند هم‌نام باشند و یک نفر
        # می‌تواند نامش را جور دیگری بنویسد. وقتی بانک صریحاً گفته این حساب
        # متعلق به دارنده‌ی این کد ملی هست یا نیست، دیگر جای حدس نیست.
        if ownership is True:
            self.iban_owner_name = bank_name
            self.iban_verified = True
            self.save(update_fields=['iban_owner_name', 'iban_verified', 'updated_at'])
            return ''

        if ownership is False:
            self.iban_owner_name = bank_name
            self.iban_verified = False
            self.status = 'needs_correction'
            self.admin_note = (
                f'این شماره شبا متعلق به شما نیست'
                + (f' (به نام «{bank_name}» است)' if bank_name else '')
                + '. حساب باید به نام خودتان و با کد ملی خودتان باشد.')
            self.save(update_fields=['iban_owner_name', 'iban_verified',
                                     'status', 'admin_note', 'updated_at'])
            return self.admin_note

        if status == OK:
            matched = names_match(bank_name, *candidate_names)
            self.iban_owner_name = bank_name
            self.iban_verified = matched
            if not matched:
                self.status = 'needs_correction'
                self.admin_note = (f'شماره شبای واردشده به نام «{bank_name}» است، '
                                   f'نه شما. حساب باید به نام خودتان باشد.')
            self.save(update_fields=['iban_owner_name', 'iban_verified',
                                     'status', 'admin_note', 'updated_at'])
            return '' if matched else self.admin_note

        if status == BAD_IBAN:
            self.iban_verified = False
            self.iban_owner_name = ''
            self.status = 'needs_correction'
            self.admin_note = ('این شماره شبا نزد بانک یافت نشد. '
                               'لطفاً آن را از اپلیکیشن بانک خود دوباره بررسی کنید.')
            self.save(update_fields=['iban_owner_name', 'iban_verified',
                                     'status', 'admin_note', 'updated_at'])
            return self.admin_note

        # نامعلوم -- دست به وضعیت نمی‌زنیم؛ بررسی دستی مثل قبل انجام می‌شود.
        return ''

    def request_correction(self, by, reason=''):
        """اطلاعات ایراد دارد -- برگردان به کاربر تا خودش اصلاح کند.

        عمداً با «رد کردن» فرق دارد: پول همچنان نگه داشته می‌شود و درخواست
        زنده می‌ماند. اگر به‌جایش رد می‌شد، پول به کیف پول برمی‌گشت، کاربر
        می‌توانست خرجش کند و بعد دیگر چیزی برای برداشت نمی‌ماند -- در حالی
        که تنها ایراد یک شماره‌ی شبای غلط بوده.
        """
        with transaction.atomic():
            fresh = WithdrawalRequest.objects.select_for_update().get(pk=self.pk)
            if fresh.status not in ('pending', 'approved', 'needs_correction'):
                return False, f'این درخواست در وضعیت «{fresh.get_status_display()}» است.'
            fresh.status = 'needs_correction'
            fresh.processed_by = by
            fresh.processed_at = timezone.now()
            fresh.admin_note = reason
            fresh.save(update_fields=['status', 'processed_by', 'processed_at',
                                      'admin_note', 'updated_at'])
        self.refresh_from_db()
        return True, ''

    def update_by_user(self, amount, iban, account_holder):
        """کاربر اطلاعات درخواستِ بازش را اصلاح می‌کند.

        اگر مبلغ عوض شود، تفاوتش همین‌جا با کیف پول تسویه می‌شود -- وگرنه
        مبلغِ نگه‌داشته‌شده با مبلغِ درخواست یکی نمی‌ماند و محاسبه‌ی
        «قابل برداشت» غلط می‌شود.
        """
        with transaction.atomic():
            fresh = WithdrawalRequest.objects.select_for_update().get(pk=self.pk)
            if fresh.status not in self.EDITABLE_STATUSES:
                return False, ('این درخواست دیگر قابل ویرایش نیست؛ '
                               f'وضعیت فعلی: {fresh.get_status_display()}.')

            wallet, _ = Wallet.objects.get_or_create(user=fresh.user)
            delta = amount - fresh.amount
            if delta > 0:
                ok = wallet.deduct_balance(
                    amount=delta,
                    description=f'افزایش مبلغ درخواست برداشت #{fresh.pk}',
                    reference_id=f'WD-ADJ-{fresh.pk}-{int(timezone.now().timestamp())}',
                    tx_type='withdraw')
                if not ok:
                    return False, 'موجودی برای افزایش مبلغ کافی نیست.'
            elif delta < 0:
                wallet.add_balance(
                    amount=-delta,
                    description=f'کاهش مبلغ درخواست برداشت #{fresh.pk}',
                    reference_id=f'WD-ADJ-{fresh.pk}-{int(timezone.now().timestamp())}',
                    tx_type='refund')

            fresh.amount = amount
            fresh.iban = iban
            fresh.account_holder = account_holder
            fresh.status = 'pending'          # دوباره در صف بررسی
            fresh.admin_note = ''
            fresh.save(update_fields=['amount', 'iban', 'account_holder', 'status',
                                      'admin_note', 'updated_at'])
        self.refresh_from_db()
        return True, ''

    def cancel_by_user(self, reason='انصراف کاربر'):
        """کاربر خودش درخواستش را پس می‌گیرد و پولش را برمی‌گرداند.

        فقط در حالت‌های قابل ویرایش ممکن است؛ بعد از تأیید، خزانه‌داری ممکن
        است همین حالا در حال واریز باشد و پس‌گرفتنش یعنی احتمال واریز دوباره.
        """
        with transaction.atomic():
            fresh = WithdrawalRequest.objects.select_for_update().get(pk=self.pk)
            if fresh.status not in self.EDITABLE_STATUSES:
                return False, ('این درخواست دیگر قابل لغو نیست؛ '
                               f'وضعیت فعلی: {fresh.get_status_display()}.')
        return self._finish('cancelled', None, note=reason)