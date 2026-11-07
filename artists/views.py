from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Avg, Count, Prefetch, Q
from django.http import HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_POST, require_http_methods
from matches.models import Event, Match
from matches.event_views import prepare_event
from matches.event_search import clean_query, matching_artists
from accounts.models import User
from .models import ArtistProfile, ArtistFollow, ArtistCredit
from .forms import ArtistProfileForm
from .services import public_artists, public_credits


def artist_rows():
    return public_artists().annotate(follower_count=Count('follows', distinct=True)).order_by('display_name', 'pk')


def programme_rows(rows):
    sessions = Match.objects.filter(is_active=True, is_cancelled=False, date_time__gt=timezone.now()).select_related('stadium', 'event').order_by('date_time')
    return rows.filter(is_active=True).exclude(category='sport').annotate(rating_average=Avg('ratings__score'),
        rating_count=Count('ratings', distinct=True)).prefetch_related(Prefetch('sessions', queryset=sessions, to_attr='upcoming_sessions'))


@require_GET
def directory(request):
    query = clean_query(request.GET.get('q', ''))
    rows = matching_artists(query).annotate(follower_count=Count('follows', distinct=True)) if query else artist_rows()
    discipline = request.GET.get('discipline', '')
    if discipline in ArtistProfile.Discipline.values:
        rows = rows.filter(discipline=discipline)
    else:
        discipline = ''
    return render(request, 'artists/directory.html', {'page_obj': Paginator(rows, 12).get_page(request.GET.get('page')),
        'query': query, 'discipline': discipline, 'disciplines': ArtistProfile.Discipline.choices})


@never_cache
@require_GET
def detail(request, artist_id):
    artist = get_object_or_404(artist_rows(), pk=artist_id)
    credits = public_credits().filter(artist=artist).select_related('event')
    events = programme_rows(Event.objects.filter(pk__in=credits.values('event_id'))).order_by('-created_at')
    upcoming, past, announced = [], [], []
    roles = {}
    for credit in credits:
        roles.setdefault(credit.event_id, []).append(credit.role)
    for event in events:
        prepare_event(event)
        event.artist_roles = roles[event.pk]
        if event.upcoming_sessions:
            upcoming.append(event)
        elif event.sessions.exists():
            past.append(event)
        else:
            announced.append(event)
    follow = ArtistFollow.objects.filter(artist=artist, user=request.user).first() if request.user.is_authenticated else None
    return render(request, 'artists/detail.html', {'artist': artist, 'follow': follow,
        'upcoming_events': upcoming, 'past_events': past, 'announced_events': announced})


@login_required
@never_cache
@require_http_methods(['GET', 'POST'])
def edit_profile(request):
    artist = ArtistProfile.objects.filter(owner=request.user).first()
    initial = {'display_name': request.user.get_full_name()} if artist is None else None
    action = request.POST.get('action', 'save')
    form = ArtistProfileForm(request.POST if request.method == 'POST' else None,
        request.FILES or None, instance=artist, initial=initial, submit_review=action == 'submit')
    if request.method == 'POST':
        if action not in ('save', 'submit'):
            return HttpResponseBadRequest('عملیات نامعتبر است.')
        if form.is_valid():
            with transaction.atomic():
                User.objects.select_for_update().get(pk=request.user.pk)
                current = ArtistProfile.objects.select_for_update().filter(owner=request.user).first()
                if current and (not artist or current.updated_at != artist.updated_at):
                    messages.error(request, 'پروفایل در پنجرهٔ دیگری تغییر کرده است؛ دوباره بررسی و ذخیره کنید.')
                    return redirect('artists:edit')
                previous_name = artist.display_name if artist else None
                # ModelForm validation mutates its instance; compare with the locked DB record.
                previous_name = current.display_name if current else previous_name
                obj = form.save(commit=False)
                obj.owner = request.user
                if obj.status == ArtistProfile.Status.APPROVED and previous_name != obj.display_name:
                    obj.status = ArtistProfile.Status.PENDING
                    obj.review_note = ''
                if action == 'submit' and obj.status != ArtistProfile.Status.APPROVED:
                    obj.status = ArtistProfile.Status.PENDING
                    obj.review_note = ''
                obj.save()
            messages.success(request, 'پروفایل برای بررسی مدیریت ارسال شد.' if obj.status == 'pending' else 'اطلاعات هنری شما ذخیره شد.')
            return redirect('artists:edit')
    credits = artist.event_credits.select_related('event').order_by('-created_at') if artist else []
    return render(request, 'artists/edit.html', {'form': form, 'artist': artist, 'credits': credits})


@login_required
@require_POST
def follow_action(request, artist_id):
    action = request.POST.get('action')
    if action == 'unfollow':
        own_follow = ArtistFollow.objects.filter(user=request.user, artist_id=artist_id).select_related('artist__owner').first()
        artist = own_follow.artist if own_follow else get_object_or_404(public_artists(), pk=artist_id)
        ArtistFollow.objects.filter(user=request.user, artist=artist).delete()
        messages.success(request, 'دنبال‌کردن این هنرمند متوقف شد.')
        return redirect(artist if artist.is_public else 'artists:following')
    artist = get_object_or_404(public_artists(), pk=artist_id)
    if artist.owner_id == request.user.pk:
        return HttpResponseBadRequest('امکان دنبال‌کردن پروفایل خودتان وجود ندارد.')
    if action == 'follow':
        ArtistFollow.objects.get_or_create(user=request.user, artist=artist)
        messages.success(request, 'هنرمند به دنبال‌شده‌های شما اضافه شد.')
    elif action == 'notifications':
        updated = ArtistFollow.objects.filter(user=request.user, artist=artist).update(notify_events=request.POST.get('notify_events') == 'on')
        if not updated:
            return HttpResponseBadRequest('ابتدا هنرمند را دنبال کنید.')
        messages.success(request, 'تنظیم اعلان‌های این هنرمند ذخیره شد.')
    else:
        return HttpResponseBadRequest('عملیات نامعتبر است.')
    return redirect(artist)


@login_required
@never_cache
@require_POST
def confirm_credit(request, credit_id):
    with transaction.atomic():
        credit = get_object_or_404(ArtistCredit.objects.select_for_update().select_related('artist', 'event'),
            pk=credit_id, artist__owner=request.user)
        action = request.POST.get('action')
        if action not in ('accept', 'decline'):
            return HttpResponseBadRequest('عملیات نامعتبر است.')
        if credit.status != ArtistCredit.Status.PENDING:
            return HttpResponseBadRequest('این ارتباط قبلاً بررسی شده است؛ برای اصلاح، تیکت ارسال کنید.')
        credit.status = ArtistCredit.Status.ACCEPTED if action == 'accept' else ArtistCredit.Status.DECLINED
        credit.confirmed_at = timezone.now()
        credit.save(update_fields=['status', 'confirmed_at'])
    messages.success(request, 'پاسخ شما دربارهٔ نقش در برنامه ثبت شد.')
    return redirect('artists:edit')


@login_required
@never_cache
@require_GET
def following(request):
    follows = ArtistFollow.objects.filter(user=request.user).select_related('artist__owner')
    credits = public_credits().filter(artist_id__in=follows.values('artist_id'))
    events = programme_rows(Event.objects.filter(pk__in=credits.values('event_id'),
        sessions__date_time__gt=timezone.now(), sessions__is_active=True, sessions__is_cancelled=False).distinct()).order_by('-created_at', '-pk')
    page = Paginator(events, 10).get_page(request.GET.get('page'))
    for event in page:
        prepare_event(event)
    return render(request, 'artists/following.html', {'page_obj': page,
        'follows': follows, 'following_count': follows.count()})
