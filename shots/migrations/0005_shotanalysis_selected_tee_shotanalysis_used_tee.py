"""Create ShotAnalysis.selected_tee and ShotAnalysis.used_tee

This migration fills the gap referenced by 0006_shotanalysis_hole_par which
depends on a migration named 0005_shotanalysis_selected_tee_shotanalysis_used_tee.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("shots", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="shotanalysis",
            name="selected_tee",
            field=models.CharField(max_length=64, blank=True, null=True),
        ),
        migrations.AddField(
            model_name="shotanalysis",
            name="used_tee",
            field=models.CharField(max_length=128, blank=True, null=True),
        ),
    ]
