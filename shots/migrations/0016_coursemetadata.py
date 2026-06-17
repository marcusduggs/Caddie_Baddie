# Migration to add CourseMetadata model
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('shots', '0015_shotanalysis_stroke_number'),
    ]

    operations = [
        migrations.CreateModel(
            name='CourseMetadata',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('course_slug', models.SlugField(max_length=255, unique=True)),
                ('name', models.CharField(max_length=255)),
                ('address', models.TextField(blank=True, null=True)),
                ('hole_count', models.IntegerField(blank=True, null=True)),
                ('par_total', models.IntegerField(blank=True, null=True)),
                ('fetched_at', models.DateTimeField(auto_now=True)),
            ],
        ),
    ]
