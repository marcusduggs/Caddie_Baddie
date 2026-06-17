"""Re-queue background processing for shots whose processed video is missing or inaccessible.

Usage:
    # Re-queue all shots that have no processed video (or whose S3 file is missing):
    python manage.py requeue_processing

    # Re-queue every shot regardless of current state:
    python manage.py requeue_processing --all

    # Dry run (show what would be re-queued without doing anything):
    python manage.py requeue_processing --dry-run
"""

import os
import tempfile

import requests
from django.conf import settings
from django.core.management.base import BaseCommand
from django_q.tasks import async_task

from shots.models import ShotAnalysis


class Command(BaseCommand):
    help = 'Re-queue background processing for shots with missing/broken processed videos.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--all',
            action='store_true',
            help='Re-queue every shot that has an input video, not just broken ones.',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Print what would be re-queued without actually queuing anything.',
        )

    def handle(self, *args, **options):
        requeue_all = options['all']
        dry_run = options['dry_run']

        qs = ShotAnalysis.objects.exclude(input_video='').exclude(input_video=None).order_by('pk')
        self.stdout.write(f'Found {qs.count()} shots with an input video.')

        queued = 0
        skipped = 0

        for sa in qs:
            needs_requeue = requeue_all

            if not needs_requeue:
                # Re-queue if processed_video is missing entirely
                if not sa.processed_video:
                    needs_requeue = True
                else:
                    # Re-queue if the processed video URL returns a non-200 response
                    try:
                        url = sa.processed_video.url
                        if url.startswith('http'):
                            resp = requests.head(url, timeout=5, allow_redirects=True)
                            if resp.status_code != 200:
                                needs_requeue = True
                                self.stdout.write(
                                    f'  pk={sa.pk}: {url} -> {resp.status_code} (will re-queue)'
                                )
                        else:
                            # Local URL — can't stream from server disk; re-queue
                            needs_requeue = True
                            self.stdout.write(f'  pk={sa.pk}: local URL {url} (will re-queue)')
                    except Exception as e:
                        needs_requeue = True
                        self.stdout.write(f'  pk={sa.pk}: error checking URL ({e}) — will re-queue')

            if not needs_requeue:
                skipped += 1
                continue

            # Resolve input path — S3-backed fields raise NotImplementedError on .path
            try:
                input_path = sa.input_video.path
            except (NotImplementedError, ValueError):
                input_path = sa.input_video.url

            base_name = os.path.splitext(os.path.basename(sa.input_video.name))[0]
            out_root = str(settings.MEDIA_ROOT) if settings.MEDIA_ROOT else tempfile.gettempdir()
            output_path = os.path.join(out_root, 'output', f'{base_name}_requeued_{sa.pk}.mp4')

            if dry_run:
                self.stdout.write(f'  [DRY RUN] Would re-queue pk={sa.pk}: {input_path}')
            else:
                sa.status = 'uploading'
                sa.error_message = ''
                sa.save(update_fields=['status', 'error_message'])
                async_task('shots.tasks.process_video_background', sa.pk, input_path, output_path, None)
                self.stdout.write(f'  Queued pk={sa.pk}: {input_path}')

            queued += 1

        label = 'Would queue' if dry_run else 'Queued'
        self.stdout.write(self.style.SUCCESS(
            f'\nDone. {label} {queued} shot(s) for reprocessing. Skipped {skipped} (already OK).'
        ))
