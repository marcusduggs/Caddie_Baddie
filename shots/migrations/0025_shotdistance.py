# Generated migration for ShotDistance model (additive only)
from django.db import migrations, models

class Migration(migrations.Migration):

    dependencies = [
        ('shots', '0024_shotanalysis_include_course_text_and_more'),
    ]

    operations = [
        migrations.CreateModel(
            name='ShotDistance',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('hole_number', models.IntegerField(blank=True, null=True)),
                ('origin_lat', models.FloatField(blank=True, null=True)),
                ('origin_lng', models.FloatField(blank=True, null=True)),
                ('landing_lat', models.FloatField(blank=True, null=True)),
                ('landing_lng', models.FloatField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('previous_shot', models.ForeignKey(blank=True, null=True, on_delete=models.SET_NULL, to='shots.ShotDistance')),
                ('shot', models.ForeignKey(on_delete=models.CASCADE, related_name='distances', to='shots.ShotAnalysis')),
            ],
        ),
    ]
