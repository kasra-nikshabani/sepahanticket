# tickets/tasks.py
import logging

logger = logging.getLogger(__name__)


def generate_ticket_pdf_task(ticket_id):
    """
    اجرا در worker پس‌زمینه (RQ) — نه در چرخه‌ی درخواست HTTP.
    سنگین‌ترین بخش صدور بلیط (رندر PDF با WeasyPrint) را از مسیر خرید جدا
    می‌کند تا کاربر منتظر آن نماند.
    """
    from .models import Ticket

    try:
        ticket = Ticket.objects.get(id=ticket_id)
    except Ticket.DoesNotExist:
        logger.warning(f"generate_ticket_pdf_task: ticket {ticket_id} not found")
        return

    ticket.generate_pdf()
    ticket.save(update_fields=['pdf_file'])


def enqueue_pdf_generation(ticket_id):
    """
    فقط بعد از commit شدن تراکنش دیتابیس صدا زده شود (مثلاً با
    transaction.on_commit) تا worker موقع پردازش، ردیف بلیط را در دیتابیس
    پیدا کند.

    محافظت idempotent: Ticket.save() هر بار که pdf_file هنوز خالی باشد این
    تابع را صدا می‌زند (نه فقط موقع ایجاد بلیط) -- اگر جایی در کد یک save()
    اضافه/تکراری روی بلیطی که هنوز PDF نگرفته صدا زده شود (که دقیقاً همین
    چند call site واقعی هم داشتند)، بدون این قفل، همان بلیط چندین‌بار در صف
    قرار می‌گرفت و صف را با job های تکراری پر می‌کرد. cache.add اتمیک است.
    """
    from django.core.cache import cache
    from .queue import pdf_queue

    lock_key = f'pdf_enqueued:{ticket_id}'
    if not cache.add(lock_key, 1, timeout=120):
        logger.info(f"enqueue_pdf_generation: ticket {ticket_id} already enqueued recently, skipping duplicate")
        return

    pdf_queue.enqueue(generate_ticket_pdf_task, ticket_id)


def build_special_codes_zip_task(user_id, code_ids):
    """
    اجرا در worker پس‌زمینه (RQ) -- ساخت ZIP گروهی کدهای ویژه دیگه توی خودِ
    درخواست HTTP انجام نمی‌شه: هر PDF با WeasyPrint حدود ۰.۳ ثانیه طول
    می‌کشه و برای دسته‌های بزرگ (مثلاً چند صد کد) کاربر چند دقیقه معطل
    می‌موند (یا حتی به timeout گانیکورن می‌خورد). نتیجه یک فایل موقت روی
    دیسکه (خارج از MEDIA_ROOT، پس هیچ URL مستقیمی به‌ش نمی‌رسه)؛ ویوی
    دانلود بعد از serve کردنش خودش پاکش می‌کنه.
    """
    import os
    import uuid
    import zipfile
    from io import BytesIO

    from django.conf import settings
    from django.contrib.auth import get_user_model
    from django.utils import timezone
    from weasyprint.text.fonts import FontConfiguration

    from .models import SpecialCode
    from .views import _build_special_code_pdf_bytes

    User = get_user_model()
    try:
        user = User.objects.get(id=user_id)
    except User.DoesNotExist:
        logger.warning(f"build_special_codes_zip_task: user {user_id} not found")
        return None

    codes = list(
        SpecialCode.objects.filter(id__in=code_ids, vip_owner_id=user_id)
        .select_related('match').order_by('match__date_time', 'created_at')
    )
    if not codes:
        return None

    font_config = FontConfiguration()
    zip_buffer = BytesIO()
    with zipfile.ZipFile(zip_buffer, 'w') as zip_file:
        used_names = set()
        for code in codes:
            pdf_bytes = _build_special_code_pdf_bytes(user, code, font_config=font_config)
            arcname = f"کد_ویژه_{code.code}.pdf"
            n = 2
            base_arcname = arcname
            while arcname in used_names:
                arcname = base_arcname.replace('.pdf', f'_{n}.pdf')
                n += 1
            used_names.add(arcname)
            zip_file.writestr(arcname, pdf_bytes)

    tmp_dir = os.path.join(settings.BASE_DIR, 'tmp_downloads')
    os.makedirs(tmp_dir, exist_ok=True)
    zip_path = os.path.join(tmp_dir, f"special_codes_{uuid.uuid4().hex}.zip")
    with open(zip_path, 'wb') as f:
        f.write(zip_buffer.getvalue())

    return {
        'zip_path': zip_path,
        'display_filename': f"کدهای_ویژه_{user.username}_{timezone.now().strftime('%Y%m%d_%H%M')}.zip",
    }
