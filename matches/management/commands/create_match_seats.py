# matches/management/commands/create_match_seats.py
from django.core.management.base import BaseCommand
from matches.models import Match, Seat, MatchSeat

class Command(BaseCommand):
    help = 'ایجاد MatchSeat برای تمام مسابقات و صندلی‌ها'

    def handle(self, *args, **options):
        matches = Match.objects.filter(is_active=True)
        total_created = 0
        for match in matches:
            seats = Seat.objects.all()
            existing = MatchSeat.objects.filter(match=match).values_list('seat_id', flat=True)
            missing_seat_ids = seats.exclude(id__in=existing).values_list('id', flat=True)
            if missing_seat_ids:
                match_seats = [
                    MatchSeat(match=match, seat_id=sid, is_available=True)
                    for sid in missing_seat_ids
                ]
                MatchSeat.objects.bulk_create(match_seats)
                total_created += len(match_seats)
                self.stdout.write(f'برای مسابقه {match.id} - {match.home_team} vs {match.away_team}، {len(match_seats)} MatchSeat ایجاد شد.')
            else:
                self.stdout.write(f'مسابقه {match.id} قبلاً کامل است.')
        self.stdout.write(self.style.SUCCESS(f'در مجموع {total_created} MatchSeat ایجاد شد.'))