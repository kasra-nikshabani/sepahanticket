from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods

from .models import ArtCardApplication


@login_required
@never_cache
@require_http_methods(['GET', 'POST'])
def art_card(request):
    application = ArtCardApplication.objects.filter(user=request.user).first()
    if request.method == 'POST':
        if request.POST.get('consent') != 'on':
            messages.error(request, 'برای ثبت درخواست، موافقت با استفاده از اطلاعات حساب لازم است.')
            return redirect('accounts:art_card')
        if application and application.status in ('requested', 'sent_to_bank', 'active'):
            messages.info(request, 'درخواست هنرکارتت در حال پیگیری است؛ وضعیت را همین صفحه می‌بینی.')
            return redirect('accounts:art_card')
        if not request.user.is_phone_verified:
            messages.error(request, 'برای ثبت درخواست، ابتدا شمارهٔ همراهت را تأیید کن.')
            return redirect('accounts:art_card')
        if not (request.user.get_full_name() or '').strip() or not (request.user.phone_number or '').strip():
            messages.error(request, 'ابتدا نام و نام خانوادگی و شمارهٔ همراه را در حساب کاربری کامل کن.')
            return redirect('accounts:edit_profile')
        application, _ = ArtCardApplication.objects.get_or_create(user=request.user)
        application.status = 'requested'
        application.admin_note = ''
        application.bank_reference = ''
        application.card_last_four = ''
        application.save(update_fields=['status', 'admin_note', 'bank_reference', 'card_last_four', 'updated_at'])
        messages.success(request, 'درخواست هنرکارت ثبت شد. پس از بررسی، وضعیت و راهنمای ادامهٔ کار را همین‌جا می‌بینی.')
        return redirect('accounts:art_card')
    return render(request, 'accounts/art_card.html', {'application': application})
