from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('shots', '0029_add_selected_tee_to_shotround'),
    ]

    operations = [
        migrations.AddField(
            model_name='shotanalysis',
            name='ai_main_fault',
            field=models.TextField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='shotanalysis',
            name='ai_strength',
            field=models.TextField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='shotanalysis',
            name='ai_drill',
            field=models.TextField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='shotanalysis',
            name='ai_swing_thought',
            field=models.TextField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='shotanalysis',
            name='ai_metrics_json',
            field=models.TextField(blank=True, null=True),
        ),
    ]
