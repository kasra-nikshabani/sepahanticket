from django.db import migrations


def backfill_events(apps, schema_editor):
    Event = apps.get_model('matches', 'Event')
    Match = apps.get_model('matches', 'Match')
    alias = schema_editor.connection.alias
    # One event per legacy fixture; all existing IDs and ticket relations stay intact.
    for session in Match.objects.using(alias).filter(event__isnull=True).iterator():
        event = Event.objects.using(alias).create(
            title=f'{session.home_team} - {session.away_team}', category='sport',
            is_active=session.is_active,
        )
        Match.objects.using(alias).filter(pk=session.pk).update(event_id=event.pk)


class Migration(migrations.Migration):
    dependencies = [('matches', '0027_event_alter_match_options_alter_stadium_options_and_more')]
    operations = [migrations.RunPython(backfill_events, migrations.RunPython.noop)]
