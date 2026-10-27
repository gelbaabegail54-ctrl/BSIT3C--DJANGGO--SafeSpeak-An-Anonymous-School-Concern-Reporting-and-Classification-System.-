from django.conf import settings
from django.db import migrations


def promote_staff_to_administrators(apps, schema_editor):
    """Merge the former Staff role into the Administrator role."""
    User = apps.get_model(*settings.AUTH_USER_MODEL.split('.'))
    User.objects.filter(is_staff=True, is_superuser=False).update(is_superuser=True)
    User.objects.filter(is_superuser=True).update(is_staff=True)


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('core', '0012_remove_ticket_numbers'),
    ]

    operations = [
        migrations.RunPython(
            promote_staff_to_administrators,
            migrations.RunPython.noop,
        ),
    ]
