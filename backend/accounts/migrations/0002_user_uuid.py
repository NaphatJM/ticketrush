from django.db import migrations
from django.db import models

import db.utils


def fill_uuids(apps, schema_editor):
    User = apps.get_model('accounts', 'User')
    for user in User.objects.filter(uuid__isnull=True).only('pk'):
        user.uuid = db.utils.uuid7()
        user.save(update_fields=['uuid'])


class Migration(migrations.Migration):
    dependencies = [
        ('accounts', '0001_initial'),
    ]

    # A unique field with a callable default must be added nullable first: AddField evaluates the default once for every existing row.
    operations = [
        migrations.AddField(
            model_name='user',
            name='uuid',
            field=models.UUIDField(editable=False, null=True, verbose_name='UUID'),
        ),
        migrations.RunPython(fill_uuids, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='user',
            name='uuid',
            field=models.UUIDField(default=db.utils.uuid7, editable=False, unique=True, verbose_name='UUID'),
        ),
    ]
