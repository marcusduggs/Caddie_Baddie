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
        logger.error(f"Failed to fetch map from Mapbox API: {e}")
        print(f"[Mapbox] ERROR: Failed to fetch map: {e}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error fetching map: {e}")
        print(f"[Mapbox] ERROR: Unexpected error: {e}")
        return None


def process_video_with_overlay(input_path: str, output_path: str, overlay_path: str = None,
                               course_name: str = None, hole_number: int = None, hole_yardage: int = None, club: str = None, hole_par: int = None):
    """
    Process a golf video by overlaying a map image in the bottom-right corner.
    
    This function:
    1. Extracts GPS coordinates from video metadata
    2. Fetches a custom map from Mapbox API based on those coordinates
    3. Overlays the map on the video using ffmpeg
    4. Falls back to static map if GPS extraction or API call fails
    
    Args:
        input_path: Absolute path to the input video file
        output_path: Absolute path where the processed video should be saved
        overlay_path: Optional path to overlay image. If None, will try to fetch from Mapbox API
        
    Returns:
        str: Path to the processed output video
        
    Raises:
        FileNotFoundError: If input video doesn't exist
        RuntimeError: If ffmpeg processing fails
    """
    # Validate input
    if not os.path.isfile(input_path):
        raise FileNotFoundError(f"Input video not found: {input_path}")

    # Determine overlay image to use
    use_dynamic_map = overlay_path is None
    temp_map_path = None
    
    if use_dynamic_map:
        print("\n" + "="*60)
        print("Starting GPS-based map overlay process")
        print("="*60)
        
        # Step 1: Extract GPS coordinates from video
        coords = _extract_coords_with_ffprobe(input_path)
        
        if coords:
            lon, lat = coords
            
            # Step 2: Fetch map from Mapbox API
            temp_map_path = os.path.join(
                tempfile.gettempdir(),
                f"mapbox_map_{uuid.uuid4().hex[:8]}.png"
            )
            
            fetched_map = _fetch_mapbox_static_image(lon, lat, temp_map_path)
            
            if fetched_map:
                overlay_path = fetched_map
                print(f"[Success] Using dynamic map based on video GPS coordinates")
            else:
                print(f"[Warning] Failed to fetch map from Mapbox, falling back to static map")
                overlay_path = None
        else:
            print(f"[Info] No GPS coordinates found, using fallback map")
            overlay_path = None
    
    # Fallback to static map if needed
    if overlay_path is None:
        project_root = Path(settings.BASE_DIR)
        overlay_path = str(project_root / "test_map.png")
        print(f"[Fallback] Using static map: {overlay_path}")
    
    # Validate overlay image exists
    if not os.path.isfile(overlay_path):
        raise FileNotFoundError(f"Overlay image not found: {overlay_path}")

    # Ensure output directory exists
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    
    # Create logs directory for debugging
    logs_dir = Path(settings.MEDIA_ROOT) / "logs"
    logs_dir.mkdir(exist_ok=True, parents=True)
    log_file = logs_dir / f"overlay_{uuid.uuid4().hex[:8]}.log"

    # Probe video width and calculate overlay size (30% of video width)
    vwidth = _probe_width(input_path) or 1280
    overlay_w = max(64, int(vwidth * 0.30))

    # Build ffmpeg filter: scale overlay, keep aspect ratio, then overlay bottom-right with 10px margin
    base_overlay = f"[1:v]scale={overlay_w}:-1[map];[0:v][map]overlay=main_w-overlay_w-10:main_h-overlay_h-10"

    # If course/hole text provided, append a drawtext filter to burn text into the video (top-left)
    drawtext_filter = ""
    temp_text_files = []
    if course_name or hole_number or hole_yardage or club:
        # Compose the individual text parts so we can style them separately:
        # part_course (prominent), part_main (Hole X — Y yards), part_par (Par N), part_club
        def _sanitize(s: str) -> str:
            if not s:
                return ''
            s = s.replace('\u00A0', ' ')
            for ch in ('\u200b', '\u200c', '\u200d', '\ufeff'):
                s = s.replace(ch, '')
            s = re.sub(r'[\x00-\x09\x0b-\x1f\x7f-\x9f]', '', s)
            return s.strip()

        part_course = _sanitize(str(course_name)) if course_name else ''
        main_parts = []
        if hole_number:
            main_parts.append(f"Hole {int(hole_number)}")
        if hole_yardage:
            main_parts.append(f"{int(hole_yardage)} yards")
        part_main = ' — '.join(main_parts) if main_parts else ''
        part_par = ''
        # We try to read par from a transient variable _hole_par on analysis, but the view
        # passes it into process_video_with_overlay as hole_par parameter. Use it if present.
        # Note: hole_par parameter is provided to this function signature above.
        if hole_par is not None:
            try:
                part_par = f"Par {int(hole_par)}"
            except Exception:
                part_par = f"Par {hole_par}"
        part_club = _sanitize(str(club)) if club else ''

        # Choose font
        font_paths = [
            '/Library/Fonts/Arial Bold.ttf',
            '/Library/Fonts/Arial.ttf',
            '/System/Library/Fonts/SFNSDisplay.ttf',
            '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf',
            '/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf'
        ]
        fontfile = None
        for p in font_paths:
            if os.path.exists(p):
                fontfile = p
                break

        # Font sizes proportional to video width
        fontsize_course = max(20, int(vwidth * 0.035))
        fontsize_main = max(16, int(vwidth * 0.028))
        # Make the par and club lines the same size as the main (Hole X — Y yards)
        fontsize_small = fontsize_main
        pad_x = 18
        pad_y = 14

        # Create temp text files for each visible part (useful to avoid escaping issues)
        def _write_temp(text, suffix):
            if not text:
                return None
            tf = logs_dir / f"overlay_text_{suffix}_{uuid.uuid4().hex[:8]}.txt"
            try:
                with open(tf, 'w', encoding='utf-8') as fh:
                    fh.write(text)
                temp_text_files.append(tf)
                return tf
            except Exception:
                return None

        tf_course = _write_temp(part_course, 'course')
        tf_main = _write_temp(part_main, 'main')
        tf_par = _write_temp(part_par, 'par')
        tf_club = _write_temp(part_club, 'club')

        # Compute box dimensions (approximate): width is a fraction of video width, height based on font sizes and visible lines
        box_w = min( int(vwidth * 0.48), int(vwidth * 0.9) )
        visible_lines = sum(1 for t in (part_course, part_main, part_par, part_club) if t)
        box_h = pad_y * 2 + fontsize_course * (1 if part_course else 0) + fontsize_main * (1 if part_main else 0) + fontsize_small * ( (1 if part_par else 0) + (1 if part_club else 0) ) + max(0, (visible_lines - 1) * 6)

        # Build a drawbox filter to render a single semi-transparent background behind the text
        # Use slightly rounded corners would be nicer but drawbox doesn't support rounding; keep it simple.
        box_x = 10
        box_y = 10
        drawbox = f"drawbox=x={box_x}:y={box_y}:w={box_w}:h={box_h}:color=black@0.55:t=fill"

        # Build drawtext filters for each line (place them stacked inside the box)
        drawtexts = []
        # course (top)
        if tf_course:
            y_course = box_y + pad_y
            font_arg = f"fontfile={fontfile}:" if fontfile else ""
            drawtexts.append(f"drawtext={font_arg}textfile={str(tf_course)}:reload=0:fontcolor=white:fontsize={fontsize_course}:x={box_x+pad_x}:y={y_course}:shadowx=1:shadowy=1:shadowcolor=black@0.6")
            y_next = y_course + fontsize_course + 6
        else:
            y_next = box_y + pad_y

        # main (hole + yardage)
        if tf_main:
            y_main = y_next
            drawtexts.append(f"drawtext={font_arg}textfile={str(tf_main)}:reload=0:fontcolor=white:fontsize={fontsize_main}:x={box_x+pad_x}:y={y_main}:shadowx=1:shadowy=1:shadowcolor=black@0.6")
            y_next = y_main + fontsize_main + 6

        # par
        if tf_par:
            y_par = y_next
            # Use the same font size as the main hole line for visual consistency
            drawtexts.append(f"drawtext={font_arg}textfile={str(tf_par)}:reload=0:fontcolor=#e6e6e6:fontsize={fontsize_main}:x={box_x+pad_x}:y={y_par}:shadowx=1:shadowy=1:shadowcolor=black@0.6")
            y_next = y_par + fontsize_main + 4

        # club
        if tf_club:
            y_club = y_next
            drawtexts.append(f"drawtext={font_arg}textfile={str(tf_club)}:reload=0:fontcolor=#ddddff:fontsize={fontsize_main}:x={box_x+pad_x}:y={y_club}:shadowx=1:shadowy=1:shadowcolor=black@0.6")

        # Combine drawbox + drawtexts into drawtext_filter (comma-separated)
        drawtext_filter = drawbox + ("," + ",".join(drawtexts) if drawtexts else "")

    filter_complex = base_overlay + ("," + drawtext_filter if drawtext_filter else "")

    print(f"[FFmpeg] Processing video with overlay...")
    
    # Build ffmpeg command
    cmd = [
        FFMPEG_PATH, "-y",
        "-i", input_path,
        "-i", overlay_path,
        "-filter_complex", filter_complex,
        "-map", "0:a?",   # copy audio if present
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "128k",
        "-movflags", "+faststart",
        output_path
    ]

    # Run ffmpeg
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    
    # Write ffmpeg output to log for debugging
    with open(log_file, "w") as fh:
        fh.write("CMD: " + " ".join(cmd) + "\n\n")
        fh.write("STDOUT:\n")
        fh.write(proc.stdout or "")
        fh.write("\n\nSTDERR:\n")
        fh.write(proc.stderr or "")

    # Clean up temporary map file if created
    if temp_map_path and os.path.exists(temp_map_path):
        try:
            os.remove(temp_map_path)
            print(f"[Cleanup] Removed temporary map file")
        except Exception as e:
            logger.warning(f"Failed to remove temp map file: {e}")
    # Clean up temporary text files used for drawtext (if any)
    try:
        for tf in temp_text_files:
            try:
                if tf is not None and tf.exists():
                    os.remove(str(tf))
                    print(f"[Cleanup] Removed temporary drawtext file: {tf}")
            except Exception:
                pass
    except Exception:
        # temp_text_files may not exist in some code paths
        pass

    # Check for errors
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg failed (log: {log_file}): {proc.stderr[:2000]}")

    # Set file permissions
    try:
        os.chmod(output_path, 0o644)
    except Exception:
        pass

    print(f"[Success] Processed video saved to: {output_path}")
    print("="*60 + "\n")
    
    return str(output_path)


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
