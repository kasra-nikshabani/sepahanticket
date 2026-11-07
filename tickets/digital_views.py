"""Owner-only mobile admission passes using the same gate payload as PDF tickets."""
from io import BytesIO
import qrcode
from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpResponse, FileResponse
from django.conf import settings
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET
from .models import Ticket


def owned_ticket(request, ticket_id):
    return get_object_or_404(Ticket.objects.select_related('user', 'match__event', 'match__stadium', 'seat__row__block'),
        pk=ticket_id, user=request.user, status__in=['paid', 'admin_assigned', 'vip_issued', 'cancelled'])


def pdf_response(ticket):
    """Development serves authorized files directly; production keeps nginx internal delivery."""
    if not ticket.pdf_file:
        raise Http404
    filename = f'ticket_{ticket.ticket_number}.pdf'
    if settings.DEBUG:
        try:
            response = FileResponse(ticket.pdf_file.open('rb'), content_type='application/pdf',
                                    as_attachment=True, filename=filename)
        except (FileNotFoundError, OSError):
            raise Http404
    else:
        response = HttpResponse(content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        response['X-Accel-Redirect'] = f'/{settings.MEDIA_URL.strip("/")}/{ticket.pdf_file.name}'
    response['Cache-Control'] = 'private, no-store'
    response['X-Content-Type-Options'] = 'nosniff'
    return response


def entry_state(ticket):
    if ticket.status == 'cancelled' or ticket.match.is_cancelled:
        return 'cancelled', 'این بلیط یا سانس لغو شده است', False
    if ticket.is_used:
        return 'used', 'ورود با این بلیط ثبت شده است', False
    # Keep admission visible for the actual performance duration plus a grace period.
    from datetime import timedelta
    if ticket.match.date_time + timedelta(minutes=ticket.match.duration_minutes + 60) < timezone.now():
        return 'ended', 'زمان اجرای این برنامه گذشته است', False
    return 'ready', 'بلیط معتبر؛ آمادهٔ ورود', True


@login_required
@never_cache
@require_GET
def digital_ticket(request, ticket_id):
    ticket = owned_ticket(request, ticket_id)
    state, label, can_enter = entry_state(ticket)
    return render(request, 'tickets/digital_ticket.html', {
        'ticket': ticket, 'entry_status': state, 'entry_label': label, 'can_enter': can_enter,
    })


@login_required
@never_cache
@require_GET
def ticket_qr(request, ticket_id):
    ticket = owned_ticket(request, ticket_id)
    if not entry_state(ticket)[2]:
        raise Http404
    payload = ticket.gate_qr_payload
    image = qrcode.make(payload, box_size=10, border=4)
    data = BytesIO()
    image.save(data, format='PNG')
    response = HttpResponse(data.getvalue(), content_type='image/png')
    response['X-Content-Type-Options'] = 'nosniff'
    return response
