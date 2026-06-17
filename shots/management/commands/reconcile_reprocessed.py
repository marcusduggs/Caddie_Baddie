from django.core.management.base import BaseCommand
from django.core.management.base import BaseCommand
from django.conf import settings
from django.core.files import File as DjangoFile
import os
import glob
import re
import logging

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Attach reprocess_*.mp4 files from MEDIA_ROOT/output to their ShotAnalysis records by pk.'

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true', help='Report actions without writing DB/files')
        parser.add_argument('--media-root', dest='media_root', help='Path to MEDIA_ROOT if not using Django settings')

    def handle(self, *args, **options):
        media_root = options.get('media_root') or getattr(settings, 'MEDIA_ROOT', None)
        # Fallback: try to infer a repo-level media directory (two levels up + /media)
        if not media_root:
            here = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
            candidate = os.path.join(here, 'media')
            if os.path.isdir(candidate):
                media_root = candidate

        if not media_root:
            self.stderr.write('MEDIA_ROOT is not configured and could not be inferred. Use --media-root to specify it.')
            return

        out_dir = os.path.join(media_root, 'output')
        if not os.path.isdir(out_dir):
            self.stderr.write(f'Output directory does not exist: {out_dir}')
            return

        # collect reprocess files and group by detected pk, allowing optional suffixes
        pattern = os.path.join(out_dir, 'reprocess_*.mp4')
        all_files = glob.glob(pattern)
        if not all_files:
            self.stdout.write('No reprocess_*.mp4 files found')
            return

        files_by_pk = {}
        # match reprocess_{pk} or reprocess_{pk}_suffix.mp4
        fname_re = re.compile(r'reprocess_(\d+)(?:_.+)?\.mp4$')
        for path in all_files:
            base = os.path.basename(path)
            m = fname_re.match(base)
            if not m:
                self.stdout.write(f'Skipping file with unexpected name: {base}')
                continue
            pk = int(m.group(1))
            files_by_pk.setdefault(pk, []).append(path)

        # pick the newest file for each pk (most recent mtime)
        chosen = {}
        for pk, paths in files_by_pk.items():
            paths.sort(key=lambda p: os.path.getmtime(p), reverse=True)
            chosen[pk] = paths[0]

        from shots.models import ShotAnalysis

        for pk, path in sorted(chosen.items()):
            base = os.path.basename(path)
            try:
                sa = ShotAnalysis.objects.get(pk=pk)
            except ShotAnalysis.DoesNotExist:
                self.stdout.write(f'No ShotAnalysis with pk={pk} for file {base}')
                continue

            # If processed_video already attached, skip
            try:
                has_file = bool(sa.processed_video and sa.processed_video.name)
            except Exception:
                has_file = False

            if has_file:
                self.stdout.write(f'Already attached: sa.pk={pk} -> {sa.processed_video.name}')
                continue

            self.stdout.write(f'Will attach {base} -> ShotAnalysis.pk={pk}')
            if options.get('dry_run'):
                continue

            try:
                with open(path, 'rb') as fh:
                    sa.processed_video.save(base, DjangoFile(fh), save=True)
                sa.status = 'completed'
                sa.error_message = ''
                sa.save()
                self.stdout.write(f'Attached and updated ShotAnalysis.pk={pk}')
            except Exception as e:
                logger.exception('Failed to attach %s to ShotAnalysis %s', path, pk)
                self.stderr.write(f'Failed to attach {base} to ShotAnalysis.pk={pk}: {e}')
