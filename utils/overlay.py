"""Minimal, defensive overlay helpers used by the app.

This module provides two small helpers the project relies on:

- _extract_coords_with_ffprobe(video_path) -> (lon, lat) | None
- process_video_with_overlay(input_path, output_path, coords=...) -> str | None

The implementation is intentionally small and tolerant. It will not raise if
optional external tools or services are unavailable; it returns None on
failures so callers can mark processing as skipped.
"""

from pathlib import Path
import os
import re
import json
import subprocess
import logging
import shutil
from urllib.request import urlopen
from urllib.error import URLError, HTTPError
from django.conf import settings

logger = logging.getLogger(__name__)


def _resolve_binary(name: str):
    p = shutil.which(name)
    if p:
        return p
    # common Homebrew /usr/local locations
    for cand in (f"/opt/homebrew/bin/{name}", f"/usr/local/bin/{name}"):
        if os.path.exists(cand) and os.access(cand, os.X_OK):
            return cand
    return name


FFMPEG_PATH = _resolve_binary("ffmpeg")
FFPROBE_PATH = _resolve_binary("ffprobe")


def _ffmpeg_has_drawtext():
    """Return True if ffmpeg reports a 'drawtext' filter is available."""
    try:
        cmd = [FFMPEG_PATH, '-hide_banner', '-filters']
        p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        out = (p.stdout or b'') + (p.stderr or b'')
        text = out.decode('utf-8', errors='ignore').lower()
        return 'drawtext' in text
    except Exception:
        return False


FFMPEG_HAS_DRAWTEXT = _ffmpeg_has_drawtext()


def _extract_coords_with_ffprobe(video_path: str):
    """Return (lon, lat) extracted from ffprobe metadata, or None.

    Looks for common QuickTime/EXIF tags. This is best-effort and returns
    None on any error.
    """
    try:
        cmd = [FFPROBE_PATH, '-v', 'quiet', '-print_format', 'json', '-show_format', '-show_streams', str(video_path)]
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if proc.returncode != 0:
            return None
        info = json.loads(proc.stdout.decode('utf-8', errors='ignore') or '{}')

        fmt = info.get('format', {})
        tags = fmt.get('tags') or {}
        cand = tags.get('com.apple.quicktime.location.ISO6709') or tags.get('location')
        if cand:
            m = re.search(r'([+-]?\d+(?:\.\d+)?)([+-]?\d+(?:\.\d+)?)', cand)
            if m:
                lat = float(m.group(1))
                lon = float(m.group(2))
                return (lon, lat)

        for s in info.get('streams', []) or []:
            st = s.get('tags') or {}
            cand = st.get('com.apple.quicktime.location.ISO6709') or st.get('location')
            if cand:
                m = re.search(r'([+-]?\d+(?:\.\d+)?)([+-]?\d+(?:\.\d+)?)', cand)
                if m:
                    lat = float(m.group(1))
                    lon = float(m.group(2))
                    return (lon, lat)
            lat = st.get('GPSLatitude')
            lon = st.get('GPSLongitude')
            if lat and lon:
                try:
                    return (float(lon), float(lat))
                except Exception:
                    pass
        return None
    except Exception:
        return None


def _fetch_mapbox_static_image(lon: float, lat: float, output_path: str, width=500, height=600, zoom=16):
    token = getattr(settings, 'MAPBOX_TOKEN', None) or os.environ.get('MAPBOX_TOKEN')
    if not token:
        return None
    try:
        from urllib.parse import quote
        overlay = quote(f"pin-s+ff0000({lon},{lat})", safe='')
        url = (
            f"https://api.mapbox.com/styles/v1/mapbox/streets-v11/static/"
            f"{overlay}/{lon},{lat},{zoom}/{width}x{height}?access_token={token}"
        )
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with urlopen(url, timeout=30) as resp:
            data = resp.read()
        with open(output_path, 'wb') as fh:
            fh.write(data)
        return output_path
    except (URLError, HTTPError) as e:
        logger.debug("Mapbox fetch failed: %s", e)
        return None
    except Exception:
        return None


def process_video_with_overlay(input_path: str, output_path: str, *args, **kwargs):
    """Overlay a small static map when coords exist; otherwise copy/re-encode.

    Backwards-compatible wrapper that accepts legacy positional metadata
    arguments. The canonical parameters are:

        process_video_with_overlay(input_path, output_path, coords=None, map_width=..., map_height=...)

    But older call sites pass additional metadata (course_name, hole_number, etc.).
    This function extracts coords from the third positional argument if present
    or from kwargs.get('coords'). Other legacy args are ignored.

    Returns output_path (str) on success or None on failure.
    """
    # Pull canonical params out of args/kwargs and support older call signatures
    coords = None
    map_width = kwargs.get('map_width', 500)
    map_height = kwargs.get('map_height', 600)
    include_course_text = kwargs.get('include_course_text', False)
    overlay_map_requested = kwargs.get('overlay_map_requested', False)

    # Legacy callers sometimes pass: (coords, course_name, hole_number, hole_yardage, club)
    course_name = kwargs.get('course_name')
    hole_number = kwargs.get('hole_number')
    hole_yardage = kwargs.get('hole_yardage')
    club = kwargs.get('club')
    hole_par = kwargs.get('hole_par')

    # Interpret positional args loosely
    if len(args) >= 1:
        first = args[0]
        # if first looks like coords (tuple/list of 2 numbers) use it
        try:
            if isinstance(first, (list, tuple)) and len(first) == 2:
                coords = (float(first[0]), float(first[1]))
            elif isinstance(first, (int, float)):
                # unlikely, treat as no coords
                coords = None
            else:
                coords = None
        except Exception:
            coords = None
    if 'coords' in kwargs:
        coords = kwargs.get('coords')

    # parse additional legacy positional metadata if present
    if len(args) >= 2 and not course_name:
        course_name = args[1]
    if len(args) >= 3 and not hole_number:
        hole_number = args[2]
    if len(args) >= 4 and not hole_yardage:
        hole_yardage = args[3]
    if len(args) >= 5 and not club:
        club = args[4]
    # the boolean overlay_map_requested may be passed as a later positional arg
    if len(args) >= 6 and not overlay_map_requested:
        try:
            overlay_map_requested = bool(args[5])
        except Exception:
            pass
    if len(args) >= 7 and not include_course_text:
        try:
            include_course_text = bool(args[6])
        except Exception:
            pass

    input_path = str(input_path)
    output_path = str(output_path)
    if not os.path.exists(input_path):
        logger.error("Input missing: %s", input_path)
        return None

    def _build_text_label():
        parts = []
        if course_name:
            parts.append(str(course_name))
        if hole_number:
            parts.append(f"Hole {hole_number}")
        if hole_yardage:
            parts.append(f"{hole_yardage}yd")
        if club:
            parts.append(str(club))
        if hole_par:
            parts.append(f"Par {hole_par}")
        info = ' | '.join(parts)
        return info.replace("'", "\\'").replace(':', '\\:')

    needs_map = overlay_map_requested and coords
    needs_text = include_course_text and FFMPEG_HAS_DRAWTEXT

    try:
        # Fast path: stream copy only when no visual changes are needed
        if not needs_map and not needs_text:
            cmd = [FFMPEG_PATH, '-y', '-i', input_path, '-c', 'copy', output_path]
            p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            if p.returncode == 0:
                return output_path
            # stream copy failed (e.g. container mismatch) — fall through to re-encode

        # Fetch Mapbox static image when map overlay is requested and we have coords
        map_path = None
        if needs_map:
            try:
                lon, lat = coords
            except Exception:
                lon = lat = None
            if lon is not None and lat is not None:
                tmp = Path(output_path).with_suffix('')
                mapfile = str(tmp.parent / (tmp.name + '_map.png'))
                fetched = _fetch_mapbox_static_image(lon, lat, mapfile, width=map_width, height=map_height)
                if fetched and os.path.exists(fetched):
                    map_path = fetched

        if map_path:
            # Map overlay (bottom-right) + optional text burn-in (top-left)
            if needs_text:
                info = _build_text_label()
                if info:
                    filter_complex = (
                        f"[0:v][1:v] overlay=main_w-overlay_w-10:main_h-overlay_h-10 [ov];"
                        f"[ov] drawtext=text='{info}':fontcolor=white:fontsize=42:box=1:boxcolor=0x00000088:boxborderw=10:x=10:y=10"
                    )
                else:
                    filter_complex = "[0:v][1:v] overlay=main_w-overlay_w-10:main_h-overlay_h-10"
            else:
                filter_complex = "[0:v][1:v] overlay=main_w-overlay_w-10:main_h-overlay_h-10"
            cmd = [
                FFMPEG_PATH, '-y',
                '-i', input_path,
                '-i', map_path,
                '-filter_complex', filter_complex,
                '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '23',
                '-c:a', 'copy',
                output_path,
            ]
        elif needs_text:
            # Text-only burn-in (no map — either not requested or no GPS coords)
            info = _build_text_label()
            if info:
                vf = f"drawtext=text='{info}':fontcolor=white:fontsize=42:box=1:boxcolor=0x00000088:boxborderw=10:x=10:y=10"
                cmd = [
                    FFMPEG_PATH, '-y',
                    '-i', input_path,
                    '-vf', vf,
                    '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '23',
                    '-c:a', 'copy',
                    output_path,
                ]
            else:
                # No text content to burn — just re-encode
                cmd = [FFMPEG_PATH, '-y', '-i', input_path, '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '23', '-c:a', 'copy', output_path]
        else:
            # Re-encode without overlays (stream copy failed above)
            cmd = [FFMPEG_PATH, '-y', '-i', input_path, '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '23', '-c:a', 'copy', output_path]

        p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if p.returncode == 0 and os.path.exists(output_path):
            try:
                if map_path and os.path.exists(map_path):
                    os.remove(map_path)
            except Exception:
                pass
            return output_path
        logger.info("ffmpeg failed: %s", p.stderr.decode('utf-8', errors='ignore'))
        return None
    except Exception as e:
        logger.exception("process_video_with_overlay error: %s", e)
        return None


def overlay_map_on_video(input_path: str, output_path: str, mapbox_token: str = None):
    """Backward-compatible wrapper."""
    return process_video_with_overlay(input_path, output_path)
