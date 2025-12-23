"""Add hole_yardage field to ShotAnalysis

This migration adds a nullable integer field used to store hole yardage.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("shots", "0011_shotanalysis_hole_number"),
    ]

    operations = [
        migrations.AddField(
            model_name="shotanalysis",
            name="hole_yardage",
            field=models.IntegerField(blank=True, null=True),
        ),
    ]
