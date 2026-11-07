"""Retire legacy identity/VIP workflows on the cultural platform without deleting history."""
from django.conf import settings
from django.http import HttpResponseNotFound
from django.shortcuts import redirect


class CulturalPlatformMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_view(self, request, view, args, kwargs):
        if not getattr(settings, 'CULTURAL_PLATFORM', False):
            return None
        match = request.resolver_match
        if not match:
            return None
        name = match.url_name or ''
        retired = (match.namespace == 'tickets' and ('vip' in name or name in (
            'inquiry_fan', 'check_special_code', 'admin_special_code_toggle', 'admin_special_code_delete')))
        retired = retired or (match.namespace == 'accounts' and match.url_name in (
            'admin_emergency_settings', 'fanid_login', 'fanid_callback', 'fanid_verify', 'fanid_resend'))
        retired = retired or (match.namespace == 'admin' and (name.startswith('tickets_vipquota_') or name.startswith('tickets_specialcode_')))
        if retired:
            return HttpResponseNotFound('این بخش در دیدآور فعال نیست.')
        if request.method == 'GET':
            links = {'event_list': 'events', 'event_create': 'event_create', 'admin_match_list': 'sessions',
                'admin_match_create': 'session_create', 'admin_stadium_list': 'venues', 'admin_stadium_create': 'venue_create',
                'admin_user_list': 'users', 'admin_site_settings': 'settings', 'sales_report': 'sales', 'admin_reports': 'sales'}
            if match.namespace in ('accounts', 'matches', 'tickets') and name in links:
                return redirect('management:' + links[name])
