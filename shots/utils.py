import subprocess
import json
import re
import tempfile
import os


def extract_coords_from_video(path: str):
    """Try to extract longitude,latitude from a video file using ffprobe metadata.

    Returns (lon, lat) or None.
    """
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

        for c in candidates:
            # ISO6709 style: +21.0172-086.8243-004.447/  (lat then lon)
            m = re.search(r'([+-]?\d+(?:\.\d+))([+-]?\d+(?:\.\d+))', c)
            if m:
                lat = float(m.group(1))
                lon = float(m.group(2))
                return lon, lat
    except Exception:
        return None
    return None


def save_uploaded_tempfile(uploaded_file):
    """Save Django UploadedFile to a temp path and return that path."""
    suffix = os.path.splitext(uploaded_file.name)[1] or '.bin'
    tf = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    for chunk in uploaded_file.chunks():
        tf.write(chunk)
    tf.flush()
    tf.close()
    return tf.name


def analyze_video(path: str, output_dir: str = None) -> dict:
    """Run a lightweight analysis on the video file.

    This is a thin integration point for your existing Hello-World logic.
    For now it:
      - extracts coordinates with ffprobe (if present)
      - returns a dict with keys: club, distance, accuracy, longitude, latitude, processed_path

    You can extend this function to call your real analyzer or external script.
    """
    # Placeholder/simple analysis: extract GPS if present and echo input path as processed
    coords = extract_coords_from_video(path)
    lon = lat = None
    if coords:
        lon, lat = coords

    # For processing, prefer to call the existing Hello-World analyzer script if present.
    processed_path = None
    hello_paths = [
        os.path.expanduser('~/Desktop/Hello-World.py'),
        os.path.join(os.getcwd(), 'Hello-World.py'),
    ]
    hello_script = None
    for hp in hello_paths:
        if os.path.exists(hp):
            hello_script = hp
            break

    if output_dir:
        os.makedirs(output_dir, exist_ok=True)
        base = os.path.basename(path)
        processed_path = os.path.join(output_dir, f"processed_{base}")
    else:
        processed_path = path

    if hello_script:
        # Build command to call Hello-World.py which overlays map image onto the video and writes output
        token = os.environ.get('MAPBOX_TOKEN')
        cmd = ['python3', hello_script, '--input', path, '--output', processed_path]
        if token:
            cmd += ['--mapbox-token', token]

        try:
            p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=300)
            stdout = p.stdout.decode('utf-8', errors='ignore') if p.stdout else ''
            if p.returncode != 0:
                # Fallback: copy original file if processing failed
                try:
                    import shutil
                    shutil.copy2(path, processed_path)
                except Exception:
                    processed_path = path
        except Exception:
            # On timeout or other errors, fallback to copying original
            try:
                import shutil
                shutil.copy2(path, processed_path)
            except Exception:
                processed_path = path
    else:
        # No Hello-World script found: copy original file as processed placeholder
        try:
            import shutil
            if processed_path and processed_path != path:
                shutil.copy2(path, processed_path)
        except Exception:
            processed_path = path

    # Return a result dict that will be saved into the model
    return {
        'club': None,
        'distance': None,
        'accuracy': None,
        'longitude': lon,
        'latitude': lat,
        'processed_path': processed_path,
        'raw': {
            'note': 'analyze_video used Hello-World.py if available; replace this function to call your full analyzer',
        }
    }

