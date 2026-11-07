"""Private AES-128 HLS packaging. Originals are never served by a view."""
import os
import shutil
import subprocess
import uuid
from pathlib import Path

from django.conf import settings
from django.utils import timezone

from .models import Lesson, PrivateEducationStorage


def stream_directory(lesson_id, revision):
    return Path(PrivateEducationStorage().location) / 'streams' / str(lesson_id) / str(revision)


def ffmpeg_binary():
    if configured := getattr(settings, 'EDUCATION_FFMPEG_BINARY', ''):
        return configured
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


def process_video(lesson_id):
    lesson = Lesson.objects.get(pk=lesson_id)
    revision = lesson.revision
    claimed = Lesson.objects.filter(pk=lesson_id, revision=revision, state='queued').update(
        state='processing', processing_started_at=timezone.now(), processing_error='')
    if not claimed:
        return False
    target = stream_directory(lesson_id, revision)
    working = target.parent / ('work-' + uuid.uuid4().hex)
    try:
        working.mkdir(parents=True, exist_ok=False)
        key_path = working / 'key.bin'
        key_path.write_bytes(os.urandom(16))
        info = working / 'keyinfo.txt'
        info.write_text('key.bin\n' + str(key_path.resolve()) + '\n')
        source_format = 'mov' if Path(lesson.source.name).suffix.lower() == '.mp4' else 'matroska'
        command = [ffmpeg_binary(), '-y', '-nostdin', '-hide_banner', '-loglevel', 'error',
                   '-protocol_whitelist', 'file,pipe,crypto', '-f', source_format, '-i', lesson.source.path,
                   '-map', '0:v:0', '-map', '0:a:0?', '-t', '21601',
                   '-vf', 'scale=1280:720:force_original_aspect_ratio=decrease:force_divisible_by=2',
                   '-c:v', 'libx264', '-preset', 'fast', '-crf', '24', '-pix_fmt', 'yuv420p',
                   '-g', '48', '-keyint_min', '48', '-sc_threshold', '0', '-threads', '2',
                   '-c:a', 'aac', '-b:a', '128k', '-ac', '2', '-f', 'hls', '-hls_time', '6',
                   '-hls_playlist_type', 'vod', '-hls_flags', 'independent_segments',
                   '-hls_segment_filename', str(working / 'segment_%06d.ts'),
                   '-hls_key_info_file', str(info), '-progress', 'pipe:1', str(working / 'index.m3u8')]
        result = subprocess.run(command, capture_output=True, timeout=getattr(settings, 'EDUCATION_VIDEO_TIMEOUT', 5400), check=True)
        progress = result.stdout.decode(errors='replace')
        times = [int(line.split('=', 1)[1]) for line in progress.splitlines() if line.startswith('out_time_us=') and line.split('=', 1)[1].isdigit()]
        duration = (max(times, default=0) + 999999) // 1000000
        manifest = (working / 'index.m3u8').read_text()
        if duration < 1 or duration >= 21600 or '#EXT-X-KEY:METHOD=AES-128' not in manifest or not list(working.glob('segment_*.ts')):
            raise ValueError('Invalid packaged video')
        info.unlink()
        if target.exists():
            raise ValueError('Revision already exists; retry with a new revision')
        working.rename(target)
        updated = Lesson.objects.filter(pk=lesson_id, revision=revision, state='processing').update(
            state='ready', stream_revision=revision, duration_seconds=duration, processing_error='')
        return bool(updated)
    except Exception:
        Lesson.objects.filter(pk=lesson_id, revision=revision, state='processing').update(
            state='failed', processing_error='آماده‌سازی انجام نشد؛ فایل MP4/WebM سالم را دوباره بارگذاری کنید یا با پشتیبانی تماس بگیرید.')
        return False
    finally:
        if working.exists():
            shutil.rmtree(working)
