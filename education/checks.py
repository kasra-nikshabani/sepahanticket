from pathlib import Path
from django.conf import settings
from django.core.checks import Error, register
from .models import PrivateEducationStorage


@register()
def private_media_check(app_configs, **kwargs):
    private = Path(PrivateEducationStorage().location).resolve()
    public = Path(settings.MEDIA_ROOT).resolve()
    if private.is_relative_to(public):
        return [Error('EDUCATION_PRIVATE_ROOT must be outside MEDIA_ROOT.', id='education.E001')]
    return []
