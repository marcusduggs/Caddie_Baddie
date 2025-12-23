"""Add error_message field to ShotAnalysis

This migration adds a nullable text field used by views to store processing
error information.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("shots", "0008_shotanalysis_status"),
    ]

    operations = [
        migrations.AddField(
            model_name="shotanalysis",
            name="error_message",
            field=models.TextField(blank=True, null=True),
        ),
    ]
