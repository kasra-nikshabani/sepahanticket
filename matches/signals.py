from django.db.models.signals import post_save
from django.dispatch import receiver
from .models import Match, MatchSeat, Seat

@receiver(post_save, sender=Match)
def create_match_seats(sender, instance, created, **kwargs):
    if created:
        # برای هر صندلی موجود، یک MatchSeat ایجاد کن
        seats = Seat.objects.all()
        match_seats = [MatchSeat(match=instance, seat=seat) for seat in seats]
        MatchSeat.objects.bulk_create(match_seats)