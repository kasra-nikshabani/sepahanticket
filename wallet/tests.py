"""تست‌های جریان پول در برداشت وجه.

چرا این فایل وجود دارد: هر مسیری که پول را جابه‌جا می‌کند باید ثابت کند که
پول نه گم می‌شود و نه دو بار شمرده می‌شود. اشتباه در این مسیر مثل اشتباه در
یک صفحه‌ی نمایشی نیست -- مستقیم روی حساب بانکی آدم‌ها اثر می‌گذارد.
"""
from django.contrib.auth import get_user_model
from django.test import TestCase

from .models import (Wallet, Transaction, WithdrawalRequest,
                     get_withdrawable_amount, is_valid_iban, normalize_iban,
                     WITHDRAWABLE_PREFIXES)

User = get_user_model()

VALID_IBAN = 'IR270170000000100324200001'


class WithdrawableAmountTests(TestCase):
    """«چقدر قابل برداشت است» -- قاعده‌ای که کل ویژگی رویش سوار است."""

    def setUp(self):
        self.user = User.objects.create_user(username='u1', password='x')
        # کیف پول با سیگنال post_save روی User ساخته می‌شود، پس فقط برش می‌داریم.
        self.wallet = Wallet.objects.get(user=self.user)

    def _credit(self, amount, reference_id, tx_type='deposit'):
        self.wallet.add_balance(amount=amount, reference_id=reference_id, tx_type=tx_type)

    def test_self_charged_money_is_not_withdrawable(self):
        """پولی که کاربر خودش از درگاه شارژ کرده قابل برداشت نیست."""
        self._credit(5_000_000, reference_id='4734693545')  # track_id درگاه
        self.assertEqual(self.wallet.balance, 5_000_000)
        self.assertEqual(get_withdrawable_amount(self.user), 0)

    def test_compensation_money_is_withdrawable(self):
        self._credit(3_000_000, reference_id='compensate-64-12')
        self.assertEqual(get_withdrawable_amount(self.user), 3_000_000)

    def test_all_compensation_prefixes_count(self):
        for i, pre in enumerate(WITHDRAWABLE_PREFIXES):
            self._credit(1_000_000, reference_id=f'{pre}{i}')
        self.assertEqual(get_withdrawable_amount(self.user),
                         1_000_000 * len(WITHDRAWABLE_PREFIXES))

    def test_mixed_money_spending_is_charged_to_self_funds_first(self):
        """خرج بلیط اول از پول شارژیِ خود کاربر کم می‌شود، بعد از پول جبرانی."""
        self._credit(5_000_000, reference_id='compensate-64-1')
        self._credit(1_000_000, reference_id='4734693545')
        self.wallet.deduct_balance(amount=2_000_000, reference_id='order-1',
                                   tx_type='ticket_purchase')
        self.assertEqual(self.wallet.balance, 4_000_000)
        # ۵ جبرانی منهای ۱ که سهم شارژ خودش را پوشانده = ۴
        self.assertEqual(get_withdrawable_amount(self.user), 4_000_000)

    def test_never_exceeds_actual_balance(self):
        """اگر پول جبرانی خرج بلیط شده باشد، دیگر قابل برداشت نیست."""
        self._credit(5_000_000, reference_id='compensate-64-1')
        self.wallet.deduct_balance(amount=4_500_000, reference_id='order-1',
                                   tx_type='ticket_purchase')
        self.assertEqual(get_withdrawable_amount(self.user), 500_000)


class WithdrawalFlowTests(TestCase):
    """چرخه‌ی کامل: ثبت -> تأیید -> واریز، و مسیر رد شدن."""

    def setUp(self):
        self.user = User.objects.create_user(username='u2', password='x')
        self.admin = User.objects.create_user(username='adm', password='x', is_staff=True)
        # کیف پول با سیگنال post_save روی User ساخته می‌شود، پس فقط برش می‌داریم.
        self.wallet = Wallet.objects.get(user=self.user)
        self.wallet.add_balance(amount=5_000_000, reference_id='compensate-64-9',
                                tx_type='deposit')

    def test_request_holds_the_money_immediately(self):
        """پول باید همان لحظه کسر شود، نه موقع واریز."""
        req = WithdrawalRequest.create_for(self.user, 3_000_000, VALID_IBAN, 'کسری ن')
        self.wallet.refresh_from_db()
        self.assertEqual(self.wallet.balance, 2_000_000)
        self.assertEqual(req.status, 'pending')
        tx = Transaction.objects.get(reference_id=f'WD-{req.pk}')
        self.assertEqual(tx.amount, -3_000_000)
        self.assertEqual(tx.transaction_type, 'withdraw')
        # همان پول نباید دوباره قابل درخواست باشد
        self.assertEqual(get_withdrawable_amount(self.user), 2_000_000)

    def test_cannot_request_more_than_balance(self):
        with self.assertRaises(ValueError):
            WithdrawalRequest.create_for(self.user, 9_000_000, VALID_IBAN, 'کسری ن')
        self.wallet.refresh_from_db()
        self.assertEqual(self.wallet.balance, 5_000_000)
        # ردیف درخواست هم نباید باقی مانده باشد (اتمیک بودن create_for)
        self.assertEqual(WithdrawalRequest.objects.count(), 0)

    def test_reject_returns_the_money(self):
        req = WithdrawalRequest.create_for(self.user, 3_000_000, VALID_IBAN, 'کسری ن')
        ok, err = req.reject(self.admin, reason='نام صاحب حساب مغایر است')
        self.assertTrue(ok, err)
        self.wallet.refresh_from_db()
        self.assertEqual(self.wallet.balance, 5_000_000)
        self.assertEqual(req.status, 'rejected')
        self.assertEqual(get_withdrawable_amount(self.user), 5_000_000)

    def test_reject_reference_does_not_pollute_the_payment_audit(self):
        """بازگشتِ ردِ درخواست نباید به‌عنوان «جبران پرداخت» شمرده شود.

        دستور audit_payment_ticket_balance هر تراکنشی با پیشوند 'refund-' را
        جبرانِ یک بلیطِ صادرنشده حساب می‌کند. اگر این بازگشت همان پیشوند را
        می‌گرفت، یک بدهیِ واقعیِ باشگاه در گزارش پنهان می‌شد.
        """
        from tickets.management.commands.audit_payment_ticket_balance import (
            COMPENSATION_PREFIXES)
        req = WithdrawalRequest.create_for(self.user, 3_000_000, VALID_IBAN, 'کسری ن')
        req.reject(self.admin, reason='تست')
        ref = Transaction.objects.filter(amount__gt=0).exclude(
            reference_id='compensate-64-9').first().reference_id
        self.assertEqual(ref, f'WD-REJECT-{req.pk}')
        self.assertFalse(ref.startswith(COMPENSATION_PREFIXES))

    def test_paid_keeps_the_money_out(self):
        req = WithdrawalRequest.create_for(self.user, 3_000_000, VALID_IBAN, 'کسری ن')
        req.approve(self.admin)
        self.assertEqual(req.status, 'approved')
        ok, err = req.mark_paid(self.admin, bank_reference='PAYA-123456')
        self.assertTrue(ok, err)
        self.wallet.refresh_from_db()
        self.assertEqual(self.wallet.balance, 2_000_000)
        self.assertEqual(req.bank_reference, 'PAYA-123456')

    def test_a_settled_request_cannot_be_processed_twice(self):
        """دو کلیک هم‌زمان ادمین نباید پول را دو بار برگرداند."""
        req = WithdrawalRequest.create_for(self.user, 3_000_000, VALID_IBAN, 'کسری ن')
        req.reject(self.admin, reason='یک بار')
        ok, err = req.reject(self.admin, reason='دو بار')
        self.assertFalse(ok)
        self.assertIn('قبلاً', err)
        self.wallet.refresh_from_db()
        self.assertEqual(self.wallet.balance, 5_000_000)  # نه ۸ میلیون

    def test_paid_request_cannot_be_rejected_afterwards(self):
        req = WithdrawalRequest.create_for(self.user, 3_000_000, VALID_IBAN, 'کسری ن')
        req.mark_paid(self.admin, bank_reference='PAYA-1')
        ok, _ = req.reject(self.admin, reason='اشتباهی')
        self.assertFalse(ok)
        self.wallet.refresh_from_db()
        self.assertEqual(self.wallet.balance, 2_000_000)


class WithdrawalViewTests(TestCase):
    """ورودی کاربر: هیچ مسیری نباید بدون کلید فعال یا با ورودی نامعتبر رد شود."""

    def setUp(self):
        from accounts.models import SiteSettings
        self.user = User.objects.create_user(username='u3', password='pw12345',
                                             user_type='normal')
        # کیف پول با سیگنال post_save روی User ساخته می‌شود، پس فقط برش می‌داریم.
        self.wallet = Wallet.objects.get(user=self.user)
        self.wallet.add_balance(amount=5_000_000, reference_id='compensate-64-3')
        s = SiteSettings.get_solo()
        s.withdrawal_enabled = True
        # GeoAccessMiddleware هدر X-Iran-IP را از nginx انتظار دارد؛ تست‌کلاینت
        # آن را نمی‌فرستد و همه‌ی درخواست‌ها ۴۰۳ می‌شدند. موضوع این تست‌ها
        # کنترل جغرافیایی نیست.
        s.block_foreign_ips = False
        s.save()
        self.client.force_login(self.user)

    def _post(self, **kw):
        data = {'amount': '1000000', 'iban': VALID_IBAN, 'account_holder': 'کسری نیک‌شبانی'}
        data.update(kw)
        return self.client.post('/wallet/withdraw/', data)

    def test_happy_path(self):
        resp = self._post()
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(WithdrawalRequest.objects.count(), 1)
        self.wallet.refresh_from_db()
        self.assertEqual(self.wallet.balance, 4_000_000)

    def test_invalid_iban_is_refused(self):
        self._post(iban='IR270170000000100324200000')
        self.assertEqual(WithdrawalRequest.objects.count(), 0)
        self.wallet.refresh_from_db()
        self.assertEqual(self.wallet.balance, 5_000_000)

    def test_amount_above_withdrawable_is_refused(self):
        self._post(amount='9000000')
        self.assertEqual(WithdrawalRequest.objects.count(), 0)

    def test_persian_digits_in_amount_and_iban_are_accepted(self):
        fa = str.maketrans('0123456789', '۰۱۲۳۴۵۶۷۸۹')
        self._post(amount='1000000'.translate(fa), iban=VALID_IBAN.translate(fa))
        self.assertEqual(WithdrawalRequest.objects.count(), 1)

    def test_second_open_request_is_refused(self):
        self._post()
        self._post()
        self.assertEqual(WithdrawalRequest.objects.count(), 1)

    def test_disabled_switch_closes_the_page(self):
        from accounts.models import SiteSettings
        s = SiteSettings.get_solo()
        s.withdrawal_enabled = False
        s.save()
        resp = self._post()
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(WithdrawalRequest.objects.count(), 0)

    def test_vip_user_has_no_access(self):
        self.user.user_type = 'vip'
        self.user.save()
        self._post()
        self.assertEqual(WithdrawalRequest.objects.count(), 0)


class PageRenderTests(TestCase):
    """صفحه‌ها واقعاً رندر شوند.

    یک خطای نحوی در تمپلیت را نه manage.py check می‌گیرد و نه تست‌های منطقی؛
    فقط رندر شدن واقعی آن را نشان می‌دهد.
    """

    def setUp(self):
        from accounts.models import SiteSettings
        self.user = User.objects.create_user(username='u4', password='pw12345')
        self.admin = User.objects.create_user(username='adm2', password='pw12345',
                                              is_staff=True, is_superuser=True)
        w = Wallet.objects.get(user=self.user)
        w.add_balance(amount=4_000_000, reference_id='compensate-64-4')
        s = SiteSettings.get_solo()
        s.withdrawal_enabled = True
        s.block_foreign_ips = False
        s.save()

    def test_user_dashboard_and_withdraw_page_render(self):
        self.client.force_login(self.user)
        self.assertEqual(self.client.get('/wallet/dashboard/').status_code, 200)
        resp = self.client.get('/wallet/withdraw/')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'حداکثر مبلغ قابل برداشت')

    def test_admin_queue_renders_with_and_without_rows(self):
        self.client.force_login(self.admin)
        url = '/wallet/admin/withdrawals/'
        self.assertEqual(self.client.get(url).status_code, 200)

        WithdrawalRequest.create_for(self.user, 1_000_000, VALID_IBAN, 'کسری نیک‌شبانی')
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'قبل از واریز، نام را مقایسه کنید')
        for st in ('pending', 'approved', 'paid', 'rejected', 'all'):
            self.assertEqual(self.client.get(f'{url}?status={st}').status_code, 200)

    def test_admin_actions_move_money_through_the_view(self):
        self.client.force_login(self.admin)
        req = WithdrawalRequest.create_for(self.user, 1_000_000, VALID_IBAN, 'کسری نیک‌شبانی')
        url = f'/wallet/admin/withdrawals/{req.pk}/action/'

        # ثبت واریز بدون شماره پیگیری نباید انجام شود
        self.client.post(url, {'action': 'paid'})
        req.refresh_from_db()
        self.assertEqual(req.status, 'pending')

        # رد بدون دلیل هم نباید انجام شود
        self.client.post(url, {'action': 'reject'})
        req.refresh_from_db()
        self.assertEqual(req.status, 'pending')

        self.client.post(url, {'action': 'approve'})
        req.refresh_from_db()
        self.assertEqual(req.status, 'approved')

        self.client.post(url, {'action': 'paid', 'bank_reference': 'PAYA-9'})
        req.refresh_from_db()
        self.assertEqual(req.status, 'paid')
        self.assertEqual(Wallet.objects.get(user=self.user).balance, 3_000_000)

    def test_site_settings_page_shows_the_withdrawal_card(self):
        """کارت «برداشت وجه» در تنظیمات سایت، عددِ واقعیِ قابل برداشت را نشان دهد."""
        self.client.force_login(self.admin)
        resp = self.client.get('/accounts/admin/site-settings/')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'برداشت وجه از کیف پول')
        self.assertEqual(resp.context['withdrawable_total'], 4_000_000)
        self.assertEqual(resp.context['withdrawable_users'], 1)

    def test_non_staff_cannot_open_the_admin_queue(self):
        self.client.force_login(self.user)
        resp = self.client.get('/wallet/admin/withdrawals/')
        self.assertNotEqual(resp.status_code, 200)


class TemplateCommentLintTests(TestCase):
    """کامنت `{# ... #}` چندخطی نباید در هیچ تمپلیتی وجود داشته باشد.

    لکسر جنگو (django/template/base.py) با الگوی
    `({%.*?%}|{{.*?}}|{#.*?#})` و **بدون** فلگ DOTALL کار می‌کند، یعنی نقطه
    خط جدید را نمی‌گیرد. پس `{#` که تا خط بعد ادامه پیدا کند اصلاً کامنت
    شناخته نمی‌شود و متنش خام به کاربر نمایش داده می‌شود. این دقیقاً روی
    صفحه‌ی کیف پول در پروداکشن اتفاق افتاد.

    برای توضیح چندخطی باید از {% comment %}...{% endcomment %} استفاده شود.
    """

    def test_no_multiline_hash_comments_in_templates(self):
        from pathlib import Path
        from django.conf import settings

        # همان رفتار لکسر تقلید می‌شود: از چپ به راست، و هر `{#` که بسته شد،
        # مکان‌نما بعد از `#}` می‌پرد. بدون این پرش، `{#` هایی که *داخل* یک
        # کامنت بسته‌شده‌اند (مثل `{# setTimeout(function () {#}`) اشتباهاً
        # خطا گزارش می‌شوند -- همان‌طور که جنگو هم آن‌ها را نمی‌بیند.
        offenders = []
        for tpl_dir in settings.TEMPLATES[0]['DIRS']:
            for path in sorted(Path(tpl_dir).rglob('*.html')):
                for lineno, line in enumerate(path.read_text(encoding='utf-8').splitlines(), 1):
                    pos = 0
                    while (start := line.find('{#', pos)) != -1:
                        close = line.find('#}', start + 2)
                        if close == -1:
                            offenders.append(f'{path}:{lineno}  {line.strip()[:80]}')
                            break
                        pos = close + 2
        self.assertEqual(offenders, [], 'کامنت {# #} چندخطی پیدا شد (خام رندر می‌شود):\n'
                                        + '\n'.join(offenders))


class RenderedPagesHaveNoLeakedCommentsTests(TestCase):
    """هیچ متنِ توضیحیِ داخل کد نباید در خروجی صفحه دیده شود."""

    def setUp(self):
        from accounts.models import SiteSettings
        self.user = User.objects.create_user(username='u5', password='pw12345')
        self.admin = User.objects.create_user(username='adm3', password='pw12345',
                                              is_staff=True, is_superuser=True)
        Wallet.objects.get(user=self.user).add_balance(
            amount=4_000_000, reference_id='compensate-64-5')
        s = SiteSettings.get_solo()
        s.withdrawal_enabled = True
        s.block_foreign_ips = False
        s.save()

    def test_wallet_pages_do_not_show_source_comments(self):
        self.client.force_login(self.user)
        for url in ['/wallet/dashboard/', '/wallet/withdraw/']:
            body = self.client.get(url).content.decode()
            self.assertNotIn('{#', body, url)
            self.assertNotIn('wallet_charge_enabled', body, url)

    def test_admin_pages_do_not_show_source_comments(self):
        self.client.force_login(self.admin)
        WithdrawalRequest.create_for(self.user, 1_000_000, VALID_IBAN, 'کسری نیک‌شبانی')
        for url in ['/wallet/admin/withdrawals/', '/accounts/admin/site-settings/']:
            body = self.client.get(url).content.decode()
            self.assertNotIn('{#', body, url)
            self.assertNotIn('سیستم شبا را استعلام', body, url)


class IbanValidationTests(TestCase):
    def test_accepts_common_input_shapes(self):
        body = VALID_IBAN[2:]
        spaced = 'IR ' + ' '.join(body[i:i + 4] for i in range(0, len(body), 4))
        for raw in [VALID_IBAN, VALID_IBAN.lower(), spaced, body,
                    VALID_IBAN.translate(str.maketrans('0123456789', '۰۱۲۳۴۵۶۷۸۹'))]:
            self.assertTrue(is_valid_iban(normalize_iban(raw)), raw)

    def test_rejects_wrong_checksum_and_foreign_iban(self):
        for raw in ['', 'IR123', 'IR000000000000000000000000',
                    'DE89370400440532013000', 'IR' + 'A' * 24]:
            self.assertFalse(is_valid_iban(normalize_iban(raw)), raw)
