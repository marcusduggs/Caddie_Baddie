from django.db import migrations, models

class Migration(migrations.Migration):

    dependencies = [
        ('shots', '0022_add_course_tee_names'),
    ]

    operations = [
        migrations.AddField(
            model_name='shotanalysis',
            name='overlayed_video',
            field=models.FileField(blank=True, null=True, upload_to='overlayed/'),
        ),
        migrations.AddField(
            model_name='shotanalysis',
            name='overlay_requested',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='shotanalysis',
            name='overlay_status',
            field=models.CharField(choices=[('pending', 'Pending'), ('overlaying', 'Overlaying'), ('completed', 'Completed'), ('failed', 'Failed')], default='pending', max_length=20),
        ),
        migrations.AddField(
            model_name='shotanalysis',
            name='overlay_error_message',
            field=models.TextField(blank=True, null=True),
        ),
    ]
