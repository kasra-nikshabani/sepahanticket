"""Shared starter slider assets, explicitly importable into managed banners."""
from pathlib import Path
from django.contrib.staticfiles import finders
from django.core.exceptions import ValidationError
from django.core.files import File
from django.db import transaction
from .models import Event, HomeBanner

DEFAULT_BANNERS = (('حوصله بحر', 'patience-of-sea-banner.jpg'), ('۶۸ ثانیه', '68-seconds-banner.jpg'))


@transaction.atomic
def install_default_banners():
    # Lock the settings singleton so two import requests cannot duplicate the defaults.
    from accounts.models import SiteSettings
    config, _ = SiteSettings.objects.get_or_create(pk=1)
    SiteSettings.objects.select_for_update().get(pk=config.pk)
    if HomeBanner.objects.exists():
        return []
    sources = [(title, filename, finders.find('events/uploads/' + filename)) for title, filename in DEFAULT_BANNERS]
    if any(not path or not Path(path).is_file() for _, _, path in sources):
        raise ValidationError('تصاویر اولیه در فایل‌های سایت پیدا نشدند؛ بنر جدید بارگذاری کنید.')
    result = []
    for order, (title, filename, path) in enumerate(sources, start=1):
        event = Event.objects.filter(title=title, is_active=True, category__in=['theater', 'concert', 'event']).first()
        banner = HomeBanner(title=title, order=order, is_active=True, event=event)
        with open(path, 'rb') as source:
            banner.image.save(filename, File(source), save=False)
        banner.save()
        result.append(banner)
    return result
