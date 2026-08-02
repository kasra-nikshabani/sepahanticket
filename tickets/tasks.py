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
    """
    from .queue import pdf_queue
    pdf_queue.enqueue(generate_ticket_pdf_task, ticket_id)
