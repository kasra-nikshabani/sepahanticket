"""Only confirmed public credits can reach opted-in followers."""
from django.db import transaction
from django.utils import timezone
from django.urls import reverse
from accounts.models import Notification
from .models import ArtistProfile, ArtistFollow, ArtistCredit


def public_artists():
    return ArtistProfile.objects.filter(status=ArtistProfile.Status.APPROVED, is_visible=True, owner__is_active=True)


def public_credits():
    return ArtistCredit.objects.filter(status=ArtistCredit.Status.ACCEPTED,
        artist__status=ArtistProfile.Status.APPROVED, artist__is_visible=True, artist__owner__is_active=True,
        event__is_active=True, event__category__in=['theater', 'concert', 'event'])


@transaction.atomic
def notify_artist_event(event, session=None):
    if not event.is_active or event.category not in ('theater', 'concert', 'event'):
        return
    if session:
        from matches.event_views import prepare_session_status
        prepare_session_status(session)
        if not session.can_purchase:
            return
    elif event.sessions.exists() and not event.sessions.filter(is_active=True, is_cancelled=False, date_time__gt=timezone.now()).exists():
        return
    artists = public_credits().filter(event=event).values('artist_id')
    recipients = ArtistFollow.objects.filter(artist_id__in=artists, notify_events=True, user__is_active=True).exclude(
        user_id__in=public_credits().filter(event=event).values('artist__owner_id')).order_by().values_list('user_id', flat=True).distinct()
    key = f'artist-sale:{session.pk}' if session else f'artist-program:{event.pk}'
    title = 'فروش سانس تازه باز شد' if session else 'اجرای تازه از هنرمندان دنبال‌شده'
    body = f'«{event.title}»؛ ' + ('یک سانس تازه برای خرید بلیط در دسترس است.' if session else 'برنامه‌ای از هنرمندانی که دنبال می‌کنید. اطلاعات اجرا و سانس‌ها را ببینید.')
    rows = [Notification(recipient_id=pk, kind='artist', title=title, body=body,
        action_url=reverse('matches:event_detail', args=[event.pk]) + ('#sessions' if session else ''), dedupe_key=key)
        for pk in recipients.iterator(chunk_size=500)]
    Notification.objects.bulk_create(rows, ignore_conflicts=True, batch_size=500)
