from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('shots', '0031_swing_coach_v2'),
    ]

    operations = [
        migrations.AddField(
            model_name='shotanalysis',
            name='is_quick_upload',
            field=models.BooleanField(default=False),
        ),
    ]
