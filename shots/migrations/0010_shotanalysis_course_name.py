"""Add course_name field to ShotAnalysis

This migration adds a nullable CharField used to store the golf course name.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("shots", "0009_shotanalysis_error_message"),
    ]

    operations = [
        migrations.AddField(
            model_name="shotanalysis",
            name="course_name",
            field=models.CharField(max_length=200, blank=True, null=True),
        ),
    ]
