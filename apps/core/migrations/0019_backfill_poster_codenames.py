from django.db import migrations


def backfill_poster_codenames(apps, schema_editor):
    """Store code names for posts created before snapshots were introduced."""
    from apps.core.codenames import generated_user_codename

    Concern = apps.get_model('core', 'Concern')
    Confession = apps.get_model('core', 'Confession')
    ReportComment = apps.get_model('core', 'ReportComment')

    for model in (Concern, Confession):
        reports = model.objects.filter(
            poster_codename='',
            submitted_by__isnull=False,
        )
        for report in reports.iterator():
            report.poster_codename = generated_user_codename(
                report.submitted_by_id,
            )
            report.save(update_fields=['poster_codename'])

    comments = ReportComment.objects.filter(
        poster_codename='',
        author__isnull=False,
    )
    for comment in comments.iterator():
        comment.poster_codename = generated_user_codename(comment.author_id)
        comment.save(update_fields=['poster_codename'])


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0018_reportcomment_poster_codename_usercodename'),
    ]

    operations = [
        migrations.RunPython(
            backfill_poster_codenames,
            migrations.RunPython.noop,
        ),
    ]
