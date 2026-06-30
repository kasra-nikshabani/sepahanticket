# tickets/reservation.py
from django.core.cache import cache
from django.conf import settings
from django.utils import timezone
import logging

logger = logging.getLogger(__name__)


class SeatReservation:
    """مدیریت رزرو صندلی‌ها با Redis"""

    RESERVATION_TIMEOUT = getattr(settings, 'SEAT_RESERVATION_TIMEOUT', 600)

    @classmethod
    def _get_seat_key(cls, match_seat_id):
        """ساخت کلید یکتا برای هر صندلی در Redis"""
        return f"seat_reservation:{match_seat_id}"

    @classmethod
    def reserve(cls, match_seat_id, user_id, match_id):
        """
        رزرو یک صندلی
        بازگشت: (success, message)
        """
        try:
            key = cls._get_seat_key(match_seat_id)
            existing = cache.get(key)
            if existing:
                if existing.get('user_id') == user_id:
                    # تمدید زمان رزرو
                    cache.set(key, existing, timeout=cls.RESERVATION_TIMEOUT)
                    return True, "رزرو تمدید شد"
                return False, "این صندلی در حال حاضر توسط کاربر دیگری رزرو شده است."

            # رزرو جدید
            data = {
                'user_id': user_id,
                'match_id': match_id,
                'reserved_at': timezone.now().isoformat()
            }
            cache.set(key, data, timeout=cls.RESERVATION_TIMEOUT)
            return True, "رزرو با موفقیت انجام شد"
        except Exception as e:
            logger.error(f"Redis error in reserve: {str(e)}")
            return False, "خطا در اتصال به سرور رزرو. لطفاً دوباره تلاش کنید."

    @classmethod
    def release(cls, match_seat_id):
        """آزاد کردن یک صندلی رزروشده"""
        key = cls._get_seat_key(match_seat_id)
        cache.delete(key)

    @classmethod
    def is_reserved(cls, match_seat_id):
        """بررسی وضعیت رزرو یک صندلی (وجود کلید در Redis)"""
        return cache.get(cls._get_seat_key(match_seat_id)) is not None

    @classmethod
    def is_reserved_by_user(cls, match_seat_id, user_id):
        """بررسی اینکه آیا صندلی توسط کاربر خاصی رزرو شده است"""
        key = cls._get_seat_key(match_seat_id)
        data = cache.get(key)
        if data and data.get('user_id') == user_id:
            return True
        return False

    @classmethod
    def get_reservation(cls, match_seat_id):
        """دریافت اطلاعات رزرو یک صندلی"""
        return cache.get(cls._get_seat_key(match_seat_id))

    @classmethod
    def extend_reservation(cls, match_seat_id):
        """تمدید زمان رزرو"""
        key = cls._get_seat_key(match_seat_id)
        data = cache.get(key)
        if data:
            cache.set(key, data, timeout=cls.RESERVATION_TIMEOUT)
            return True
        return False