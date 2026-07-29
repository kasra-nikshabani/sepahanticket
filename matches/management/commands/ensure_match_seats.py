from django.core.management.base import BaseCommand, CommandError
from matches.models import Match, MatchSeat, Block


class Command(BaseCommand):
    help = (
        'پیش‌ساخت MatchSeat برای یک مسابقه (یا همه مسابقات فعال). '
        'قبل از شروع فروش سنگین اجرا شود.'
    )

    def add_arguments(self, parser):
        parser.add_argument('--match-id', type=int, help='شناسه مسابقه خاص')
        parser.add_argument('--all-active', action='store_true', help='همه مسابقات فعال')
        parser.add_argument('--block-id', type=int, help='فقط یک بلوک')

    def handle(self, *args, **options):
        match_id = options.get('match_id')
        all_active = options.get('all_active')
        block_id = options.get('block_id')

        if not match_id and not all_active:
            raise CommandError('یکی از --match-id یا --all-active را مشخص کنید.')

        if match_id:
            matches = Match.objects.filter(id=match_id)
        else:
            matches = Match.objects.filter(is_active=True)

        if not matches.exists():
            raise CommandError('مسابقه‌ای یافت نشد.')

        block = None
        if block_id:
            block = Block.objects.filter(id=block_id).first()
            if not block:
                raise CommandError(f'بلوک {block_id} یافت نشد.')

        for match in matches:
            created = MatchSeat.ensure_for_match(match, block=block)
            self.stdout.write(
                self.style.SUCCESS(
                    f'[{match.id}] {match.home_team} vs {match.away_team}: '
                    f'{created} صندلی جدید ساخته شد.'
                )
            )
