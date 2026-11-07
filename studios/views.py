import uuid
from datetime import datetime, time, timedelta
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import transaction, OperationalError
from django.db.models import Count,Q,Sum,CharField,OuterRef,Subquery,IntegerField
from django.db.models.functions import Cast, TruncDate
from django.core.exceptions import ValidationError
from django.http import Http404
from django.shortcuts import get_object_or_404,redirect,render
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_http_methods, require_POST
from matches.event_search import clean_query,search_expression,normalized
from wallet.models import Wallet,is_wallet_enabled,is_wallet_charge_enabled
from accounts.management_forms import SessionDate
from .forms import StudioForm,ScheduleForm,SlotForm,BookingForm
from .models import Studio,StudioPhoto,StudioSlot,Booking
from .services import public_studios,publication_errors,build_schedule,change_slot,book_slots


def owned(request,studio_id,lock=False):
    rows=Studio.objects.select_for_update() if lock else Studio.objects.all()
    if not request.user.is_staff: rows=rows.filter(owner=request.user)
    return get_object_or_404(rows,pk=studio_id)


def accessible(request,studio_id):
    studio=get_object_or_404(Studio.objects.select_related('owner'),pk=studio_id)
    if request.user.is_authenticated and (request.user.is_staff or studio.owner_id==request.user.pk or studio.bookings.filter(renter=request.user).exists()): return studio
    if not public_studios().filter(pk=studio.pk).exists(): raise Http404
    return studio


def day_context(request,studio,scheduled_only=False):
    day=timezone.localdate()
    if not request.GET.get('day'):
        upcoming=studio.slots.filter(starts_at__gt=timezone.now()).order_by('starts_at').first()
        if upcoming: day=timezone.localtime(upcoming.starts_at).date()
    if request.GET.get('day'):
        try: day=SessionDate().clean(request.GET['day'])
        except (ValueError,ValidationError): day=timezone.localdate()
    scheduled_days = []
    if scheduled_only:
        today_start = timezone.make_aware(datetime.combine(timezone.localdate(), time.min))
        scheduled_days = list(studio.slots.filter(starts_at__gte=today_start)
            .annotate(calendar_day=TruncDate('starts_at', tzinfo=timezone.get_current_timezone()))
            .order_by('calendar_day').values_list('calendar_day', flat=True).distinct())
        if day not in scheduled_days:
            day = scheduled_days[0] if scheduled_days else timezone.localdate()
    start=timezone.make_aware(datetime.combine(day,time.min)); end=start+timedelta(days=1)
    # Existing Jalali template filters accept localized datetimes, not dates.
    days = ([timezone.make_aware(datetime.combine(item, time.min)) for item in scheduled_days]
            if scheduled_only else [start+timedelta(days=i) for i in range(-3,4)])
    return {'scheduled_only':scheduled_only,'selected_day':start,'calendar_days':days,'slots':studio.slots.filter(starts_at__gte=start,starts_at__lt=end).select_related('booking')}


@require_GET
def catalogue(request):
    rows=public_studios();query=clean_query(request.GET.get('q',''));city=clean_query(request.GET.get('city',''))[:80]
    if query:
        rows=rows.alias(_amenities_text=Cast('amenities',CharField())).alias(_search=search_expression('title','city','district','_amenities_text'))
        for term in query.split(maxsplit=5):
            if normalized(term): rows=rows.filter(_search__contains=normalized(term))
    if city: rows=rows.alias(_city=search_expression('city')).filter(_city=normalized(city))
    rows=rows.annotate(available_count=Count('slots',filter=Q(slots__state='open',slots__booking__isnull=True,slots__starts_at__gt=timezone.now()))).order_by('-created_at','-pk')
    params=request.GET.copy();params.pop('page',None)
    return render(request,'studios/catalogue.html',{'page_obj':Paginator(rows,12).get_page(request.GET.get('page')),'query':query,'city':city,
        'cities':public_studios().exclude(city='').order_by('city').values_list('city',flat=True).distinct(),'filter_query':params.urlencode()})


@never_cache
@require_GET
def detail(request,studio_id):
    studio=accessible(request,studio_id)
    now=timezone.now()
    ctx=day_context(request,studio,scheduled_only=True)
    for slot in ctx['slots']: slot.available=slot.starts_at>now and slot.state=='open' and not slot.booking_id and studio.status=='published' and studio.booking_open and studio.owner.is_active
    return render(request,'studios/_calendar.html' if request.headers.get('X-Studio-Calendar') == '1' else 'studios/detail.html',{'studio':studio,'photos':studio.photos.filter(is_active=True),'now':now,
        'privileged':request.user.is_authenticated and (request.user.is_staff or studio.owner_id==request.user.pk),**ctx})


@login_required
@never_cache
@require_http_methods(['GET','POST'])
def checkout(request,studio_id):
    studio=accessible(request,studio_id)
    raw=request.POST.getlist('slots') if request.method=='POST' else request.GET.getlist('slots')
    try: ids=[int(value) for value in raw]
    except (ValueError,TypeError): ids=[]
    if not ids or len(ids)>12 or len(set(ids))!=len(ids):
        messages.error(request,'بین ۱ تا ۱۲ ساعت پشت‌سرهم انتخاب کنید.');return redirect(studio.get_absolute_url()+'#studio-calendar')
    slots=list(studio.slots.filter(pk__in=ids).order_by('starts_at'))
    if len(slots)!=len(ids): raise Http404
    total=sum(slot.price_toman for slot in slots)
    issue=''
    if studio.status!='published' or not studio.booking_open or not studio.owner.is_active: issue='رزرو این پلاتو بسته است.'
    elif studio.owner_id==request.user.pk: issue='برای رزرو خارج از سایت از تقویم مدیریت پلاتو استفاده کنید.'
    elif any(slot.booking_id or slot.state!='open' or slot.starts_at<=timezone.now() for slot in slots): issue='یکی از ساعت‌ها دیگر قابل رزرو نیست.'
    elif timezone.localtime(slots[0].starts_at).date()!=timezone.localtime(slots[-1].starts_at).date() or any(a.ends_at!=b.starts_at for a,b in zip(slots,slots[1:])): issue='ساعت‌ها باید در یک روز و پشت‌سرهم باشند.'
    form=BookingForm(request.POST if request.method=='POST' else None,initial={'token':uuid.uuid4(),'total':total,'renter_name':request.user.get_full_name()})
    if request.method=='POST' and form.is_valid():
        try:
            book_slots(request.user,studio.pk,ids,form.cleaned_data['total'],form.cleaned_data['renter_name'],form.cleaned_data['token'])
        except (ValueError,OperationalError) as error:
            form.add_error(None,str(error) if isinstance(error,ValueError) else 'رزرو دیگری در حال ثبت است؛ چند لحظه بعد دوباره امتحان کنید.')
        else:
            messages.success(request,'رزرو قطعی شد؛ به امید یک تمرین خوب!');return redirect('studios:my_bookings')
    wallet=Wallet.objects.filter(user=request.user).first();balance=wallet.balance if wallet else 0
    return render(request,'studios/checkout.html',{'studio':studio,'slots':slots,'form':form,'total':total,'hours':len(slots),'issue':issue,'balance':balance,
        'shortfall':max(0,total*10-balance),'wallet_enabled':is_wallet_enabled(),'charge_enabled':is_wallet_charge_enabled(),'return_path':request.get_full_path()})


@login_required
@never_cache
@require_GET
def my_bookings(request):
    return render(request,'studios/my_bookings.html',{'page_obj':Paginator(Booking.objects.filter(renter=request.user).select_related('studio'),15).get_page(request.GET.get('page'))})


@login_required
@never_cache
@require_GET
def my_studios(request):
    now=timezone.now()
    rows=Studio.objects.filter(owner=request.user).annotate(
        booking_count=Count('bookings',filter=Q(bookings__status='confirmed')),
        revenue=Sum('bookings__paid_rial',filter=Q(bookings__status='confirmed')),
        next_slot=Subquery(StudioSlot.objects.filter(studio_id=OuterRef('pk'),state='open',booking__isnull=True,starts_at__gt=now)
            .order_by('starts_at').values('starts_at')[:1]),
        open_slot_count=Subquery(StudioSlot.objects.filter(studio_id=OuterRef('pk'),state='open',booking__isnull=True,starts_at__gt=now)
            .order_by().values('studio_id').annotate(total=Count('pk')).values('total')[:1],output_field=IntegerField()),
    ).order_by('-created_at','-pk')
    summary=Studio.objects.filter(owner=request.user).aggregate(
        total=Count('pk'),published=Count('pk',filter=Q(status=Studio.Status.PUBLISHED)),
        pending=Count('pk',filter=Q(status=Studio.Status.PENDING)),revision=Count('pk',filter=Q(status=Studio.Status.REVISION)))
    return render(request,'studios/my_studios.html',{'page_obj':Paginator(rows,12).get_page(request.GET.get('page')),'summary':summary})


@login_required
@never_cache
@require_http_methods(['GET','POST'])
def edit(request,studio_id=None):
    with transaction.atomic():
        studio=owned(request,studio_id,lock=request.method=='POST') if studio_id else Studio(owner=request.user)
        if studio.published_at and not request.user.is_staff:
            messages.info(request,'تغییر معرفی پلاتوی منتشرشده را با تیکت از مدیریت بخواهید. ساعت‌ها را می‌توانید در تقویم مدیریت کنید.')
            return redirect('studios:manage',studio.pk)
        form=StudioForm(request.POST if request.method=='POST' else None,request.FILES or None,instance=studio)
        if request.method=='POST' and form.is_valid():
            if studio.created_at and form.cleaned_data['version']!=studio.updated_at.isoformat(): form.add_error(None,'اطلاعات تغییر کرده است؛ صفحه را تازه‌سازی کنید.')
            else:
                obj=form.save(commit=False)
                if not obj.published_at: obj.status='draft';obj.review_note=''
                obj.save()
                for image in form.cleaned_data['gallery']: StudioPhoto.objects.create(studio=obj,image=image)
                if request.user.is_staff:
                    from accounts.management_views import audit
                    audit(request,obj,'ویرایش معرفی و تصاویر پلاتو')
                messages.success(request,'اطلاعات ذخیره شد؛ حالا ساعت‌های پلاتو را مشخص کنید.');return redirect('studios:manage',obj.pk)
    return render(request,'studios/edit.html',{'studio':studio,'form':form})


@login_required
@never_cache
@require_http_methods(['GET','POST'])
def manage(request,studio_id):
    studio=owned(request,studio_id)
    initial={'start_date':timezone.localdate(),'end_date':timezone.localdate()+timedelta(days=6),'weekdays':['5','6','0','1','2','3','4'],
        'start_time':'10:00','end_time':'22:00','price':studio.hourly_price or None}
    form=ScheduleForm(request.POST if request.method=='POST' else None,initial=initial)
    if request.method=='POST' and form.is_valid():
        try:
            data=form.cleaned_data
            count,skipped=build_schedule(studio.pk,data['start_date'],data['end_date'],data['start_time'],data['end_time'],[int(d) for d in data['weekdays']],data['price'])
        except (ValueError,OperationalError) as error:
            form.add_error(None,str(error) if isinstance(error,ValueError) else 'تقویم در حال تغییر است؛ دوباره امتحان کنید.')
        else:
            if request.user.is_staff:
                from accounts.management_views import audit
                audit(request,studio,f'ساخت {count} ساعت جدید در تقویم پلاتو')
            messages.success(request,f'{count} ساعت ساخته شد؛ {skipped} ساعتِ قبلی بدون تغییر باقی ماند.');return redirect('studios:manage',studio.pk)
    active=studio.bookings.filter(status='confirmed')
    return render(request,'studios/manage.html',{'studio':studio,'form':form,'can_edit':request.user.is_staff or not studio.published_at,
        'booking_count':active.count(),'revenue':active.aggregate(total=Sum('paid_rial'))['total'] or 0,'reserved_hours':active.aggregate(total=Sum('hours'))['total'] or 0,
        'now':timezone.now(),'page_obj':Paginator(studio.bookings.all(),20).get_page(request.GET.get('page')),'photos':studio.photos.filter(is_active=True),**day_context(request,studio)})


@login_required
@require_POST
def submit(request,studio_id):
    with transaction.atomic():
        studio=owned(request,studio_id,lock=True)
        if studio.published_at and not request.user.is_staff: raise Http404
        errors=publication_errors(studio)
        if errors: messages.error(request,' '.join(errors))
        else:
            studio.status='pending';studio.submitted_at=timezone.now();studio.review_note='';studio.save()
            messages.success(request,'پلاتو برای بررسی مدیریت ارسال شد؛ پس از تأیید در سایت دیده می‌شود.')
    return redirect('studios:manage',studio.pk)


@login_required
@never_cache
@require_http_methods(['GET','POST'])
def slot_edit(request,studio_id,slot_id):
    studio=owned(request,studio_id);slot=get_object_or_404(StudioSlot,studio=studio,pk=slot_id)
    if slot.booking_id or slot.starts_at<=timezone.now(): raise Http404
    form=SlotForm(request.POST if request.method=='POST' else None,initial={'state':slot.state,'price':slot.price_toman,'note':slot.private_note})
    if request.method=='POST' and form.is_valid():
        try: change_slot(studio.pk,slot.pk,form.cleaned_data['state'],form.cleaned_data['price'],form.cleaned_data['note'])
        except (ValueError,OperationalError) as error:
            form.add_error(None,str(error) if isinstance(error,ValueError) else 'این ساعت در حال تغییر است؛ چند لحظه بعد دوباره امتحان کنید.')
        else:
            if request.user.is_staff:
                from accounts.management_views import audit
                audit(request,studio,f'تغییر ساعت {slot.pk}: {form.cleaned_data["state"]}')
            messages.success(request,'وضعیت و قیمت این ساعت ذخیره شد.');return redirect('studios:manage',studio.pk)
    return render(request,'studios/slot_edit.html',{'studio':studio,'slot':slot,'form':form})


@login_required
@require_POST
def hide_photo(request,studio_id,photo_id):
    with transaction.atomic():
        studio=owned(request,studio_id,lock=True)
        if studio.published_at and not request.user.is_staff: raise Http404
        photo=get_object_or_404(StudioPhoto,studio=studio,pk=photo_id)
        photo.is_active=False;photo.save(update_fields=['is_active'])
        if not studio.published_at: studio.status='draft'
        studio.save()
        if request.user.is_staff:
            from accounts.management_views import audit
            audit(request,studio,f'پنهان کردن تصویر پلاتو {photo.pk}')
    return redirect('studios:manage',studio.pk)
