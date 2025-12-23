"""Add hole_number field to ShotAnalysis

This migration adds a nullable integer field used to store the hole number.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("shots", "0010_shotanalysis_course_name"),
    ]

    operations = [
        migrations.AddField(
            model_name="shotanalysis",
            name="hole_number",
            field=models.IntegerField(blank=True, null=True),
        ),
    ]
