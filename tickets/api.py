# tickets/api.py
import json
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from django.utils import timezone
from .models import Ticket

GATE_USERS = {
    'gate_class1': {'password': '123456789', 'zone': 'class1'},
    'gate_home':   {'password': '123456789', 'zone': 'home'},
    'gate_away':   {'password': '123456789', 'zone': 'away'},
    'gate_women':  {'password': '123456789', 'zone': 'women'},
    'gate_vip': {'password': '123456789', 'zone': 'vip'},

}


def get_ticket_zone(ticket):
    """تشخیص جایگاه بلیط بر اساس بلوک"""
    try:
        block = ticket.seat.row.block
        if block.is_vip:
            return 'vip'
        # اولویت: کلاس ۱
        if block.is_class1:
            return 'class1'

        # VIP → به جایگاه میزبان (یا اگر جایگاه جداگانه دارید، می‌توانید 'vip' برگردانید)
        if block.is_vip:
            return 'home'  # ← تغییر: VIP به جایگاه میزبان نگاشت می‌شود

        # تشخیص بلوک‌های میهمان بر اساس شماره
        try:
            block_number = int(block.name.split()[-1])
            if block_number in [2, 3, 4, 5]:
                return 'away'
        except:
            pass

        # پیش‌فرض: میزبان
        return 'home'
    except:
        return 'home'

@csrf_exempt
@require_http_methods(['POST'])
def gate_login(request):
    try:
        data = json.loads(request.body)
        username = data.get('username', '')
        password = data.get('password', '')
    except:
        return JsonResponse({'success': False, 'message': 'داده نامعتبر'}, status=400)

    user = GATE_USERS.get(username)
    if user and user['password'] == password:
        return JsonResponse({
            'success': True,
            'zone': user['zone'],
            'zone_label': {
                'class1': 'کلاس ۱',
                'home': 'میزبان',
                'away': 'میهمان',
                'women': 'بانوان',
            }.get(user['zone'], '')
        })
    return JsonResponse({'success': False, 'message': 'نام کاربری یا رمز اشتباه است'}, status=401)


@csrf_exempt
@require_http_methods(['POST'])
def scan_ticket(request):
    try:
        data = json.loads(request.body)
        qr_data = data.get('qr_data', '').strip()
        zone = data.get('zone', '')
    except:
        return JsonResponse({'status': 'invalid', 'message': 'داده نامعتبر'}, status=400)

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
    if ticket_zone != zone:
        zone_labels = {'class1': 'کلاس ۱', 'home': 'میزبان', 'away': 'میهمان', 'women': 'بانوان'}
        return JsonResponse({
            'status': 'invalid',
            'message': f'این بلیط متعلق به جایگاه {zone_labels.get(ticket_zone, ticket_zone)} است'
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