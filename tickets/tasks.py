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
