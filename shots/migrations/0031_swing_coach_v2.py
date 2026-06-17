from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('shots', '0030_shotanalysis_ai_fields'),
    ]

    operations = [
        # New score fields on ShotAnalysis
        migrations.AddField(
            model_name='shotanalysis',
            name='ai_overall_score',
            field=models.IntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='shotanalysis',
            name='ai_tempo_score',
            field=models.IntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='shotanalysis',
            name='ai_balance_score',
            field=models.IntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='shotanalysis',
            name='ai_rotation_score',
            field=models.IntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='shotanalysis',
            name='ai_posture_score',
            field=models.IntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='shotanalysis',
            name='ai_sequencing_score',
            field=models.IntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='shotanalysis',
            name='ai_consistency_score',
            field=models.IntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='shotanalysis',
            name='ai_shot_shape',
            field=models.CharField(blank=True, max_length=20, null=True),
        ),
        migrations.AddField(
            model_name='shotanalysis',
            name='ai_pro_comparison',
            field=models.TextField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='shotanalysis',
            name='ai_trend_summary',
            field=models.TextField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='shotanalysis',
            name='ai_snapshots_json',
            field=models.TextField(blank=True, null=True),
        ),
        # SwingTendency model
        migrations.CreateModel(
            name='SwingTendency',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('tendency_type', models.CharField(max_length=50)),
                ('label', models.CharField(max_length=100)),
                ('occurrence_count', models.IntegerField(default=1)),
                ('first_seen_at', models.DateTimeField(auto_now_add=True)),
                ('last_seen_at', models.DateTimeField(auto_now=True)),
                ('user', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='swing_tendencies',
                    to=settings.AUTH_USER_MODEL,
                )),
                ('last_seen_analysis', models.ForeignKey(
                    blank=True,
                    null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    to='shots.shotanalysis',
                )),
            ],
            options={'unique_together': {('user', 'tendency_type')}},
        ),
    ]
