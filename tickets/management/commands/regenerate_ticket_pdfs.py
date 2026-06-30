from django.core.management.base import BaseCommand
from tickets.models import Ticket


class Command(BaseCommand):
    help = 'Regenerate PDF files for all tickets'

    def add_arguments(self, parser):
        parser.add_argument(
            '--match-id',
            type=int,
            help='Only regenerate tickets for a specific match ID',
        )

    def handle(self, *args, **options):
        queryset = Ticket.objects.all()
        if options.get('match_id'):
            queryset = queryset.filter(match_id=options['match_id'])

        total = queryset.count()
        self.stdout.write(f"🔄 Regenerating {total} tickets...")

        for index, ticket in enumerate(queryset, 1):
            if ticket.pdf_file:
                ticket.pdf_file.delete(save=False)
            ticket.generate_pdf()
            ticket.save()

            if index % 10 == 0:
                self.stdout.write(f"✅ {index}/{total} done")

        self.stdout.write(self.style.SUCCESS(f"🎉 All {total} tickets updated successfully!"))