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
from django.conf import settings
from urllib.request import urlopen
from urllib.error import URLError, HTTPError

# Set up logging
logger = logging.getLogger(__name__)

# Full paths to ffmpeg and ffprobe
FFMPEG_PATH = "ffmpeg"
FFPROBE_PATH = "ffprobe"


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


def process_video_with_overlay(input_path: str, output_path: str, overlay_path: str = None):
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
    filter_complex = f"[1:v]scale={overlay_w}:-1[map];[0:v][map]overlay=main_w-overlay_w-10:main_h-overlay_h-10"

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
