from django.db.models.signals import post_save
from django.dispatch import receiver
from .models import Match, MatchSeat, Seat

@receiver(post_save, sender=Match)
def create_match_seats(sender, instance, created, **kwargs):
    if kwargs.get("raw"):
        return
	
    if created:
        # فقط برای صندلی‌های ورزشگاه همین مسابقه یک MatchSeat ایجاد کن
        # (نه همه‌ی صندلی‌های کل دیتابیس -- در پروژه‌ای با چند ورزشگاه این
        # باعث ساخت ده‌ها هزار رکورد اضافه و اشتباه شدن ظرفیت/درصد اشغال
        # در گزارش‌ها می‌شد)
        seats = Seat.objects.filter(row__block__stadium=instance.stadium)
        match_seats = [MatchSeat(match=instance, seat=seat) for seat in seats]
        MatchSeat.objects.bulk_create(match_seats, ignore_conflicts=True)
