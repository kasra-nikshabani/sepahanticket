"""Private inbox; opening and marking notifications never happens through GET."""
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_POST
from .models import Notification
from .notifications import internal_notification_url


@login_required
@never_cache
@require_GET
def inbox(request):
    rows = request.user.notifications.all()
    unread_only = request.GET.get('state') == 'unread'
    if unread_only:
        rows = rows.filter(read_at__isnull=True)
    return render(request, 'accounts/notifications.html', {
        'page_obj': Paginator(rows, 20).get_page(request.GET.get('page')),
        'unread_only': unread_only,
    })


@login_required
@require_POST
def open_notification(request, notification_id):
    notification = get_object_or_404(Notification, pk=notification_id, recipient=request.user)
    request.user.notifications.filter(pk=notification.pk, read_at__isnull=True).update(read_at=timezone.now())
    url = notification.action_url
    return redirect(url if internal_notification_url(url) else 'accounts:notifications')


@login_required
@require_POST
def mark_all_read(request):
    request.user.notifications.filter(read_at__isnull=True).update(read_at=timezone.now())
    return redirect('accounts:notifications')
