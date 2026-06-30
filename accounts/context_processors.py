# accounts/context_processors.py
from django.conf import settings

def site_settings(request):
    return {'settings': settings}