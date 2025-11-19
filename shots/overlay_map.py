import os
import shutil
import subprocess
import uuid
from pathlib import Path
from django.conf import settings

def _probe_width(path):
    cmd = ["ffprobe", "-v", "error", "-select_streams", "v:0",
           "-show_entries", "stream=width", "-of", "csv=p=0", path]
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if p.returncode != 0:
        return None
    try:
        return int(p.stdout.strip())
    except Exception:
        return None

def process_video_with_overlay(input_path: str, output_path: str, overlay_path: str = "/Users/marcusduggs/Desktop/test_map.png"):
    """
    Overlay overlay_path onto input_path (bottom-right, 10px margin).
    Writes output_path (mp4). Raises RuntimeError on failure.
    """
    if not os.path.isfile(input_path):
        raise FileNotFoundError(f"Input not found: {input_path}")

    if not os.path.isfile(overlay_path):
        raise FileNotFoundError(f"Overlay image not found: {overlay_path}")

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    logs_dir = Path(settings.MEDIA_ROOT) / "logs"
    logs_dir.mkdir(exist_ok=True, parents=True)
    log_file = logs_dir / f"overlay_{uuid.uuid4().hex[:8]}.log"

    # probe width and choose overlay width (20% by default)
    vwidth = _probe_width(input_path) or 1280
    overlay_w = max(64, int(vwidth * 0.20))

    # filter: scale overlay, keep aspect, then overlay bottom-right with 10px margin
    filter_complex = f"[1:v]scale={overlay_w}:-1[map];[0:v][map]overlay=main_w-overlay_w-10:main_h-overlay_h-10"

    cmd = [
        "ffmpeg", "-y",
        "-i", input_path,
        "-i", overlay_path,
        "-filter_complex", filter_complex,
        "-map", "0:a?",   # copy audio if present
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "128k",
        "-movflags", "+faststart",
        output_path
    ]

    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    # write ffmpeg stderr to log for debugging
    with open(log_file, "w") as fh:
        fh.write("CMD: " + " ".join(cmd) + "\n\n")
        fh.write(proc.stdout or "")
        fh.write(proc.stderr or "")

    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg failed (log: {log_file}): {proc.stderr[:2000]}")

    try:
        os.chmod(output_path, 0o644)
    except Exception:
        pass

    return str(output_path)