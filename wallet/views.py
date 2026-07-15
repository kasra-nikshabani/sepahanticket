# wallet/views.py
from django.core.paginator import Paginator, PageNotAnInteger, EmptyPage
from django.db.models import Sum
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db import transaction
from decimal import Decimal
from django.utils import timezone
from django.views.decorators.cache import never_cache

from .models import Wallet, Transaction


@login_required
def wallet_dashboard(request):
    """نمایش کیف پول و تاریخچه تراکنش‌ها با صفحه‌بندی"""
    if request.user.user_type == 'vip':
        messages.error(request, 'کاربران ویژه به این بخش دسترسی ندارند.')
        return redirect('matches:home')

    wallet, created = Wallet.objects.get_or_create(user=request.user)

    # ===== دریافت تراکنش‌ها =====
    transactions_list = Transaction.objects.filter(
        user=request.user
    ).order_by('-created_at')

    # ===== صفحه‌بندی =====
    paginator = Paginator(transactions_list, 5)
    page = request.GET.get('page', 1)

    try:
        transactions = paginator.page(page)
    except PageNotAnInteger:
        transactions = paginator.page(1)
    except EmptyPage:
        transactions = paginator.page(paginator.num_pages)

    # ============================================================
    # ===== محاسبه آمار دقیق =====
    # ============================================================

    # ===== کل شارژها (واریز) =====
    total_deposits = Transaction.objects.filter(
        user=request.user,
        transaction_type='deposit'
    ).aggregate(total=Sum('amount'))['total'] or 0

    # ===== کل برداشت‌ها (فقط withdraw و ticket_purchase) =====
    total_withdrawals = Transaction.objects.filter(
        user=request.user,
        transaction_type__in=['withdraw', 'ticket_purchase']
    ).aggregate(total=Sum('amount'))['total'] or 0

    # ===== خرید بلیط (برای نمایش جداگانه) =====
    total_ticket_purchases = Transaction.objects.filter(
        user=request.user,
        transaction_type='ticket_purchase'
    ).aggregate(total=Sum('amount'))['total'] or 0

    # ===== بازگشت وجه =====
    total_refunds = Transaction.objects.filter(
        user=request.user,
        transaction_type='refund'
    ).aggregate(total=Sum('amount'))['total'] or 0

    # ===== تعداد کل تراکنش‌ها =====
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
    }
    return render(request, 'wallet/dashboard.html', context)


@login_required
def wallet_charge(request):
    """شارژ کیف پول"""
    if request.user.user_type == 'vip':
        messages.error(request, 'کاربران ویژه به این بخش دسترسی ندارند.')
        return redirect('matches:home')

    wallet = get_object_or_404(Wallet, user=request.user)

    if request.method == 'POST':
        amount = request.POST.get('amount')
        try:
            amount = int(amount)
            if amount <= 0:
                messages.error(request, 'مبلغ شارژ باید بزرگتر از صفر باشد.')
                return redirect('wallet:charge')
            if amount > 10000000:
                messages.error(request, 'حداکثر مبلغ شارژ ۱۰ میلیون تومان است.')
                return redirect('wallet:charge')
        except ValueError:
            messages.error(request, 'مبلغ نامعتبر است.')
            return redirect('wallet:charge')

        # اینجا می‌توانید درگاه پرداخت واقعی را متصل کنید
        # فعلاً به‌صورت شبیه‌سازی شده
        with transaction.atomic():
            wallet.add_balance(
                amount=amount,
                description=f"شارژ کیف پول به مبلغ {amount:,} تومان (شبیه‌سازی)",
                reference_id=f"SIM-{timezone.now().timestamp()}"
            )
        messages.success(request, f'کیف پول شما با موفقیت به مبلغ {amount:,} تومان شارژ شد.')
        return redirect('wallet:dashboard')

    return render(request, 'wallet/charge.html', {'wallet': wallet})
