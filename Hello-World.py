#!/usr/bin/env python3
"""
Hello-World.py

Run ffmpeg to overlay "Hello World" onto ~/Desktop/Input/Golf.mov and write the result
to ~/Desktop/Output/Golf-out.mov. The script creates the Output directory if needed and
prints ffmpeg's output. It returns ffmpeg's exit code.

Usage:
  python3 ~/Desktop/Hello-World.py
  ~/Desktop/Hello-World.py    # after chmod +x
"""

import os
import shutil
import subprocess
import sys
import tempfile
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError
import urllib.parse
import json


def main():
    import argparse

    parser = argparse.ArgumentParser(description='Overlay image (from Mapbox or file) onto a video')
    parser.add_argument('--mapbox-token', default='[REDACTED_MAPBOX_TOKEN]', help='Mapbox access token (can also be set via MAPBOX_TOKEN env var)')
    parser.add_argument('--overlay-file', help='Path to a local image file to overlay (skips Mapbox fetch)')
    parser.add_argument('--input', default='~/Desktop/Input/Golf.mov', help='Input video path')
    parser.add_argument('--output', default='~/Desktop/Output/Golf-out.mov', help='Output video path')
    args = parser.parse_args()

    input_path = os.path.expanduser(args.input)
    output_path = os.path.expanduser(args.output)
    output_dir = os.path.dirname(output_path)

    if not os.path.exists(input_path):
        print(f"Input file not found: {input_path}")
        return 2

    os.makedirs(output_dir, exist_ok=True)

    # Decide whether to use a provided overlay file, or fetch from Mapbox
    overlay_tmp = None
    try:
        overlay_file = None
        if args.overlay_file:
            overlay_file = os.path.expanduser(args.overlay_file)
            if not os.path.exists(overlay_file):
                print(f"Overlay file not found: {overlay_file}")
                return 4

        if overlay_file is None:
            token = args.mapbox_token or os.environ.get('MAPBOX_TOKEN')
            if not token:
                print("No overlay file provided and no Mapbox token found (use --mapbox-token or set MAPBOX_TOKEN). Skipping map fetch.")
                return 5

            # First, try to extract GPS from the video's metadata using ffprobe
            def extract_coords_from_ffprobe(path: str):
                try:
                    cmd = [
                        'ffprobe', '-v', 'quiet', '-print_format', 'json',
                        '-show_format', '-show_streams', path
                    ]
                    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
                    if p.returncode != 0:
                        return None
                    info = json.loads(p.stdout.decode('utf-8', errors='ignore') or '{}')
                    # Search tags in format and streams for com.apple.quicktime.location.ISO6709
                    candidates = []
                    fmt = info.get('format', {})
                    tags = fmt.get('tags') or {}
                    loc = tags.get('com.apple.quicktime.location.ISO6709') or tags.get('location')
                    if loc:
                        candidates.append(loc)
                    for s in info.get('streams', []) or []:
                        stags = s.get('tags') or {}
                        loc = stags.get('com.apple.quicktime.location.ISO6709') or stags.get('location')
                        if loc:
                            candidates.append(loc)

                    import re
                    for c in candidates:
                        # ISO6709 style: +DD.DDDD+DDD.DDDD+ALT/  (lat then lon)
                        m = re.search(r'([+-]?\d+(?:\.\d+))([+-]?\d+(?:\.\d+))', c)
                        if m:
                            lat = float(m.group(1))
                            lon = float(m.group(2))
                            return lon, lat
                except Exception:
                    return None
                return None

            def read_video_coords():
                # Try ffprobe metadata first
                ff_coords = extract_coords_from_ffprobe(input_path)
                if ff_coords:
                    lon, lat = ff_coords
                    # Persist a copy to a couple of common Output.txt candidate locations
                    try:
                        out_paths = [
                            os.path.expanduser('~/desktop/Output/Output.txt'),
                            os.path.expanduser('~/Desktop/Output/Output.txt'),
                            os.path.expanduser('~/Desktop/Output.txt'),
                        ]
                        for op in out_paths:
                            try:
                                os.makedirs(os.path.dirname(op), exist_ok=True)
                                with open(op, 'w', encoding='utf-8') as ofh:
                                    ofh.write(f"{lon},{lat}\n")
                            except Exception:
                                pass
                    except Exception:
                        pass
                    return lon, lat

                # Fallback: read previously-generated Output.txt files
                candidates = [
                    os.path.expanduser('~/desktop/Output/Output.txt'),
                    os.path.expanduser('~/Desktop/Output.txt'),
                    os.path.expanduser('~/desktop/Output.txt'),
                    os.path.expanduser('~/Desktop/Output/Output.txt'),
                ]
                for p in candidates:
                    try:
                        if not os.path.exists(p):
                            continue
                        with open(p, 'r', encoding='utf-8') as fh:
                            for line in fh:
                                line = line.strip()
                                if not line or line.lower().startswith('longitude'):
                                    continue
                                parts = line.split(',')
                                if len(parts) >= 2:
                                    try:
                                        lon = float(parts[0])
                                        lat = float(parts[1])
                                        return lon, lat
                                    except Exception:
                                        continue
                    except Exception:
                        continue
                return None

            coords = read_video_coords()
            if coords:
                lon_val, lat_val = coords
                # Use canonical GeoJSON / Mapbox ordering: [longitude, latitude]
                first_val = lon_val
                second_val = lat_val
            else:
                # keep original defaults if no coords found (longitude,latitude)
                first_val = -73.99
                second_val = 40.7

            # GeoJSON expects [longitude, latitude]
            geojson_obj = json.dumps({"type": "Point", "coordinates": [first_val, second_val]})
            geojson_quoted = urllib.parse.quote(geojson_obj, safe='')
            center_part = f"{first_val},{second_val},16.5"
            mapbox_api = (
                "https://api.mapbox.com/styles/v1/mapbox/streets-v12/static/"
                f"geojson({geojson_quoted})/"
                f"{center_part}/300x350"
            )
            mapbox_url = f"{mapbox_api}?access_token={token}"

            print(f"Fetching Mapbox image from: {mapbox_url}")
            req = Request(mapbox_url, headers={"User-Agent": "hello-world-script/1.0"})
            try:
                with urlopen(req, timeout=15) as resp:
                    data = resp.read()
            except HTTPError as e:
                if e.code == 401:
                    print("Mapbox returned 401 Unauthorized. The token may be invalid or expired. Provide a valid token via --mapbox-token or MAPBOX_TOKEN.")
                else:
                    print(f"HTTP error fetching map image: {e.code} {e.reason}")
                return 3
            except URLError as e:
                print(f"URL error fetching map image: {e}")
                return 3

            # Save the fetched image to a temporary PNG file
            with tempfile.NamedTemporaryFile(mode='wb', suffix='.png', delete=False) as tf:
                tf.write(data)
                overlay_tmp = tf.name

            overlay_file = overlay_tmp

        print(f"Using overlay image: {overlay_file}")

        # Build ffmpeg command to overlay the image bottom-right with 10px margin
        filter_complex = "[0:v][1:v]overlay=W-w-10:H-h-10"
        cmd = [
            'ffmpeg', '-y',
            '-i', input_path,
            '-i', overlay_file,
            '-filter_complex', filter_complex,
            '-c:a', 'copy',
            output_path,
        ]

        print('Running ffmpeg to overlay image...')
        print(' '.join(shlex_quote(a) for a in cmd))

        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        sys.stdout.buffer.write(proc.stdout)
        return proc.returncode
    finally:
        # Clean up temporary overlay image
        try:
            if overlay_tmp and os.path.exists(overlay_tmp):
                os.remove(overlay_tmp)
        except Exception:
            pass


def shlex_quote(s: str) -> str:
    # Minimal quoting for printing commands (not used to build cmd)
    if any(c.isspace() for c in s):
        return '"' + s.replace('"', '\\"') + '"'
    return s


if __name__ == '__main__':
    raise SystemExit(main())
