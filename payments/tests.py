"""تست‌های «پول نباید گم شود».

هر تست این فایل یک حالت واقعی است که یک بار روی پروداکشن اتفاق افتاده و
پول مردم را بلاتکلیف گذاشته. هدف این نیست که کد «کار کند» -- هدف این است
که این حالت‌ها دیگر هرگز بی‌صدا رد نشوند.
"""
from datetime import timedelta
from io import StringIO
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from matches.models import Block, Match, MatchSeat, Row, Seat, Stadium
from payments.models import Payment
from tickets.models import Ticket
from wallet.models import Transaction as WalletTx, Wallet

User = get_user_model()


class MoneyFixture(TestCase):
    """ورزشگاه/مسابقه/صندلیِ کمینه، فقط به اندازه‌ای که پول قابل ردیابی باشد."""

    def setUp(self):
        self.user = User.objects.create_user(username='buyer', password='x',
                                             phone_number='09120000000')
        self.stadium = Stadium.objects.create(name='نقش جهان', capacity=1000)
        self.block = Block.objects.create(stadium=self.stadium, name='بلوک ۱', price=1_000_000)
        self.row = Row.objects.create(block=self.block, number=1)
        self.seats = [Seat.objects.create(row=self.row, number=i) for i in range(1, 4)]
        self.match = Match.objects.create(
            home_team='سپاهان', away_team='حریف', stadium=self.stadium,
            date_time=timezone.now() + timedelta(days=2), created_by=None)
        # MatchSeat ها هنگام ساخت مسابقه خودکار تولید می‌شوند؛ فقط برشان می‌داریم.
        self.match_seats = [
            MatchSeat.objects.get_or_create(match=self.match, seat=s)[0]
            for s in self.seats
        ]
        self.wallet = Wallet.objects.get(user=self.user)

    def make_payment(self, seats, status='pending', amount=None, track='1000001',
                     captured=False, age_minutes=60):
        ms = seats if isinstance(seats, list) else [seats]
        buyer = {}
        for m in ms:
            buyer[f'match_seat_id_{m.id}'] = str(m.id)
            buyer[f'full_name_{m.id}'] = 'خریدار تست'
            buyer[f'national_code_{m.id}'] = '1234567890'
        p = Payment.objects.create(
            user=self.user, purpose='ticket_purchase', status=status,
            track_id=track, gateway_amount=amount if amount is not None else 1_000_000 * len(ms),
            match=self.match, buyer_info=buyer,
            gateway_captured_at=timezone.now() if captured else None)
        Payment.objects.filter(pk=p.pk).update(
            created_at=timezone.now() - timedelta(minutes=age_minutes))
        p.refresh_from_db()
        return p

    def make_ticket(self, seat, price=1_000_000, status='paid'):
        return Ticket.objects.create(
            user=self.user, match=self.match, seat=seat, price=price,
            full_name='خریدار تست', national_code='1234567890', status=status)


def zibal_says(status, amount=1_000_000):
    """پاسخ جعلیِ استعلام زیبال."""
    class R:
        @staticmethod
        def json():
            return {'status': status, 'amount': amount, 'result': 100}
    return R()


class SweeperTests(MoneyFixture):
    """جاروکش: کاربری که پرداخت کرد و هرگز برنگشت."""

    def _sweep(self, *extra):
        out = StringIO()
        call_command('sweep_pending_payments', '--execute', '--min-age', '1',
                     *extra, stdout=out, stderr=out)
        return out.getvalue()

    @patch('requests.Session.post')
    def test_user_paid_but_never_returned_gets_a_ticket(self, post):
        """حالت اصلی: پول گرفته شده، مسابقه هنوز نیامده -> باید بلیط بگیرد."""
        p = self.make_payment(self.match_seats[0])
        post.return_value = zibal_says(2)
        self._sweep()
        p.refresh_from_db()
        self.assertIsNotNone(p.gateway_captured_at, 'ثبتِ «پول گرفته شد» انجام نشد')
        self.assertEqual(p.status, 'success')
        self.assertEqual(Ticket.objects.filter(match=self.match, user=self.user).count(), 1)

    @patch('requests.Session.post')
    def test_paid_after_the_match_is_refunded_not_ticketed(self, post):
        """بلیطِ بازیِ تمام‌شده به درد نمی‌خورد -- پول باید برگردد."""
        Match.objects.filter(pk=self.match.pk).update(
            date_time=timezone.now() - timedelta(hours=3))
        p = self.make_payment(self.match_seats[0])
        post.return_value = zibal_says(2)
        self._sweep()
        p.refresh_from_db()
        self.wallet.refresh_from_db()
        self.assertIsNotNone(p.gateway_captured_at)
        self.assertEqual(self.wallet.balance, 1_000_000)
        self.assertEqual(Ticket.objects.filter(match=self.match).count(), 0)
        self.assertTrue(WalletTx.objects.filter(reference_id='refund-1000001').exists())

    @patch('requests.Session.post')
    def test_running_twice_never_refunds_twice(self, post):
        """اجرای دوباره‌ی تایمر نباید پول را دو بار برگرداند."""
        Match.objects.filter(pk=self.match.pk).update(
            date_time=timezone.now() - timedelta(hours=3))
        self.make_payment(self.match_seats[0])
        post.return_value = zibal_says(2)
        self._sweep()
        self._sweep()
        self.wallet.refresh_from_db()
        self.assertEqual(self.wallet.balance, 1_000_000)
        self.assertEqual(WalletTx.objects.filter(reference_id='refund-1000001').count(), 1)

    @patch('requests.Session.post')
    def test_user_never_paid_is_closed_and_seats_released(self, post):
        p = self.make_payment(self.match_seats[0])
        MatchSeat.objects.filter(pk=self.match_seats[0].pk).update(is_available=False)
        post.return_value = zibal_says(-1)
        self._sweep()
        p.refresh_from_db()
        self.match_seats[0].refresh_from_db()
        self.assertEqual(p.status, 'failed')
        self.assertIsNone(p.gateway_captured_at, 'پرداخت‌نشده نباید «گرفته‌شده» علامت بخورد')
        self.assertTrue(self.match_seats[0].is_available, 'صندلی آزاد نشد')
        self.assertEqual(self.wallet.balance, 0)

    @patch('tickets.management.commands.sweep_pending_payments.ZibalClient', create=True)
    @patch('requests.Session.post')
    def test_unverified_transaction_is_verified_before_anything_else(self, post, _client):
        """status=1 یعنی پرداخت‌شده ولی تأییدنشده.

        اگر verify نکنیم، زیبال خودش تراکنش را برمی‌گرداند؛ بازگشت وجهِ ما
        روی آن یعنی کاربر دو بار پول می‌گیرد.
        """
        Match.objects.filter(pk=self.match.pk).update(
            date_time=timezone.now() - timedelta(hours=3))
        self.make_payment(self.match_seats[0])
        post.return_value = zibal_says(1)
        with patch('zibal_payment.client.ZibalClient.payment_verify',
                   return_value={'result': 100}) as verify:
            self._sweep()
        self.assertTrue(verify.called, 'تراکنش تأییدنشده بدون verify پردازش شد')
        self.wallet.refresh_from_db()
        self.assertEqual(self.wallet.balance, 1_000_000)

    @patch('requests.Session.post')
    def test_gateway_error_leaves_the_payment_untouched(self, post):
        """اگر نتوانستیم بپرسیم، حق نداریم حدس بزنیم."""
        p = self.make_payment(self.match_seats[0])
        post.side_effect = RuntimeError('شبکه قطع است')
        self._sweep()
        p.refresh_from_db()
        self.assertEqual(p.status, 'pending')
        self.assertIsNone(p.gateway_captured_at)
        self.assertEqual(self.wallet.balance, 0)

    @patch('requests.Session.post')
    def test_old_payments_are_out_of_scope(self, post):
        """رکوردهای قدیمی قبلاً دستی تسویه شده‌اند؛ بازکردنشان خطر پرداخت دوباره است."""
        self.make_payment(self.match_seats[0], age_minutes=60 * 24 * 40)
        post.return_value = zibal_says(2)
        self._sweep()
        self.assertEqual(Ticket.objects.count(), 0)
        self.assertFalse(post.called)


class AuditTests(MoneyFixture):
    """ممیزی: هیچ حالتی از «پول گرفتیم و معادلش را ندادیم» نباید بی‌صدا بماند."""

    def _audit(self):
        out = StringIO()
        try:
            call_command('audit_payment_ticket_balance', stdout=out, stderr=out)
        except SystemExit:
            pass
        return out.getvalue()

    def test_healthy_purchase_raises_no_alarm(self):
        self.make_payment(self.match_seats[0], status='success', captured=True)
        self.make_ticket(self.seats[0])
        self.assertIn('تراز درست است', self._audit())

    def test_captured_but_pending_payment_is_caught(self):
        """نقطه‌ی کور شماره‌ی یک: پول گرفته شده ولی وضعیت 'pending' مانده."""
        self.make_payment(self.match_seats[0], status='pending', captured=True)
        out = self._audit()
        self.assertIn('طلبکار', out)
        self.assertIn('1,000,000', out)

    def test_value_mismatch_is_caught_even_when_seat_count_looks_fine(self):
        """نقطه‌ی کور شماره‌ی دو: بلیطِ رایگان، شمارشِ صندلی را گمراه می‌کند.

        کاربر ۲٬۰۰۰٬۰۰۰ پرداخت کرده و سه بلیط دارد -- از نظر تعداد صندلی
        بستانکار به‌نظر می‌رسد، ولی دو تا از بلیط‌ها رایگان‌اند و در واقع
        ۱٬۰۰۰٬۰۰۰ ریال طلبکار است.
        """
        self.make_payment([self.match_seats[0], self.match_seats[1]],
                          status='success', captured=True, amount=2_000_000)
        self.make_ticket(self.seats[0], price=1_000_000)
        self.make_ticket(self.seats[1], price=0)
        self.make_ticket(self.seats[2], price=0)
        out = self._audit()
        self.assertIn('طلبکار', out)

    def test_refund_already_paid_closes_the_balance(self):
        self.make_payment(self.match_seats[0], status='failed', captured=True, track='1000009')
        self.wallet.add_balance(amount=1_000_000, reference_id='refund-1000009', tx_type='refund')
        self.assertIn('تراز درست است', self._audit())

    def test_stale_pending_payment_is_reported_as_unknown(self):
        """پرداختی که نمی‌دانیم چه شد، باید صدا کند -- سکوت همان اشتباه قبلی است."""
        self.make_payment(self.match_seats[0], status='pending', age_minutes=120)
        out = self._audit()
        self.assertIn('تعیین‌تکلیف‌نشده', out)
        self.assertIn('sweep_pending_payments', out)

    def test_fresh_pending_payment_is_not_reported(self):
        """کاربری که همین الان روی صفحه‌ی درگاه است، هشدار نیست."""
        self.make_payment(self.match_seats[0], status='pending', age_minutes=2)
        self.assertIn('تراز درست است', self._audit())
