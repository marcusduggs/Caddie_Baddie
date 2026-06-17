"""Add updated_at field to ShotAnalysis

This migration adds a timestamp column updated_at used by the model to track
last-updated times. It allows nulls to avoid touching existing rows.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("shots", "0012_shotanalysis_hole_yardage"),
    ]

    operations = [
        migrations.AddField(
            model_name="shotanalysis",
            name="updated_at",
            field=models.DateTimeField(auto_now=True, null=True),
        ),
    ]
