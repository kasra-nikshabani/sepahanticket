# tickets/management/commands/rqworker.py
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "اجرای worker صف پس‌زمینه (RQ) برای تولید PDF بلیط"

    def handle(self, *args, **options):
        from rq import Worker
        from tickets.queue import pdf_queue

        self.stdout.write(self.style.SUCCESS("Starting RQ worker for queue: ticket_pdfs"))
        worker = Worker([pdf_queue], connection=pdf_queue.connection)
        worker.work()
