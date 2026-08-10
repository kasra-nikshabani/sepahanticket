# tickets/api.py
import json
import secrets
from django.conf import settings
from django.core.cache import cache
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from django.utils import timezone
from .models import Ticket

ZONE_LABELS = {'class1': 'کلاس ۱', 'home': 'میزبان', 'away': 'میهمان', 'women': 'بانوان', 'vip': 'VIP'}

# حداکثر تلاش ناموفق ورود گیت قبل از قفل موقت
GATE_LOGIN_MAX_ATTEMPTS = 5
GATE_LOGIN_LOCKOUT_SECONDS = 300


def _gate_token_key(token):
    return f"gate_token:{token}"


def _gate_login_attempts_key(username):
    return f"gate_login_attempts:{username}"


def _extract_token(request, data):
    """توکن گیت را از هدر Authorization یا بدنه‌ی JSON درخواست می‌خواند."""
    auth_header = request.headers.get('Authorization', '')
    if auth_header.startswith('Bearer '):
        return auth_header[len('Bearer '):].strip()
    return (data.get('token') or '').strip()


def _get_gate_session(request, data):
    """نشست معتبر گیت (username, zone) را از روی توکن برمی‌گرداند؛ در صورت نامعتبر بودن None."""
    token = _extract_token(request, data)
    if not token:
        return None
    return cache.get(_gate_token_key(token))


def get_ticket_zone(ticket):
    """
    تشخیص جایگاه بلیط بر اساس بلوک — هماهنگ با Ticket.block_type_label
    (tickets/models.py) که از zone_type واقعی بلوک استفاده می‌کند، نه از
    حدس زدن روی اسم بلوک.
    برمی‌گرداند یکی از: 'vip' | 'class1' | 'women' | 'away' | 'home' | None
    (None یعنی جایگاه بلیط قابل تشخیص نیست — نباید به هیچ گیتی راه داده شود)
    """
    try:
        block = ticket.seat.row.block
    except Exception:
        return None

    if getattr(block, 'is_vip', False) or block.zone_type == 'vip':
        return 'vip'
    if getattr(block, 'is_class1', False) or block.zone_type == 'class1':
        return 'class1'
    if block.zone_type == 'women':
        return 'women'
    if block.zone_type == 'away':
        return 'away'
    if block.zone_type == 'home':
        return 'home'
    return None

@csrf_exempt
@require_http_methods(['POST'])
def gate_login(request):
    try:
        data = json.loads(request.body)
        username = data.get('username', '')
        password = data.get('password', '')
    except:
        return JsonResponse({'success': False, 'message': 'داده نامعتبر'}, status=400)

    attempts_key = _gate_login_attempts_key(username)
    if cache.get(attempts_key, 0) >= GATE_LOGIN_MAX_ATTEMPTS:
        return JsonResponse(
            {'success': False, 'message': 'تعداد تلاش‌های ناموفق زیاد است. چند دقیقه صبر کنید.'}, status=429
        )

    user = settings.GATE_USERS.get(username)
    if not user or not user['password'] or not secrets.compare_digest(user['password'], password):
        cache.set(attempts_key, cache.get(attempts_key, 0) + 1, timeout=GATE_LOGIN_LOCKOUT_SECONDS)
        return JsonResponse({'success': False, 'message': 'نام کاربری یا رمز اشتباه است'}, status=401)

    cache.delete(attempts_key)

    token = secrets.token_urlsafe(32)
    cache.set(_gate_token_key(token), {'username': username, 'zone': user['zone']}, timeout=settings.GATE_TOKEN_TTL)

    return JsonResponse({
        'success': True,
        'token': token,
        'zone': user['zone'],
        'zone_label': ZONE_LABELS.get(user['zone'], ''),
    })


@csrf_exempt
@require_http_methods(['POST'])
def scan_ticket(request):
    try:
        data = json.loads(request.body)
        qr_data = data.get('qr_data', '').strip()
    except:
        return JsonResponse({'status': 'invalid', 'message': 'داده نامعتبر'}, status=400)

    session = _get_gate_session(request, data)
    if not session:
        return JsonResponse({'status': 'invalid', 'message': 'نشست منقضی شده؛ دوباره وارد گیت شوید'}, status=401)

    # جایگاه از روی توکن سرور تعیین می‌شود، نه از ورودی کاربر — قابل جعل نیست
    zone = session['zone']

    # پارس QR: "Ticket:XXXXXX|Match:1|Seat:1|User:username"
    try:
        parts = dict(p.split(':') for p in qr_data.split('|'))
        ticket_number = parts.get('Ticket', '')
    except:
        return JsonResponse({'status': 'invalid', 'message': 'بلیط نامعتبر است'})

    try:
        ticket = Ticket.objects.select_related(
            'seat__row__block', 'match', 'user'
        ).get(ticket_number=ticket_number)
    except Ticket.DoesNotExist:
        return JsonResponse({'status': 'invalid', 'message': 'بلیط در سیستم یافت نشد'})

    # چک وضعیت بلیط
    if ticket.status not in ['paid', 'admin_assigned', 'vip_issued']:
        return JsonResponse({'status': 'invalid', 'message': f'وضعیت بلیط: {ticket.get_status_display()}'})

    # چک جایگاه
    ticket_zone = get_ticket_zone(ticket)
    if ticket_zone is None:
        return JsonResponse({'status': 'invalid', 'message': 'جایگاه این بلیط قابل تشخیص نیست؛ با مدیر تماس بگیرید'})
    if ticket_zone != zone:
        return JsonResponse({
            'status': 'invalid',
            'message': f'این بلیط متعلق به جایگاه {ZONE_LABELS.get(ticket_zone, ticket_zone)} است'
        })

    # چک استفاده شده
    if ticket.is_used:
        return JsonResponse({
            'status': 'used',
            'message': 'این بلیط قبلاً استفاده شده است',
            'used_at': ticket.used_at.strftime('%H:%M:%S') if ticket.used_at else '',
            'full_name': ticket.full_name,
            'national_code': ticket.national_code,
            'seat': f'بلوک {ticket.seat.row.block.name} - ردیف {ticket.seat.row.number} - صندلی {ticket.seat.number}',
        })

    # بلیط معتبر — علامت‌گذاری به عنوان استفاده شده
    ticket.is_used = True
    ticket.used_at = timezone.now()
    ticket.save(update_fields=['is_used', 'used_at'])

    return JsonResponse({
        'status': 'valid',
        'message': 'بلیط معتبر است',
        'full_name': ticket.full_name,
        'national_code': ticket.national_code,
        'match': f'{ticket.match.home_team} - {ticket.match.away_team}',
        'seat': f'بلوک {ticket.seat.row.block.name} - ردیف {ticket.seat.row.number} - صندلی {ticket.seat.number}',
    })