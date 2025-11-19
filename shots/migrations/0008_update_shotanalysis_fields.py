# Generated migration for updating ShotAnalysis model
from django.db import migrations, models


def set_default_values(apps, schema_editor):
    """Set default values for existing rows before applying NOT NULL constraints."""
    ShotAnalysis = apps.get_model('shots', 'ShotAnalysis')
    # Set default distance for any NULL values
    ShotAnalysis.objects.filter(distance__isnull=True).update(distance='0')
    # Set default club for any NULL or empty values
    ShotAnalysis.objects.filter(club__isnull=True).update(club='Unknown')
    ShotAnalysis.objects.filter(club='').update(club='Unknown')


class Migration(migrations.Migration):

    dependencies = [
        ('shots', '0007_alter_shotanalysis_distance'),
    ]

    operations = [
        # First, set default values for existing rows
        migrations.RunPython(set_default_values, reverse_code=migrations.RunPython.noop),
        
        # Rename video to input_video
        migrations.RenameField(
            model_name='shotanalysis',
            old_name='video',
            new_name='input_video',
        ),
        # Change processed_video upload path from 'processed/' to 'output/'
        migrations.AlterField(
            model_name='shotanalysis',
            name='processed_video',
            field=models.FileField(blank=True, null=True, upload_to='output/'),
        ),
        # Change distance from CharField to FloatField
        migrations.AlterField(
            model_name='shotanalysis',
            name='distance',
            field=models.FloatField(),
        ),
        # Change club to be non-nullable with max_length=50
        migrations.AlterField(
            model_name='shotanalysis',
            name='club',
            field=models.CharField(max_length=50),
        ),
        # Remove fields that are no longer in the model
        migrations.RemoveField(
            model_name='shotanalysis',
            name='accuracy',
        ),
        migrations.RemoveField(
            model_name='shotanalysis',
            name='longitude',
        ),
        migrations.RemoveField(
            model_name='shotanalysis',
            name='latitude',
        ),
        migrations.RemoveField(
            model_name='shotanalysis',
            name='result_json',
        ),
    ]
