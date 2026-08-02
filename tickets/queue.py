# tickets/queue.py
"""
صف پردازش پس‌زمینه برای کارهای سنگین (فعلاً فقط تولید PDF بلیط) با RQ روی
همان Redis که پروژه از قبل برای کش/سشن/رزرو صندلی استفاده می‌کند.
"""
import redis
from django.conf import settings
from rq import Queue

_connection = redis.from_url(settings.REDIS_URL)

pdf_queue = Queue('ticket_pdfs', connection=_connection, default_timeout=60)
