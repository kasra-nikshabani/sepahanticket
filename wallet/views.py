# wallet/views.py
from django.core.paginator import Paginator, PageNotAnInteger, EmptyPage
from django.db.models import Sum
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.views.decorators.cache import never_cache

from .models import (Wallet, Transaction, WithdrawalRequest,
                     is_wallet_enabled, is_wallet_charge_enabled, is_withdrawal_enabled,
                     get_withdrawable_amount, normalize_iban, is_valid_iban,
                     MIN_WITHDRAWAL_AMOUNT,
                     WALLET_DISABLED_MESSAGE, WALLET_CHARGE_DISABLED_MESSAGE,
                     WITHDRAWAL_DISABLED_MESSAGE)


@never_cache
@login_required
def wallet_dashboard(request):
    """نمایش کیف پول و تاریخچه تراکنش‌ها با صفحه‌بندی"""
    if request.user.user_type == 'vip':
        messages.error(request, 'کاربران ویژه به این بخش دسترسی ندارند.')
        return redirect('matches:home')

    wallet, created = Wallet.objects.get_or_create(user=request.user)

    transactions_list = Transaction.objects.filter(
        user=request.user
    ).order_by('-created_at')

    paginator = Paginator(transactions_list, 5)
    page = request.GET.get('page', 1)

    try:
        transactions = paginator.page(page)
    except PageNotAnInteger:
        transactions = paginator.page(1)
    except EmptyPage:
        transactions = paginator.page(paginator.num_pages)

    total_deposits = Transaction.objects.filter(
        user=request.user,
        transaction_type='deposit'
    ).aggregate(total=Sum('amount'))['total'] or 0

    total_withdrawals = Transaction.objects.filter(
        user=request.user,
        transaction_type__in=['withdraw', 'ticket_purchase']
    ).aggregate(total=Sum('amount'))['total'] or 0

    total_ticket_purchases = Transaction.objects.filter(
        user=request.user,
        transaction_type='ticket_purchase'
    ).aggregate(total=Sum('amount'))['total'] or 0

    total_refunds = Transaction.objects.filter(
        user=request.user,
        transaction_type='refund'
    ).aggregate(total=Sum('amount'))['total'] or 0

    total_transactions = Transaction.objects.filter(user=request.user).count()

    context = {
        'wallet': wallet,
        'wallet_balance': wallet.balance,
        'transactions': transactions,
        'total_deposits': total_deposits,
        'total_withdrawals': total_withdrawals,
        'total_ticket_purchases': total_ticket_purchases,
        'total_refunds': total_refunds,
        'total_transactions': total_transactions,
        # داشبورد در حالت غیرفعال هم باز می‌ماند (کاربر باید موجودی و تاریخچه‌اش
        # را ببیند)، ولی دکمه‌های شارژ جای خود را به یک توضیح می‌دهند.
        'wallet_enabled': is_wallet_enabled(),
        'wallet_charge_enabled': is_wallet_charge_enabled(),
        'withdrawal_enabled': is_withdrawal_enabled(),
        'withdrawable': get_withdrawable_amount(request.user),
        'withdrawals': WithdrawalRequest.objects.filter(user=request.user)[:10],
    }
    return render(request, 'wallet/dashboard.html', context)


@login_required
def wallet_charge(request):
    """
    صفحه‌ی شارژ کیف پول.

    نکته‌ی مهم: این ویو دیگر خودش موجودی را افزایش نمی‌دهد (قبلاً یک نسخه‌ی
    شبیه‌سازی‌شده بدون پرداخت واقعی بود که حذف شد). شارژ واقعی همیشه از طریق
    فرم این صفحه مستقیماً به payments:payment_request ارسال می‌شود و فقط پس
    از تایید واقعی زیبال در payments:payment_verify انجام می‌گیرد.
    """
    if request.user.user_type == 'vip':
        messages.error(request, 'کاربران ویژه به این بخش دسترسی ندارند.')
        return redirect('matches:home')

    # ===== کیف پول غیرفعال یعنی صفحه‌ی شارژ اصلاً باز نشود =====
    # پنهان کردن دکمه در تمپلیت کافی نیست؛ آدرس این صفحه ممکن است بوکمارک
    # شده باشد یا مستقیم تایپ شود.
    if not is_wallet_charge_enabled():
        messages.error(request, WALLET_CHARGE_DISABLED_MESSAGE)
        return redirect('wallet:dashboard')

    wallet = get_object_or_404(Wallet, user=request.user)

    if request.method == 'POST':
        # این مسیر دیگر پردازشی انجام نمی‌دهد؛ فرم صفحه باید مستقیم به
        # payments:payment_request ارسال شود (طبق تمپلیت فعلی charge.html).
        messages.info(request, 'برای شارژ کیف پول از دکمه‌ی «پرداخت و شارژ» استفاده کنید.')
        return redirect('wallet:charge')

    return render(request, 'wallet/charge.html', {'wallet': wallet})


# ============================================================
#  برداشت وجه -- سمت کاربر
# ============================================================

@never_cache
@login_required
def wallet_withdraw(request):
    """ثبت درخواست برداشت به شبا.

    این ویو پول را جابه‌جا نمی‌کند؛ فقط درخواست می‌سازد و موجودی را نگه
    می‌دارد. واریز واقعی را خزانه‌دار از پنل انجام می‌دهد.
    """
    if request.user.user_type == 'vip':
        messages.error(request, 'کاربران ویژه به این بخش دسترسی ندارند.')
        return redirect('matches:home')

    if not is_withdrawal_enabled():
        messages.error(request, WITHDRAWAL_DISABLED_MESSAGE)
        return redirect('wallet:dashboard')

    withdrawable = get_withdrawable_amount(request.user)
    pending = WithdrawalRequest.objects.filter(
        user=request.user, status__in=WithdrawalRequest.OPEN_STATUSES
    ).first()

    # مقادیری که اگر فرم رد شد، دوباره در آن نشان داده شوند تا کاربر مجبور
    # به تایپ دوباره‌ی شبا نباشد.
    form = {
        'amount': request.POST.get('amount', '') if request.method == 'POST' else '',
        'iban': request.POST.get('iban', '') if request.method == 'POST' else '',
        'account_holder': (request.POST.get('account_holder', '') if request.method == 'POST'
                           else (request.user.get_full_name() or '').strip()),
    }

    def _render(error=None):
        if error:
            messages.error(request, error)
        return render(request, 'wallet/withdraw.html', {
            'withdrawable': withdrawable,
            'pending': pending,
            'min_amount': MIN_WITHDRAWAL_AMOUNT,
            'form': form,
        })

    if request.method != 'POST':
        return _render()

    if pending:
        return _render('شما یک درخواست برداشت در جریان دارید؛ تا تعیین تکلیف آن '
                       'نمی‌توانید درخواست تازه‌ای ثبت کنید.')

    if withdrawable < MIN_WITHDRAWAL_AMOUNT:
        return _render(f'مبلغ قابل برداشت شما کمتر از حداقل مجاز '
                       f'({MIN_WITHDRAWAL_AMOUNT:,} ریال) است.')

    try:
        amount = int(str(request.POST.get('amount', '')).translate(
            str.maketrans('۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩', '01234567890123456789')
        ).replace(',', '').replace('٬', '').strip())
    except (TypeError, ValueError):
        return _render('مبلغ را به عدد وارد کنید.')

    if amount < MIN_WITHDRAWAL_AMOUNT:
        return _render(f'حداقل مبلغ برداشت {MIN_WITHDRAWAL_AMOUNT:,} ریال است.')
    if amount > withdrawable:
        return _render(f'حداکثر مبلغ قابل برداشت شما {withdrawable:,} ریال است.')

    iban = normalize_iban(request.POST.get('iban'))
    if not is_valid_iban(iban):
        return _render('شماره شبا معتبر نیست. شبا باید ۲۴ رقم بعد از IR داشته باشد.')

    holder = (request.POST.get('account_holder') or '').strip()
    if len(holder) < 3:
        return _render('نام صاحب حساب را کامل وارد کنید.')

    try:
        req = WithdrawalRequest.create_for(request.user, amount, iban, holder)
    except ValueError:
        # موجودی بین بارگذاری فرم و ارسال آن خرج شده است.
        return _render('موجودی کیف پول شما تغییر کرده است؛ لطفاً دوباره تلاش کنید.')

    messages.success(
        request,
        f'درخواست برداشت #{req.pk} به مبلغ {amount:,} ریال ثبت شد. '
        'پس از بررسی و تأیید، مبلغ به حساب اعلامی شما واریز می‌شود.'
    )
    return redirect('wallet:dashboard')


# ============================================================
#  برداشت وجه -- پنل مدیریت
# ============================================================

@never_cache
@staff_member_required
def admin_withdrawal_list(request):
    """صف بررسی درخواست‌های برداشت.

    ترتیب عمداً «قدیمی‌ترینِ در انتظار، اول» است: کسی که زودتر درخواست داده
    نباید پشت درخواست‌های تازه بماند.
    """
    status = request.GET.get('status', 'open')
    qs = WithdrawalRequest.objects.select_related('user', 'processed_by')

    if status == 'open':
        qs = qs.filter(status__in=WithdrawalRequest.OPEN_STATUSES).order_by('created_at')
    elif status in dict(WithdrawalRequest.STATUS_CHOICES):
        qs = qs.filter(status=status)
    # 'all' -> بدون فیلتر

    q = (request.GET.get('q') or '').strip()
    if q:
        from django.db.models import Q
        digits = q.translate(str.maketrans('۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩', '01234567890123456789'))
        qs = qs.filter(
            Q(user__username__icontains=q) | Q(user__phone_number__icontains=digits)
            | Q(user__national_code__icontains=digits) | Q(iban__icontains=digits)
            | Q(account_holder__icontains=q)
        )

    counts = {
        'pending': WithdrawalRequest.objects.filter(status='pending').count(),
        'approved': WithdrawalRequest.objects.filter(status='approved').count(),
    }
    open_total = WithdrawalRequest.objects.filter(
        status__in=WithdrawalRequest.OPEN_STATUSES
    ).aggregate(s=Sum('amount'))['s'] or 0
    paid_total = WithdrawalRequest.objects.filter(
        status='paid'
    ).aggregate(s=Sum('amount'))['s'] or 0

    paginator = Paginator(qs, 50)
    try:
        page = paginator.page(request.GET.get('page', 1))
    except PageNotAnInteger:
        page = paginator.page(1)
    except EmptyPage:
        page = paginator.page(paginator.num_pages)

    return render(request, 'wallet/admin_withdrawals.html', {
        'requests': page,
        'status': status,
        'q': q,
        'counts': counts,
        'open_total': open_total,
        'paid_total': paid_total,
        'withdrawal_enabled': is_withdrawal_enabled(),
    })


@staff_member_required
def admin_withdrawal_action(request, request_id):
    """تأیید / ثبت واریز / رد یک درخواست."""
    if request.method != 'POST':
        return redirect('wallet:admin_withdrawal_list')

    wr = get_object_or_404(WithdrawalRequest, pk=request_id)
    action = request.POST.get('action')
    note = (request.POST.get('note') or '').strip()

    if action == 'approve':
        ok, err = wr.approve(request.user, note=note)
        done = f'درخواست #{wr.pk} تأیید شد؛ حالا در انتظار واریز است.'
    elif action == 'paid':
        bank_ref = (request.POST.get('bank_reference') or '').strip()
        if not bank_ref:
            messages.error(request, 'برای ثبت واریز، شماره پیگیری بانکی الزامی است.')
            return redirect('wallet:admin_withdrawal_list')
        ok, err = wr.mark_paid(request.user, bank_reference=bank_ref, note=note)
        done = f'واریز درخواست #{wr.pk} ثبت شد.'
    elif action == 'reject':
        if not note:
            messages.error(request, 'برای رد درخواست، ذکر دلیل الزامی است '
                                    '(همان متن برای کاربر نمایش داده می‌شود).')
            return redirect('wallet:admin_withdrawal_list')
        ok, err = wr.reject(request.user, reason=note)
        done = f'درخواست #{wr.pk} رد شد و مبلغ {wr.amount:,} ریال به کیف پول کاربر برگشت.'
    else:
        messages.error(request, 'درخواست نامعتبر است.')
        return redirect('wallet:admin_withdrawal_list')

    if ok:
        messages.success(request, done)
    else:
        messages.warning(request, err)

    # کاربر را به همان فیلتر/صفحه‌ای برمی‌گردانیم که از آن آمده بود، وگرنه
    # بعد از هر تأیید باید دوباره فیلترها را بچیند.
    back = (request.POST.get('back_query') or '').lstrip('?')
    url = reverse('wallet:admin_withdrawal_list')
    return redirect(f'{url}?{back}' if back else url)