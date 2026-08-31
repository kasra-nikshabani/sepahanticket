# tickets/api.py
import json
import secrets
from django.conf import settings
from django.core.cache import cache
from django.db import transaction
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from django.utils import timezone
from .models import Ticket

ZONE_LABELS = {'class1': 'کلاس ۱', 'home': 'میزبان', 'away': 'میهمان', 'women': 'بانوان میزبان',
               'women_away': 'بانوان میهمان', 'vip': 'VIP'}

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

    # نوع جایگاه مخصوصِ همین مسابقه (نه مقدار گلوبالِ بلوک) -- سهمیه‌ی
    # میزبان/میهمان از بازی به بازی فرق می‌کند. باید دقیقاً با
    # Ticket.block_type_label (که روی PDF بلیط چاپ می‌شود) یکی بماند، وگرنه
    # تماشاگر با بلیطی که روی آن «میزبان» نوشته دم گیت میهمان رد می‌شود.
    from matches.models import get_block_zone_for_match
    zone = get_block_zone_for_match(ticket.match, block)
    if zone in ('vip', 'class1', 'women', 'women_away', 'away', 'home'):
        return zone
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

    qr_match_id = parts.get('Match', '')

    try:
        # ===== قفل ردیف بلیط قبل از چک is_used (جلوگیری از race condition) =====
        # اگر دو گیت (یا دو اسکن سریع پشت‌سرهم روی همون بلیط -- مثلاً یک نفر
        # از عکس صفحه‌ی گوشی یک بار دیگه‌ای QR رو نشون بده) دقیقاً همزمان
        # برسن، بدون قفل هر دو ممکنه is_used=False رو ببینن و هر دو 'valid'
        # برگردونن -- یعنی با یک بلیط دو نفر وارد بشن. با select_for_update
        # تراکنش دوم منتظر اولی می‌مونه و درست 'used' می‌بینه.
        with transaction.atomic():
            ticket = Ticket.objects.select_for_update(of=('self',)).select_related(
                'seat__row__block', 'match', 'user'
            ).get(ticket_number=ticket_number)

            # چک وضعیت بلیط
            if ticket.status not in ['paid', 'admin_assigned', 'vip_issued']:
                return JsonResponse({'status': 'invalid', 'message': f'وضعیت بلیط: {ticket.get_status_display()}'})

            # ===== بلیط باید مالِ همین مسابقه باشد =====
            # تا پیش از این، گیت فقط شماره‌ی بلیط را نگاه می‌کرد و هیچ‌وقت
            # نمی‌پرسید این بلیط برای کدام مسابقه است. یعنی هر بلیطِ
            # اسکن‌نشده‌ی مسابقات قبلی (فقط در مسابقات ۲۲ و ۲۷ بیش از ۱۰ هزار
            # بلیط) در گیتِ مسابقه‌ی بعدی «معتبر» شمرده می‌شد و دارنده‌اش
            # می‌توانست دوباره وارد ورزشگاه شود.
            if ticket.match.is_cancelled:
                return JsonResponse({'status': 'invalid', 'message': 'مسابقه‌ی این بلیط لغو شده است'})

            window = getattr(settings, 'GATE_MATCH_WINDOW_HOURS', 12)
            now = timezone.now()
            if ticket.match.has_time:
                too_far = abs((now - ticket.match.date_time).total_seconds()) > window * 3600
                when = timezone.localtime(ticket.match.date_time).strftime('%Y/%m/%d %H:%M')
            else:
                # ساعت بازی اعلام نشده -- کل همان روزِ تقویمی (به‌وقت تهران)
                # پذیرفته می‌شود، وگرنه پنجره‌ی ساعتی حول ساعتِ جای‌پرکن
                # تماشاگرِ یک بازی شبانه را دم گیت رد می‌کرد.
                match_day = timezone.localtime(ticket.match.date_time).date()
                too_far = timezone.localtime(now).date() != match_day
                when = match_day.strftime('%Y/%m/%d')
            if too_far:
                return JsonResponse({
                    'status': 'invalid',
                    'message': f'این بلیط برای مسابقه‌ی {when} است، نه مسابقه‌ی امروز',
                })

            # QR خودش هم شناسه‌ی مسابقه را دارد؛ اگر با بلیط نخواند یعنی QR
            # دستکاری شده و باید رد شود (دفاع لایه‌ی دوم).
            if qr_match_id and str(ticket.match_id) != str(qr_match_id):
                return JsonResponse({'status': 'invalid', 'message': 'بلیط نامعتبر است'})

            # چک جایگاه
            ticket_zone = get_ticket_zone(ticket)
            if ticket_zone is None:
                return JsonResponse(
                    {'status': 'invalid', 'message': 'جایگاه این بلیط قابل تشخیص نیست؛ با مدیر تماس بگیرید'}
                )
            if ticket_zone != zone:
                return JsonResponse({
                    'status': 'invalid',
                    'message': f'این بلیط متعلق به جایگاه {ZONE_LABELS.get(ticket_zone, ticket_zone)} است'
                })

            # سن و مبلغ پرداختی فقط برای بلیط‌های خریداری‌شده‌ی واقعی (عادی یا
            # باسایی) نمایش داده می‌شود، نه برای بلیط‌های ویژه/سهمیه‌ای
            # (admin_assigned/vip_issued) که اصلاً سن/قیمتِ معنادار ندارند.
            extra_fields = {}
            if ticket.status == 'paid':
                extra_fields['price'] = ticket.price if ticket.price is not None else 0
                if ticket.age is not None:
                    extra_fields['age'] = ticket.age

            # چک استفاده شده
            if ticket.is_used:
                return JsonResponse({
                    'status': 'used',
                    'message': 'این بلیط قبلاً استفاده شده است',
                    'used_at': ticket.used_at.strftime('%H:%M:%S') if ticket.used_at else '',
                    'full_name': ticket.full_name,
                    'national_code': ticket.national_code,
                    'seat': f'بلوک {ticket.seat.row.block.name} - ردیف {ticket.seat.row.number} - صندلی {ticket.seat.number}',
                    **extra_fields,
                })

            # بلیط معتبر — علامت‌گذاری به عنوان استفاده شده
            ticket.is_used = True
            ticket.used_at = timezone.now()
            ticket.save(update_fields=['is_used', 'used_at'])
    except Ticket.DoesNotExist:
        return JsonResponse({'status': 'invalid', 'message': 'بلیط در سیستم یافت نشد'})

    return JsonResponse({
        'status': 'valid',
        'message': 'بلیط معتبر است',
        'full_name': ticket.full_name,
        'national_code': ticket.national_code,
        'match': f'{ticket.match.home_team} - {ticket.match.away_team}',
        'seat': f'بلوک {ticket.seat.row.block.name} - ردیف {ticket.seat.row.number} - صندلی {ticket.seat.number}',
        **extra_fields,
    })