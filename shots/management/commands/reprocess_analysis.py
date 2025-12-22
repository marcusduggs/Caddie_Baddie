from django.core.management.base import BaseCommand, CommandError
from django.core.files import File
from django.conf import settings
import os
import traceback

from shots.models import ShotAnalysis
from utils.overlay import process_video_with_overlay


class Command(BaseCommand):
    help = 'Reprocess an existing ShotAnalysis by id. Regenerates the processed video using current overlay logic.'

    def add_arguments(self, parser):
        parser.add_argument('analysis_id', type=int, help='ID of the ShotAnalysis to reprocess')

    def handle(self, *args, **options):
        analysis_id = options['analysis_id']
        try:
            sa = ShotAnalysis.objects.get(pk=analysis_id)
        except ShotAnalysis.DoesNotExist:
            raise CommandError(f'ShotAnalysis with id={analysis_id} not found')

        if not sa.input_video:
            self.stdout.write(self.style.ERROR('Selected analysis has no input video file.'))
            return

        input_path = sa.input_video.path
        base_name = os.path.splitext(os.path.basename(sa.input_video.name))[0]
        output_filename = f"{base_name}_processed.mp4"
        output_dir = os.path.join(settings.MEDIA_ROOT, 'output')
        os.makedirs(output_dir, exist_ok=True)
        output_path = os.path.join(output_dir, output_filename)

        # Remove any existing output file so we start fresh
        try:
            if os.path.exists(output_path):
                os.remove(output_path)
        except Exception as e:
            self.stdout.write(self.style.WARNING(f'Could not remove existing output file: {e}'))

        # Update status
        sa.status = 'processing'
        sa.error_message = ''
        sa.save()

        try:
            self.stdout.write(f'Reprocessing analysis {analysis_id}: {input_path} -> {output_path}')

            # Call the overlay processor with the metadata saved on the analysis
            process_video_with_overlay(
                input_path,
                output_path,
                None,
                sa.course_name,
                sa.hole_number,
                sa.hole_yardage,
                sa.club,
                hole_par=getattr(sa, 'hole_par', None),
            )

            if os.path.exists(output_path):
                with open(output_path, 'rb') as f:
                    sa.processed_video.save(os.path.basename(output_path), File(f), save=False)

            sa.status = 'completed'
            sa.error_message = ''
            sa.save()

            self.stdout.write(self.style.SUCCESS(f'Analysis {analysis_id} reprocessed successfully. Output: {sa.processed_video.url if sa.processed_video else output_path}'))

        except Exception as e:
            tb = traceback.format_exc()
            sa.status = 'failed'
            sa.error_message = str(e)
            sa.save()
            self.stdout.write(self.style.ERROR(f'Failed to reprocess analysis {analysis_id}: {e}'))
            self.stdout.write(tb)
