# Generated migration to add stroke_number to ShotAnalysis
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('shots', '0014_alter_shotanalysis_updated_at'),
    ]

    operations = [
        migrations.AddField(
            model_name='shotanalysis',
            name='stroke_number',
            field=models.IntegerField(blank=True, null=True),
        ),
    ]
