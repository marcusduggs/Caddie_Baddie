"""
Video overlay processing module.
Contains functionality to overlay map images onto golf swing videos.
"""
import os
import subprocess
import uuid
import json
import re
import tempfile
import logging
from pathlib import Path
import shutil
from django.conf import settings
from urllib.request import urlopen
from urllib.error import URLError, HTTPError

# Set up logging
logger = logging.getLogger(__name__)


def _is_valid_file(path):
    """Return True if path is a non-empty string/Path-like and exists as a file."""
    if not path:
        return False
    # Accept Path objects and bytes as well
    if isinstance(path, (bytes, os.PathLike)):
        try:
            path = str(path)
        except Exception:
            return False
    if not isinstance(path, (str,)):
        return False
    try:
        return os.path.isfile(path)
    except Exception:
        return False

def _resolve_binary(name: str):
    """Resolve a binary by name, trying PATH first, then common Homebrew locations."""
    # Try PATH
    path = shutil.which(name)
    if path:
        return path
    # Try common Homebrew prefixes
    candidates = [
        f"/usr/local/bin/{name}",
        f"/opt/homebrew/bin/{name}",
    ]
    for candidate in candidates:
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    # Fallback to name (will likely fail, but keeps error messages clear)
    return name

# Full paths to ffmpeg and ffprobe (resolved once at import)
FFMPEG_PATH = _resolve_binary("ffmpeg")
FFPROBE_PATH = _resolve_binary("ffprobe")


def _probe_width(path):
    """Probe video width using ffprobe."""
    cmd = [FFPROBE_PATH, "-v", "error", "-select_streams", "v:0",
           "-show_entries", "stream=width", "-of", "csv=p=0", path]
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if p.returncode != 0:
        return None
    try:
        return int(p.stdout.strip())
    except Exception:
        return None


def _extract_coords_with_ffprobe(video_path):
    """
    Extract GPS coordinates from video metadata using ffprobe.
    
    Supports multiple formats:
    - Apple QuickTime: com.apple.quicktime.location.ISO6709 (e.g., "+21.9173-159.5286+000.000/")
    - Generic: location, GPSLatitude/GPSLongitude
    
    Returns:
        tuple: (longitude, latitude) or None if not found
    """
    try:
        cmd = [
            FFPROBE_PATH, '-v', 'quiet', '-print_format', 'json',
            '-show_format', '-show_streams', video_path
        ]
        
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
        
        if proc.returncode != 0:
            logger.warning(f"ffprobe failed: {proc.stderr.decode('utf-8', errors='ignore')}")
            return None
            
        info = json.loads(proc.stdout.decode('utf-8', errors='ignore') or '{}')
        
        # Search for coordinates in format and stream tags
        candidates = []
        
        # Check format tags
        fmt = info.get('format', {})
        tags = fmt.get('tags') or {}
        
        # Apple QuickTime ISO6709 format
        iso6709 = tags.get('com.apple.quicktime.location.ISO6709')
        if iso6709:
            candidates.append(('iso6709', iso6709))
            
        # Generic location tag
        location = tags.get('location')
        if location:
            candidates.append(('location', location))
            
        # Check stream tags
        for stream in info.get('streams', []) or []:
            stream_tags = stream.get('tags') or {}
            
            iso6709 = stream_tags.get('com.apple.quicktime.location.ISO6709')
            if iso6709:
                candidates.append(('iso6709', iso6709))
                
            location = stream_tags.get('location')
            if location:
                candidates.append(('location', location))
                
            # GPS coordinates (some formats)
            gps_lat = stream_tags.get('GPSLatitude')
            gps_lon = stream_tags.get('GPSLongitude')
            if gps_lat and gps_lon:
                candidates.append(('gps', (gps_lat, gps_lon)))
        
        # Parse candidates
        for tag_type, value in candidates:
            try:
                if tag_type == 'iso6709':
                    # ISO6709 format: +21.9173-159.5286+000.000/
                    # Pattern: latitude(+/-) longitude(+/-) altitude(+/-)
                    match = re.search(r'([+-]?\d+(?:\.\d+)?)([+-]?\d+(?:\.\d+)?)', value)
                    if match:
                        lat = float(match.group(1))
                        lon = float(match.group(2))
                        logger.info(f"Extracted GPS from ISO6709: lat={lat}, lon={lon}")
                        print(f"[GPS] Extracted coordinates from video: latitude={lat}, longitude={lon}")
                        return (lon, lat)  # Return as (longitude, latitude)
                        
                elif tag_type == 'location':
                    # Try to parse generic location format
                    match = re.search(r'([+-]?\d+(?:\.\d+)?)([+-]?\d+(?:\.\d+)?)', value)
                    if match:
                        lat = float(match.group(1))
                        lon = float(match.group(2))
                        logger.info(f"Extracted GPS from location tag: lat={lat}, lon={lon}")
                        print(f"[GPS] Extracted coordinates from video: latitude={lat}, longitude={lon}")
                        return (lon, lat)
                        
                elif tag_type == 'gps':
                    # Direct GPS lat/lon
                    gps_lat, gps_lon = value
                    lat = float(gps_lat)
                    lon = float(gps_lon)
                    logger.info(f"Extracted GPS from GPSLatitude/GPSLongitude: lat={lat}, lon={lon}")
                    print(f"[GPS] Extracted coordinates from video: latitude={lat}, longitude={lon}")
                    return (lon, lat)
                    
            except (ValueError, AttributeError) as e:
                logger.warning(f"Failed to parse coordinates from {tag_type}: {value}, error: {e}")
                continue
                
        logger.info("No GPS coordinates found in video metadata")
        print("[GPS] No GPS coordinates found in video metadata - using default location")
        return None
        
    except Exception as e:
        logger.error(f"Error extracting coordinates: {e}")
        print(f"[GPS] Error extracting coordinates: {e}")
        return None


def _fetch_mapbox_static_image(lon, lat, output_path, width=500, height=600, zoom=16):
    """
    Fetch a static map image from Mapbox Static Images API.
    
    Args:
        lon: Longitude
        lat: Latitude
        output_path: Where to save the downloaded image
        width: Image width in pixels
        height: Image height in pixels
        zoom: Map zoom level (1-20)
        
    Returns:
        str: Path to the downloaded image, or None if failed
    """
    # Get Mapbox token from settings
    mapbox_token = getattr(settings, 'MAPBOX_TOKEN', None) or os.environ.get('MAPBOX_TOKEN')
    
    if not mapbox_token:
        logger.error("MAPBOX_TOKEN not found in settings or environment")
        print("[Mapbox] ERROR: MAPBOX_TOKEN not configured")
        return None
    
    try:
        # Build Mapbox Static Images API URL
        # Format: https://api.mapbox.com/styles/v1/{username}/{style_id}/static/{overlay}/{lon},{lat},{zoom}/{width}x{height}{@2x}
        # With marker overlay: pin-s+color({lon},{lat})
        
        overlay = f"pin-s+ff0000({lon},{lat})"  # Small red pin marker
        from urllib.parse import quote
        overlay_enc = quote(overlay, safe='')
        
        # Use streets-v11 style
        url = (
            f"https://api.mapbox.com/styles/v1/mapbox/streets-v11/static/"
            f"{overlay_enc}/{lon},{lat},{zoom}/{width}x{height}"
            f"?access_token={mapbox_token}"
        )
        
        logger.info(f"Fetching map from Mapbox API: {url[:100]}...")
        print(f"[Mapbox] Fetching map image for coordinates: ({lon}, {lat})")
        
        # Download the image
        with urlopen(url, timeout=30) as response:
            data = response.read()
            
        # Save to file
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, 'wb') as f:
            f.write(data)
            
        # Set permissions
        try:
            os.chmod(output_path, 0o644)
        except Exception:
            pass
            
        logger.info(f"Successfully downloaded map image to {output_path}")
        print(f"[Mapbox] Map image downloaded successfully: {os.path.getsize(output_path)} bytes")
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
        logger.error(f"Unexpected error fetching map: {e}")
        print(f"[Mapbox] ERROR: Unexpected error: {e}")
        return None


def overlay_map_on_video(input_path: str, output_path: str, mapbox_token: str = None):
    """
    Legacy function for backwards compatibility.
    Wraps process_video_with_overlay with similar interface.
    
    Args:
        input_path: Path to input video
        output_path: Path to output video
        mapbox_token: Optional Mapbox token (now uses settings.MAPBOX_TOKEN)
    """
    return process_video_with_overlay(input_path, output_path)
