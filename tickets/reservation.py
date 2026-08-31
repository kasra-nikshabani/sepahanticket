# tickets/reservation.py
"""
رزرو صندلی با Redis — نسخه سخت‌گیرانه.

ویژگی‌ها:
- رزرو جدید: SET NX EX (atomic)
- تمدید: Lua script (atomic، فقط مالک)
- آزادسازی: فقط مالک (یا force برای ادمین/سیستم)
- خواندن دسته‌ای با get_many
- پاک‌سازی رزروهای منقضی در DB
"""
from django.core.cache import cache
from django.conf import settings
from django.utils import timezone
import logging

logger = logging.getLogger(__name__)

# Lua: تمدید TTL فقط اگر توکن مالک در value باشد
# KEYS[1] = key, ARGV[1] = owner_token, ARGV[2] = ttl_seconds
LUA_EXTEND = """
local raw = redis.call('GET', KEYS[1])
if not raw then
    return 0
end
if string.find(raw, ARGV[1], 1, true) then
    redis.call('EXPIRE', KEYS[1], tonumber(ARGV[2]))
    return 1
end
return 0
"""

# Lua: حذف فقط اگر توکن مالک در value باشد
# KEYS[1] = key, ARGV[1] = owner_token
LUA_RELEASE_OWNED = """
local raw = redis.call('GET', KEYS[1])
if not raw then
    return 0
end
if string.find(raw, ARGV[1], 1, true) then
    redis.call('DEL', KEYS[1])
    return 1
end
return 0
"""


class SeatReservation:
    """مدیریت رزرو صندلی‌ها با Redis (نسخه سخت‌گیرانه)"""

    RESERVATION_TIMEOUT = getattr(settings, 'SEAT_RESERVATION_TIMEOUT', 600)

    @classmethod
    def _get_seat_key(cls, match_seat_id):
        return f"seat_reservation:{match_seat_id}"

    @classmethod
    def _owner_token(cls, user_id):
        return f"uid:{user_id}"

    @classmethod
    def _build_data(cls, user_id, match_id):
        return {
            'user_id': user_id,
            'match_id': match_id,
            'owner': cls._owner_token(user_id),
            'reserved_at': timezone.now().isoformat(),
        }

    @classmethod
    def _redis_client(cls):
        return cache.client.get_client(write=True)

    @classmethod
    def _make_cache_key(cls, match_seat_id):
        key = cls._get_seat_key(match_seat_id)
        try:
            return cache.make_key(key)
        except Exception:
            return key

    # ------------------------------------------------------------------
    # رزرو
    # ------------------------------------------------------------------
    @classmethod
    def reserve(cls, match_seat_id, user_id, match_id):
        """
        رزرو atomic یک صندلی.
        بازگشت: (success: bool, message: str)
        """
        try:
            key = cls._get_seat_key(match_seat_id)
            data = cls._build_data(user_id, match_id)

            if cache.add(key, data, timeout=cls.RESERVATION_TIMEOUT):
                return True, "رزرو با موفقیت انجام شد"

            if cls.extend_reservation(match_seat_id, user_id=user_id):
                return True, "رزرو تمدید شد"

            return False, "این صندلی در حال حاضر توسط کاربر دیگری رزرو شده است."
        except Exception as e:
            logger.error(f"Redis error in reserve: {e}", exc_info=True)
            return False, "خطا در اتصال به سرور رزرو. لطفاً دوباره تلاش کنید."

    @classmethod
    def reserve_many(cls, match_seat_ids, user_id, match_id):
        reserved = []
        for seat_id in match_seat_ids:
            success, msg = cls.reserve(seat_id, user_id, match_id)
            if not success:
                cls.release_many(reserved, user_id=user_id, force=True)
                return False, msg, []
            reserved.append(seat_id)
        return True, "رزرو با موفقیت انجام شد", reserved

    # ------------------------------------------------------------------
    # تمدید atomic
    # ------------------------------------------------------------------
    @classmethod
    def extend_reservation(cls, match_seat_id, user_id=None):
        if user_id is None:
            return False

        try:
            client = cls._redis_client()
            redis_key = cls._make_cache_key(match_seat_id)
            owner = cls._owner_token(user_id)
            result = client.eval(
                LUA_EXTEND,
                1,
                redis_key,
                owner,
                str(cls.RESERVATION_TIMEOUT),
            )
            if result == 1:
                return True

            key = cls._get_seat_key(match_seat_id)
            data = cache.get(key)
            if data and data.get('user_id') == user_id:
                cache.set(key, data, timeout=cls.RESERVATION_TIMEOUT)
                return True
            return False
        except Exception as e:
            logger.warning(f"extend_reservation Lua/fallback: {e}")
            try:
                key = cls._get_seat_key(match_seat_id)
                data = cache.get(key)
                if data and data.get('user_id') == user_id:
                    cache.set(key, data, timeout=cls.RESERVATION_TIMEOUT)
                    return True
            except Exception as e2:
                logger.error(f"extend_reservation failed: {e2}", exc_info=True)
            return False

    # ------------------------------------------------------------------
    # آزادسازی — فقط مالک مگر force
    # ------------------------------------------------------------------
    @classmethod
    def release(cls, match_seat_id, user_id=None, force=False):
        """
        - force=True: همیشه حذف (پرداخت ناموفق / سیستم)
        - user_id: فقط اگر مالک باشد
        - بدون هردو: حذف نمی‌کند
        """
        try:
            key = cls._get_seat_key(match_seat_id)

            if force:
                cache.delete(key)
                return True

            if user_id is None:
                logger.warning(
                    f"release blocked for seat {match_seat_id}: no user_id and not force"
                )
                return False

            try:
                client = cls._redis_client()
                redis_key = cls._make_cache_key(match_seat_id)
                owner = cls._owner_token(user_id)
                result = client.eval(LUA_RELEASE_OWNED, 1, redis_key, owner)
                if result == 1:
                    return True
            except Exception as e:
                logger.warning(f"release Lua failed, fallback: {e}")

            data = cache.get(key)
            if data and data.get('user_id') == user_id:
                cache.delete(key)
                return True

            return False
        except Exception as e:
            logger.error(f"Redis error in release: {e}", exc_info=True)
            return False

    @classmethod
    def release_many(cls, match_seat_ids, user_id=None, force=False):
        ok = 0
        for seat_id in match_seat_ids:
            if cls.release(seat_id, user_id=user_id, force=force):
                ok += 1
        return ok

    # ------------------------------------------------------------------
    # خواندن
    # ------------------------------------------------------------------
    @classmethod
    def is_reserved(cls, match_seat_id):
        try:
            return cache.get(cls._get_seat_key(match_seat_id)) is not None
        except Exception:
            return False

    @classmethod
    def is_reserved_by_user(cls, match_seat_id, user_id):
        try:
            data = cache.get(cls._get_seat_key(match_seat_id))
            return bool(data and data.get('user_id') == user_id)
        except Exception:
            return False

    @classmethod
    def get_reservation(cls, match_seat_id):
        try:
            return cache.get(cls._get_seat_key(match_seat_id))
        except Exception:
            return None

    @classmethod
    def get_reserved_map(cls, match_seat_ids):
        result = {sid: None for sid in match_seat_ids}
        if not match_seat_ids:
            return result
        try:
            keys = {sid: cls._get_seat_key(sid) for sid in match_seat_ids}
            values = cache.get_many(list(keys.values()))
            inv = {v: k for k, v in keys.items()}
            for redis_key, data in values.items():
                sid = inv.get(redis_key)
                if sid is not None:
                    result[sid] = data
        except Exception as e:
            logger.error(f"get_reserved_map error: {e}", exc_info=True)
        return result

    # ------------------------------------------------------------------
    # پاک‌سازی DB
    # ------------------------------------------------------------------
    @classmethod
    def cleanup_expired_db_reservations(cls, batch_size=500):
        """
        MatchSeatهای منقضی که در Redis کلید ندارند را آزاد می‌کند.
        """
        from matches.models import MatchSeat
        from tickets.models import Ticket
        from django.db import transaction

        now = timezone.now()
        freed = 0
        skipped_ticketed = 0
        scanned = set()

        while True:
            expired_ids = list(
                MatchSeat.objects.filter(
                    is_available=False,
                    reserved_until__isnull=False,
                    reserved_until__lt=now,
                ).exclude(id__in=scanned)
                .values_list('id', flat=True)[:batch_size]
            )
            if not expired_ids:
                break
            scanned.update(expired_ids)

            reserved_map = cls.get_reserved_map(expired_ids)
            candidates = [sid for sid in expired_ids if not reserved_map.get(sid)]

            # ===== صندلی‌ای که بلیط صادرشده دارد هرگز آزاد نمی‌شود =====
            # این تابع تا اینجا فقط «مهلت گذشته + کلید Redis نیست» را می‌دید و
            # اصلاً نمی‌پرسید آیا برای این صندلی بلیطی صادر شده یا نه. یعنی هر
            # مسیری که روی یک صندلیِ فروخته‌شده reserved_until را پاک نکند،
            # ۵ دقیقه بعد باعث می‌شود همین job صندلی را «آزاد» کند و نفر بعدی
            # همان صندلی را بخرد -- دو بلیط روی یک صندلی. (روی مسابقه‌ی ۲۲
            # ۱۲۱ صندلی و روی ۲۷ ۳۲ صندلی دقیقاً همین شکلی دو بار فروخته شدند؛
            # فاصله‌ی زمانی بین دو بلیط دقیقه/ساعت بود، نه میلی‌ثانیه، پس
            # race condition نبوده.) مسیر خرید فعلی reserved_until را پاک
            # می‌کند، ولی این‌جا آخرین خط دفاع است و نباید به آن تکیه کرد.
            ISSUED = ('paid', 'admin_assigned', 'vip_issued')
            rows = list(
                MatchSeat.objects.filter(id__in=candidates)
                .values_list('id', 'match_id', 'seat_id')
            )
            pair_of = {mid_: (m, s) for mid_, m, s in rows}
            ticketed_ms_ids = set(
                Ticket.objects.filter(status__in=ISSUED, match_seat_id__in=candidates)
                .values_list('match_seat_id', flat=True)
            )
            # بلیط‌های قدیمی‌تر ممکن است match_seat نداشته باشند؛ با جفتِ
            # (مسابقه، صندلی) هم چک می‌شود.
            ticketed_pairs = set(
                Ticket.objects.filter(
                    status__in=ISSUED,
                    match_id__in={m for _, m, _ in rows},
                    seat_id__in={s for _, _, s in rows},
                ).values_list('match_id', 'seat_id')
            )
            to_free = [
                sid for sid in candidates
                if sid not in ticketed_ms_ids and pair_of.get(sid) not in ticketed_pairs
            ]
            blocked = len(candidates) - len(to_free)
            if blocked:
                skipped_ticketed += blocked
                logger.error(
                    "cleanup_expired_db_reservations: %d صندلیِ دارای بلیط از آزادسازی محافظت شد "
                    "-- یعنی جایی reserved_until روی صندلیِ فروخته‌شده پاک نشده است: %s",
                    blocked,
                    [sid for sid in candidates if sid not in to_free][:20],
                )

            if to_free:
                with transaction.atomic():
                    updated = (
                        MatchSeat.objects
                        .filter(id__in=to_free, is_available=False)
                        .update(is_available=True, reserved_until=None)
                    )
                    freed += updated

            if len(expired_ids) < batch_size:
                break

        return freed
