"""Add status field to ShotAnalysis

This migration creates the `status` column referenced by the model so existing
views that query `shots_shotanalysis.status` won't raise OperationalError.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("shots", "0007_shotanalysis_thumbnail"),
    ]

    operations = [
        migrations.AddField(
            model_name="shotanalysis",
            name="status",
            field=models.CharField(
                max_length=20,
                choices=[
                    ("uploading", "Uploading"),
                    ("processing", "Processing"),
                    ("completed", "Completed"),
                    ("failed", "Failed"),
                ],
                default="uploading",
                null=True,
                blank=True,
            ),
        ),
    ]
