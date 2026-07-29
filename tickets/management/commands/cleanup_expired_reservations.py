from django.core.management.base import BaseCommand
from tickets.reservation import SeatReservation


class Command(BaseCommand):
    help = 'آزادسازی MatchSeatهای رزرو‌شده منقضی که در Redis کلید ندارند'

    def handle(self, *args, **options):
        freed = SeatReservation.cleanup_expired_db_reservations()
        self.stdout.write(self.style.SUCCESS(f'{freed} صندلی منقضی آزاد شد.'))
