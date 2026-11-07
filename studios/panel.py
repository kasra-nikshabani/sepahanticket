from django import forms
from django.contrib import messages
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q,Count,Sum
from django.shortcuts import get_object_or_404,redirect
from django.urls import reverse
from django.utils import timezone
from accounts.management_views import managed,show,audit
from accounts.notifications import notify
from .models import Studio,Booking
from .services import lock_studio,publication_errors,cancel_booking


class ReviewForm(forms.Form):
    version=forms.CharField(widget=forms.HiddenInput)
    note=forms.CharField(required=False,max_length=2000,label='پیام برای صاحب پلاتو',widget=forms.Textarea(attrs={'rows':3,'class':'edu-input'}))


@managed
def studios(request):
    rows=Studio.objects.select_related('owner').annotate(booking_count=Count('bookings',filter=Q(bookings__status='confirmed'))).order_by('-created_at','-pk')
    state=request.GET.get('state','');query=request.GET.get('q','').strip()[:120]
    if state in Studio.Status.values: rows=rows.filter(status=state)
    if query: rows=rows.filter(Q(title__icontains=query)|Q(city__icontains=query)|Q(district__icontains=query))
    return show(request,'studios','studios','مدیریت پلاتوها',page_obj=Paginator(rows,20).get_page(request.GET.get('page')),state=state,query=query,states=Studio.Status.choices,
        rental_revenue=Booking.objects.filter(status='confirmed').aggregate(total=Sum('paid_rial'))['total'] or 0)


@managed
def review(request,studio_id):
    with transaction.atomic():
        # Same studio lock as rentals: publication and refunds cannot race a booking.
        studio=lock_studio(studio_id) if request.method=='POST' and Studio.objects.filter(pk=studio_id).exists() else get_object_or_404(Studio.objects.select_related('owner'),pk=studio_id)
        form=ReviewForm(request.POST if request.method=='POST' else None,initial={'version':studio.updated_at.isoformat()})
        if request.method=='POST' and form.is_valid():
            action=request.POST.get('action','');note=form.cleaned_data['note'].strip()
            if form.cleaned_data['version']!=studio.updated_at.isoformat(): form.add_error(None,'اطلاعات تغییر کرده است؛ صفحه را تازه‌سازی کنید.')
            elif action!='approve' and not note: form.add_error('note','علت تصمیم یا لغو را بنویسید.')
            elif action=='approve' and (studio.status!='pending' or not studio.owner.is_active): form.add_error(None,'فقط درخواست در انتظار بررسیِ حساب فعال قابل تأیید است.')
            elif action=='approve' and publication_errors(studio): form.add_error(None,' '.join(publication_errors(studio)))
            elif action=='revision' and studio.status!='pending': form.add_error(None,'فقط درخواست در انتظار بررسی قابل بازگشت است.')
            elif action in ('close','open','pause') and studio.status!='published': form.add_error(None,'ابتدا پلاتو باید منتشر شود.')
            elif action=='reopen' and studio.status!='paused': form.add_error(None,'این پلاتو متوقف نیست.')
            elif action not in ('approve','revision','pause','reopen','close','open','refund'): form.add_error(None,'عملیات نامعتبر است.')
            else:
                if action=='refund':
                    from django.core.exceptions import ValidationError
                    from django.http import Http404
                    try: booking=get_object_or_404(Booking,studio=studio,pk=request.POST.get('booking_id'))
                    except (ValueError,ValidationError): raise Http404
                    try: cancel_booking(booking.pk,note)
                    except ValueError as error: form.add_error(None,str(error))
                    else:
                        audit(request,studio,f'لغو و بازپرداخت رزرو {booking.pk}: {note}')
                        messages.success(request,'رزرو لغو شد، مبلغ به کیف پول برگشت و ساعت‌ها آزاد شدند.');return redirect('management:studio_detail',studio.pk)
                else:
                    if action in ('approve','revision','pause','reopen'): studio.status={'approve':'published','revision':'revision','pause':'paused','reopen':'pending'}[action]
                    if action=='approve' and not studio.published_at: studio.published_at=timezone.now()
                    if action in ('close','open'): studio.booking_open=action=='open'
                    studio.review_note=note;studio.save()
                    audit(request,studio,f'مدیریت پلاتو: {action}. {note}')
                    notify(studio.owner,'publication' if action=='approve' else 'review','پیام مدیریت دربارهٔ پلاتو',f'«{studio.title}»؛ {studio.get_status_display()}. {note}',reverse('studios:manage',args=[studio.pk]),f'studio-review:{studio.pk}:{studio.updated_at.isoformat()}')
                    messages.success(request,'تصمیم ثبت شد و صاحب پلاتو پیام دریافت کرد.');return redirect('management:studio_detail',studio.pk)
    return show(request,'studio_detail','studios',studio.title,studio=studio,form=form,page_obj=Paginator(studio.bookings.all(),25).get_page(request.GET.get('page')),
        photos=studio.photos.filter(is_active=True))
