from django.contrib import messages
from django.db import transaction
from django.db.models import Count, Q
from django.http import HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect
from django.utils import timezone
from django.urls import reverse
from django.views.decorators.http import require_GET, require_POST
from matches.models import Event
from accounts.management_views import managed, show, paginate, audit
from accounts.notifications import notify
from .models import ArtistProfile, ArtistCredit
from .forms import ArtistReviewForm, CreditForm


@managed
@require_GET
def artists(request):
    rows = ArtistProfile.objects.select_related('owner').annotate(follower_count=Count('follows', distinct=True))
    query = request.GET.get('q', '').strip()[:100]
    state = request.GET.get('state', '')
    selected_event = Event.objects.filter(pk=request.GET['event'], category__in=['theater', 'concert', 'event']).first() if request.GET.get('event', '').isdigit() else None
    if query:
        rows = rows.filter(Q(display_name__icontains=query) | Q(owner__first_name__icontains=query) | Q(owner__last_name__icontains=query))
    if state in ArtistProfile.Status.values:
        rows = rows.filter(status=state)
    return show(request, 'artists', 'artists', 'هنرمندان دیدآور', page_obj=paginate(request, rows.order_by('-updated_at')),
        query=query, selected_state=state, states=ArtistProfile.Status.choices,
        awaiting_count=ArtistProfile.objects.filter(status='pending').count(), selected_event=selected_event)


@managed
def artist_detail(request, artist_id):
    artist = get_object_or_404(ArtistProfile.objects.select_related('owner'), pk=artist_id)
    action = request.POST.get('action', '')
    review_form = ArtistReviewForm(request.POST if request.method == 'POST' and action != 'add_credit' else None)
    credit_form = CreditForm(request.POST if request.method == 'POST' and action == 'add_credit' else None,
        initial={'event': request.GET.get('event', '') if request.GET.get('event', '').isdigit() else None})
    if request.method == 'POST':
        with transaction.atomic():
            artist = ArtistProfile.objects.select_for_update().select_related('owner').get(pk=artist.pk)
            if action == 'add_credit':
                if credit_form.is_valid():
                    event = credit_form.cleaned_data['event']
                    role = credit_form.cleaned_data['role']
                    credit, created = ArtistCredit.objects.get_or_create(artist=artist, event=event, role=role,
                        defaults={'created_by': request.user})
                    if created:
                        audit(request, credit, 'ارتباط هنرمند و برنامه برای تأیید به هنرمند ارسال شد.', created=True)
                        notify(artist.owner, 'artist', 'نقش شما در یک برنامه نیاز به تأیید دارد',
                            f'برنامهٔ «{event.title}»؛ نقش «{role}». این ارتباط پس از تأیید شما در سایت نمایش داده می‌شود.',
                            reverse('artists:edit'), f'artist-credit:{credit.pk}:requested')
                        messages.success(request, 'ارتباط برای تأیید به هنرمند ارسال شد.')
                        return redirect('management:artist_detail', artist.pk)
                    credit_form.add_error('role', 'این نقش برای هنرمند قبلاً ثبت شده است.')
            elif action in ('approve', 'revision', 'hide', 'show'):
                if review_form.is_valid():
                    note = review_form.cleaned_data['note'].strip()
                    if action == 'approve' and (artist.status != 'pending' or len(artist.biography.strip()) < 20 or not artist.owner.is_active):
                        review_form.add_error(None, 'فقط درخواست کامل و در انتظار تأییدِ کاربر فعال قابل تأیید است.')
                    elif action in ('revision', 'hide') and not note:
                        review_form.add_error('note', 'علت تغییر وضعیت را برای هنرمند بنویسید.')
                    elif action == 'show' and artist.status != 'approved':
                        review_form.add_error(None, 'ابتدا پروفایل باید تأیید شود.')
                    else:
                        if action == 'approve':
                            artist.status = 'approved'
                        elif action == 'revision':
                            artist.status = 'revision'
                        elif action == 'hide':
                            artist.is_visible = False
                        elif action == 'show':
                            artist.is_visible = True
                        artist.review_note = note
                        artist.reviewed_by = request.user
                        artist.reviewed_at = timezone.now()
                        artist.save()
                        audit(request, artist, f'وضعیت پروفایل هنرمند تغییر کرد: {action}')
                        notify(artist.owner, 'artist', 'نتیجهٔ بررسی پروفایل هنری شما',
                            f'وضعیت: {artist.get_status_display()}. ' + ('نمایش عمومی متوقف شد. ' if not artist.is_visible else '') + note,
                            reverse('artists:edit'), f'artist-review:{artist.pk}:{artist.updated_at.isoformat()}')
                        messages.success(request, 'وضعیت پروفایل و پیام برای هنرمند ثبت شد.')
                        return redirect('management:artist_detail', artist.pk)
            else:
                return HttpResponseBadRequest('عملیات نامعتبر است.')
    credits = artist.event_credits.select_related('event').order_by('-created_at')
    return show(request, 'artist_detail', 'artists', artist.display_name, artist=artist,
        review_form=review_form, credit_form=credit_form, credits=credits,
        follower_count=artist.follows.count())


@managed
@require_POST
def remove_credit(request, credit_id):
    with transaction.atomic():
        credit = get_object_or_404(ArtistCredit.objects.select_for_update().select_related('artist', 'event'), pk=credit_id)
        artist_id = credit.artist_id
        audit(request, credit, 'ارتباط هنرمند و برنامه در پنل مدیریت حذف شد.')
        notify(credit.artist.owner, 'artist', 'ارتباط با برنامه اصلاح شد',
            f'نقش «{credit.role}» در برنامهٔ «{credit.event.title}» توسط مدیریت حذف شد. برای پرسش یا اصلاح، تیکت ارسال کنید.',
            reverse('artists:edit'), f'artist-credit:{credit.pk}:removed')
        credit.delete()
    messages.success(request, 'ارتباط هنرمند و برنامه حذف شد.')
    return redirect('management:artist_detail', artist_id)
