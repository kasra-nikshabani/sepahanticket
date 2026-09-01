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

    # ===== چرا update() و نه save() =====
    # Ticket.save() هر بار که pdf_file خالی باشد دوباره همین کار را در صف
    # می‌گذارد. پس اگر تولید PDF ناموفق بماند، همین save یک حلقه‌ی بی‌پایان
    # می‌سازد: کار اجرا می‌شود -> PDF ساخته نمی‌شود -> save -> دوباره در صف.
    # با قفلِ ۱۲۰ ثانیه‌ایِ enqueue یعنی هر بلیطِ بی‌PDF هر دو دقیقه یک کار
    # تازه تولید می‌کند. شب دربی همین حلقه صف را به ۱.۳۹ میلیون کار رساند
    # (برای ۳۲ هزار بلیط) و بلیط‌های واقعی ساعت‌ها پشت آن ماندند.
    # update() مستقیم روی دیتابیس می‌نویسد و save() را اصلاً صدا نمی‌زند.
    if ticket.pdf_file:
        Ticket.objects.filter(pk=ticket.pk).update(pdf_file=ticket.pdf_file.name)
    else:
        # عمداً دوباره در صف گذاشته نمی‌شود -- یک خطای پایدار نباید به
        # سیلِ کار تبدیل شود. بلیط‌های بی‌PDF از طریق گزارش قابل شناسایی و
        # با دستور مدیریتی قابل تولید مجددند.
        logger.error("generate_ticket_pdf_task: PDF تولید نشد برای بلیط %s", ticket_id)


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

    # ===== شبکه‌ی ایمنی: اگر کاربری فایل آماده‌شده رو هیچ‌وقت دانلود نکنه
    # (تب رو ببنده، نتِ قطع بشه و...)، ویوی دانلود که مسئول پاک کردنه هیچ‌وقت
    # صدا زده نمی‌شه و فایل موقت رو دیسک می‌مونه. اینجا هر بار قبل از نوشتن
    # فایل جدید، فایل‌های موقت قدیمی‌تر از ۲ ساعت رو پاک می‌کنیم -- کشف‌شده
    # موقع بررسی سلامت سامانه (یک ZIP ~۶ مگابایتی از یک تست قدیمی روی دیسک
    # مونده بود چون polling سمت کلاینت زودتر از تمام‌شدنِ job قطع شده بود). =====
    try:
        cutoff = timezone.now().timestamp() - 2 * 3600
        for fname in os.listdir(tmp_dir):
            fpath = os.path.join(tmp_dir, fname)
            if os.path.isfile(fpath) and os.path.getmtime(fpath) < cutoff:
                os.remove(fpath)
    except OSError:
        pass

    zip_path = os.path.join(tmp_dir, f"special_codes_{uuid.uuid4().hex}.zip")
    with open(zip_path, 'wb') as f:
        f.write(zip_buffer.getvalue())

    return {
        'zip_path': zip_path,
        'display_filename': f"کدهای_ویژه_{user.username}_{timezone.now().strftime('%Y%m%d_%H%M')}.zip",
    }
