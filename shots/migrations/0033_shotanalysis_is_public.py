from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('shots', '0032_shotanalysis_is_quick_upload'),
    ]

    operations = [
        migrations.AddField(
            model_name='shotanalysis',
            name='is_public',
            field=models.BooleanField(default=False),
        ),
    ]
