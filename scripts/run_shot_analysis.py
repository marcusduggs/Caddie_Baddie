#!/usr/bin/env python3
import os, sys
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'golf_caddie.settings')
import django
django.setup()
from shots import utils
from shots.models import ShotAnalysis
from django.core.files import File

orig = os.path.expanduser('~/Desktop/Input/Golf.mov')
if not os.path.exists(orig):
    print('ERROR: input file not found:', orig)
    sys.exit(2)

print('Running analyze_video on', orig)
res = utils.analyze_video(orig, output_dir=os.path.join(os.getcwd(),'media','processed'))
print('analyze_video returned:', res)
proc = res.get('processed_path') or orig
print('Processed path:', proc, 'exists?', os.path.exists(proc))

# Create ShotAnalysis and save files to media via FileField
sa = ShotAnalysis()
with open(orig, 'rb') as f:
    sa.video.save(os.path.basename(orig), File(f), save=False)
with open(proc, 'rb') as f:
    sa.processed_video.save(os.path.basename(proc), File(f), save=False)
sa.club = res.get('club') or ''
sa.distance = res.get('distance')
sa.accuracy = res.get('accuracy')
sa.longitude = res.get('longitude')
sa.latitude = res.get('latitude')
sa.result_json = res.get('raw')
sa.save()
print('Created ShotAnalysis id', sa.pk)
print('Video URL:', sa.video.url)
print('Processed URL:', sa.processed_video.url)
