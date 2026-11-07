import hashlib
import re

from django.conf import settings
from django.core import signing
from django.http import FileResponse, Http404, JsonResponse
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_POST
from django.contrib.auth.decorators import login_required

from .models import Enrollment, Lesson
from .video import stream_directory


def playable_lesson(request, lesson_id):
    lesson = get_object_or_404(Lesson.objects.select_related('course__owner'), pk=lesson_id)
    course = lesson.course
    if course.kind != 'recorded':
        raise Http404
    privileged = request.user.is_authenticated and (request.user.is_staff or request.user.pk == course.owner_id)
    enrollment = Enrollment.objects.filter(course=course, learner=request.user, status='active').first() if request.user.is_authenticated else None
    preview = lesson.is_preview and course.status == 'published' and course.owner.is_active and not course.access_suspended
    if not privileged and (not lesson.is_active or course.access_suspended or not (enrollment or preview)):
        raise Http404
    if not lesson.stream_revision: raise Http404
    return lesson, enrollment


def session_binding(request):
    return hashlib.sha256((request.session.session_key or '').encode()).hexdigest()


def cookie_name(lesson):
    return 'edu_play_' + lesson.pk.hex


@login_required
@never_cache
@require_POST
def authorize(request, lesson_id):
    lesson, _ = playable_lesson(request, lesson_id)
    ttl = getattr(settings, 'EDUCATION_PLAYBACK_TTL', 180)
    payload = {'user': request.user.pk, 'lesson': str(lesson.pk), 'revision': str(lesson.stream_revision), 'session': session_binding(request)}
    token = signing.dumps(payload, salt='education-playback')
    manifest = reverse('education:stream', args=[lesson.pk, lesson.stream_revision, 'index.m3u8'])
    response = JsonResponse({'manifest': manifest, 'expires_in': ttl})
    response.set_cookie(cookie_name(lesson), token, max_age=ttl, httponly=True,
                        secure=settings.SESSION_COOKIE_SECURE, samesite='Strict',
                        path=reverse('education:stream', args=[lesson.pk, lesson.stream_revision, 'index.m3u8']).rsplit('/', 2)[0] + '/')
    return response


@never_cache
@require_GET
def stream(request, lesson_id, revision, asset):
    if not request.user.is_authenticated: raise Http404
    lesson, _ = playable_lesson(request, lesson_id)
    if revision != lesson.stream_revision: raise Http404
    try:
        payload = signing.loads(request.COOKIES.get(cookie_name(lesson), ''), salt='education-playback', max_age=getattr(settings, 'EDUCATION_PLAYBACK_TTL', 180))
    except signing.BadSignature:
        raise Http404
    if payload != {'user': request.user.pk, 'lesson': str(lesson.pk), 'revision': str(revision), 'session': session_binding(request)}:
        raise Http404
    if asset not in ('index.m3u8', 'key.bin') and not re.fullmatch(r'segment_\d{6}\.ts', asset): raise Http404
    path = stream_directory(lesson.pk, revision) / asset
    if not path.is_file(): raise Http404
    content_type = {'index.m3u8': 'application/vnd.apple.mpegurl', 'key.bin': 'application/octet-stream'}.get(asset, 'video/mp2t')
    response = FileResponse(path.open('rb'), content_type=content_type)
    response['Content-Disposition'] = 'inline'
    response['X-Content-Type-Options'] = 'nosniff'
    response['Cross-Origin-Resource-Policy'] = 'same-origin'
    response['Vary'] = 'Cookie'
    return response
