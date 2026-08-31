# wallet/views.py
from django.core.paginator import Paginator, PageNotAnInteger, EmptyPage
from django.db.models import Sum
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.views.decorators.cache import never_cache

from .models import Wallet, Transaction, is_wallet_enabled, WALLET_DISABLED_MESSAGE


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
    if not is_wallet_enabled():
        messages.error(request, WALLET_DISABLED_MESSAGE)
        return redirect('wallet:dashboard')

    wallet = get_object_or_404(Wallet, user=request.user)

    if request.method == 'POST':
        # این مسیر دیگر پردازشی انجام نمی‌دهد؛ فرم صفحه باید مستقیم به
        # payments:payment_request ارسال شود (طبق تمپلیت فعلی charge.html).
        messages.info(request, 'برای شارژ کیف پول از دکمه‌ی «پرداخت و شارژ» استفاده کنید.')
        return redirect('wallet:charge')

    return render(request, 'wallet/charge.html', {'wallet': wallet})