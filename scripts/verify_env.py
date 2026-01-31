"""Simple environment verifier to run inside the project venv.

Usage: python scripts/verify_env.py

Prints whether key binaries are available and whether optional features (drawtext, Mapbox token)
are present.
"""
import os
import shutil
import subprocess


def which(name):
    return shutil.which(name)


def ffmpeg_has_drawtext(ffmpeg_bin='ffmpeg'):
    try:
        p = subprocess.run([ffmpeg_bin, '-hide_banner', '-filters'], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        out = (p.stdout or b'') + (p.stderr or b'')
        return b'drawtext' in out.lower()
    except Exception:
        return False


def main():
    print('Checking environment for Caddie_Baddie')
    py = which('python3')
    print('python3 ->', py or 'NOT FOUND')
    ff = which('ffmpeg')
    print('ffmpeg ->', ff or 'NOT FOUND')
    fp = which('ffprobe')
    print('ffprobe ->', fp or 'NOT FOUND')
    if ff:
        print('ffmpeg drawtext filter available ->', ffmpeg_has_drawtext(ff))
    print('MAPBOX_TOKEN set ->', bool(os.environ.get('MAPBOX_TOKEN')))
    try:
        import django
        print('django import -> OK', django.get_version())
    except Exception as e:
        print('django import -> FAILED', e)
    try:
        import cv2
        print('opencv import -> OK')
    except Exception:
        print('opencv import -> NOT INSTALLED')
    try:
        import mediapipe as mp
        print('mediapipe import -> OK')
    except Exception:
        print('mediapipe import -> NOT INSTALLED')

if __name__ == '__main__':
    main()
