import os
import tempfile
import os
import tempfile
import math
import subprocess
import shutil
from typing import Dict, List, Optional, Tuple

import urllib.request

_POSE_MODEL_URL = (
    'https://storage.googleapis.com/mediapipe-models/pose_landmarker/'
    'pose_landmarker_lite/float16/latest/pose_landmarker_lite.task'
)
_POSE_MODEL_PATH = '/tmp/pose_landmarker_lite.task'

try:
    import cv2
except Exception:
    cv2 = None

try:
    from mediapipe.tasks import python as _mp_tasks_python
    from mediapipe.tasks.python import vision as _mp_tasks_vision
    from mediapipe import Image as _MpImage, ImageFormat as _MpImageFormat
    _mediapipe_available = True
except Exception:
    _mediapipe_available = False
    _mp_tasks_python = None
    _mp_tasks_vision = None
    _MpImage = None
    _MpImageFormat = None


def _ensure_pose_model():
    if os.path.exists(_POSE_MODEL_PATH):
        return _POSE_MODEL_PATH
    try:
        urllib.request.urlretrieve(_POSE_MODEL_URL, _POSE_MODEL_PATH)
        return _POSE_MODEL_PATH
    except Exception:
        return None


def _angle_between(a: Tuple[float, float], b: Tuple[float, float]) -> float:
    """Return angle (radians) between vectors a and b."""
    ax, ay = a
    bx, by = b
    dot = ax * bx + ay * by
    mag = math.hypot(ax, ay) * math.hypot(bx, by) + 1e-9
    val = max(-1.0, min(1.0, dot / mag))
    return math.acos(val)


def render_pose_wireframe(input_path: str,
                          output_path: Optional[str] = None,
                          smoothing: float = 0.7,
                          wrist_trail_len: int = 8,
                          detection_confidence: float = 0.5,
                          tracking_confidence: float = 0.5) -> str:
    """Run MediaPipe Pose on input_path and write an output video with a skeleton overlay.

    The overlay is drawn semi-transparently on top of each frame. The function returns
    the absolute path to the written output file.

    Parameters:
    - input_path: path to the input video file
    - output_path: optional path where to write the processed video (if None a temp file is used)
    - smoothing: 0..1 smoothing factor for landmark EMA (higher = more smoothing)
    - wrist_trail_len: number of frames to keep for estimating club path from wrist positions
    - detection_confidence / tracking_confidence: MediaPipe thresholds

    Returns:
    - output_path (str)

    Raises RuntimeError if mediapipe/opencv are not installed or video cannot be opened.
    """
    if not _mediapipe_available or cv2 is None:
        raise RuntimeError('mediapipe and opencv-python are required for pose overlay')

    if not os.path.exists(input_path):
        raise FileNotFoundError(f'Input video not found: {input_path}')

    if output_path is None:
        fd, output_path = tempfile.mkstemp(suffix='.mp4')
        os.close(fd)

    cap = cv2.VideoCapture(input_path)
    if not cap.isOpened():
        raise RuntimeError(f'Unable to open video {input_path}')

    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    # Attempt to create a VideoWriter. Some platforms/codecs may not be available;
    # try a short list of fallbacks. If none work, fall back to writing frames to a
    # temporary directory and using ffmpeg to encode the final MP4. This avoids
    # empty output files on platforms where OpenCV is built without MP4 codecs
    # (common on macOS pip wheels).
    tried_codecs = ['mp4v', 'avc1', 'H264', 'XVID']
    out = None
    for code in tried_codecs:
        try:
            fourcc = cv2.VideoWriter_fourcc(*code)
            out = cv2.VideoWriter(output_path, fourcc, fps, (w, h))
            if out is not None and out.isOpened():
                break
            else:
                out = None
        except Exception:
            out = None

    use_ffmpeg_seq = False
    tmp_dir = None
    frame_seq_paths = []
    if out is None or not out.isOpened():
        # Fall back to FFmpeg image sequence encoding
        ffmpeg_path = shutil.which('ffmpeg')
        if not ffmpeg_path:
            # Try to import project's ffmpeg resolver if available
            try:
                from utils.overlay import FFMPEG_PATH as ffmpeg_path
            except Exception:
                ffmpeg_path = None
        if not ffmpeg_path:
            raise RuntimeError(f'Failed to open cv2.VideoWriter with codecs={tried_codecs} and ffmpeg not found; check your OpenCV build or install ffmpeg')
        use_ffmpeg_seq = True
        tmp_dir = tempfile.mkdtemp(prefix='pose_frames_')

    model_path = _ensure_pose_model()
    if model_path is None:
        raise RuntimeError('Pose landmarker model could not be downloaded')

    base_options = _mp_tasks_python.BaseOptions(model_asset_path=model_path)
    options = _mp_tasks_vision.PoseLandmarkerOptions(
        base_options=base_options,
        running_mode=_mp_tasks_vision.RunningMode.VIDEO,
        num_poses=1,
        min_pose_detection_confidence=detection_confidence,
        min_pose_presence_confidence=detection_confidence,
        min_tracking_confidence=tracking_confidence,
    )
    landmarker = _mp_tasks_vision.PoseLandmarker.create_from_options(options)

    # state for smoothing and trails
    smoothed_landmarks: Optional[List[Dict[str, float]]] = None
    wrist_history: List[Dict[str, Tuple[float, float]]] = []
    frame_index = 0
    wrist_speeds: List[float] = []

    try:
     while True:
        ret, frame = cap.read()
        if not ret:
            break
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        mp_image = _MpImage(image_format=_MpImageFormat.SRGB, data=rgb)
        timestamp_ms = int(frame_index * 1000.0 / fps)
        results = landmarker.detect_for_video(mp_image, timestamp_ms)

        overlay = frame.copy()

        landmarks = None
        if results.pose_landmarks:
                raw = []
                for lm in results.pose_landmarks[0]:
                    raw.append({'x': lm.x, 'y': lm.y, 'z': lm.z, 'visibility': getattr(lm, 'visibility', 1.0)})

                # initialize or smooth landmarks with simple EMA
                if smoothed_landmarks is None:
                    smoothed_landmarks = raw.copy()
                else:
                    a = smoothing
                    for i in range(len(raw)):
                        smoothed_landmarks[i]['x'] = a * smoothed_landmarks[i]['x'] + (1 - a) * raw[i]['x']
                        smoothed_landmarks[i]['y'] = a * smoothed_landmarks[i]['y'] + (1 - a) * raw[i]['y']
                        smoothed_landmarks[i]['z'] = a * smoothed_landmarks[i]['z'] + (1 - a) * raw[i]['z']
                        smoothed_landmarks[i]['visibility'] = a * smoothed_landmarks[i].get('visibility', 1.0) + (1 - a) * raw[i].get('visibility', 1.0)
                landmarks = smoothed_landmarks

                # pixel coords helper
                def pix(i):
                    lm = landmarks[i]
                    return int(lm['x'] * w), int(lm['y'] * h)

                # compute shoulder and hip rotation angles (degrees)
                try:
                    ls = landmarks[11]; rs = landmarks[12]
                    lh = landmarks[23]; rh = landmarks[24]
                    shoulder_vec = (rs['x'] - ls['x'], rs['y'] - ls['y'])
                    hip_vec = (rh['x'] - lh['x'], rh['y'] - lh['y'])
                    shoulder_deg = math.degrees(_angle_between(shoulder_vec, (1.0, 0.0)))
                    hip_deg = math.degrees(_angle_between(hip_vec, (1.0, 0.0)))
                except Exception:
                    shoulder_deg = None
                    hip_deg = None

                # update wrist trail (approximate club path)
                try:
                    lw = pix(15)
                    rw = pix(16)
                    wrist_history.insert(0, {'left': lw, 'right': rw, 'frame': frame_index})
                    if len(wrist_history) > wrist_trail_len:
                        wrist_history = wrist_history[:wrist_trail_len]
                    # compute simple wrist speed (pixel displacement between frames)
                    if len(wrist_history) >= 2:
                        dx = wrist_history[0]['right'][0] - wrist_history[1]['right'][0]
                        dy = wrist_history[0]['right'][1] - wrist_history[1]['right'][1]
                        wrist_speeds.append(math.hypot(dx, dy))
                    else:
                        wrist_speeds.append(0.0)
                except Exception:
                    pass

                # --- Drawing on overlay (semi-transparent) ---
                # Use color scheme and thickness tuned for visibility over golf video
                # connections: emphasize shoulders and hips, arms, legs
                def draw_segment(i, j, color=(0, 160, 255), thickness=2):
                    try:
                        a = pix(i); b = pix(j)
                        cv2.line(overlay, a, b, color, thickness, lineType=cv2.LINE_AA)
                    except Exception:
                        pass

                # arms
                draw_segment(11, 13, (200, 80, 80), 3)
                draw_segment(13, 15, (200, 80, 80), 3)
                draw_segment(12, 14, (200, 80, 80), 3)
                draw_segment(14, 16, (200, 80, 80), 3)
                # shoulders and torso
                draw_segment(11, 12, (0, 140, 255), 5)
                draw_segment(11, 23, (0, 200, 200), 3)
                draw_segment(12, 24, (0, 200, 200), 3)
                draw_segment(23, 24, (180, 200, 255), 5)
                # legs
                draw_segment(23, 25, (120, 200, 255), 3)
                draw_segment(25, 27, (120, 200, 255), 3)
                draw_segment(24, 26, (120, 200, 255), 3)
                draw_segment(26, 28, (120, 200, 255), 3)

                # draw joints
                key_joints = [11,12,13,14,15,16,23,24,25,26]
                for idx in key_joints:
                    try:
                        x, y = pix(idx)
                        cv2.circle(overlay, (x, y), 4, (255,255,255), -1, lineType=cv2.LINE_AA)
                    except Exception:
                        pass

                # Shoulder/hip angles are computed above but we intentionally
                # do not render their numeric labels into the video overlay.
                # This keeps the wireframe clean while preserving angle values
                # in memory (swing_info) if callers need them.

                # draw wrist trails (club path approximation)
                for i in range(1, len(wrist_history)):
                    alpha = 1.0 - (i / max(1, wrist_trail_len))
                    col = (int(255 * alpha), int(220 * alpha), int(50 * alpha))
                    pt_prev = wrist_history[i-1].get('right')
                    pt = wrist_history[i].get('right')
                    if pt_prev and pt:
                        cv2.line(overlay, pt_prev, pt, col, int(2 + 2*alpha), lineType=cv2.LINE_AA)

        # Blend overlay onto frame with alpha transparency so underlying video remains visible
        try:
            alpha = 0.7  # overlay opacity
            cv2.addWeighted(overlay, alpha, frame, 1 - alpha, 0, frame)
        except Exception:
            frame = overlay

        if use_ffmpeg_seq:
            frame_file = os.path.join(tmp_dir, f'frame_{frame_index:06d}.png')
            cv2.imwrite(frame_file, frame)
            frame_seq_paths.append(frame_file)
        else:
            out.write(frame)
        frame_index += 1

    finally:
        try:
            landmarker.close()
        except Exception:
            pass

    cap.release()
    if not use_ffmpeg_seq:
        out.release()
    else:
        # run ffmpeg to assemble the image sequence into MP4
        try:
            # -y overwrite, -framerate fps, input pattern
            cmd = [ffmpeg_path, '-y', '-framerate', str(int(round(fps))), '-i', os.path.join(tmp_dir, 'frame_%06d.png'), '-c:v', 'libx264', '-pix_fmt', 'yuv420p', output_path]
            proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            if proc.returncode != 0:
                raise RuntimeError(f'ffmpeg failed: {proc.stderr.decode("utf-8", errors="ignore")}')
        finally:
            # cleanup frame files and temp dir
            try:
                for p in frame_seq_paths:
                    if os.path.exists(p):
                        os.remove(p)
                os.rmdir(tmp_dir)
            except Exception:
                pass

    # post-processing: determine swing phases from wrist_speeds (very simple heuristic)
    swing_info = {}
    try:
        if wrist_speeds:
            # impact = frame with maximum wrist speed
            impact_idx = int(max(range(len(wrist_speeds)), key=lambda i: wrist_speeds[i]))
            swing_info['impact_frame'] = impact_idx
            # address: first frame where speed is small before impact
            before = wrist_speeds[:impact_idx+1] if impact_idx>0 else wrist_speeds
            thresh = (max(before) if before else 0) * 0.15
            addr = 0
            for i, v in enumerate(before):
                if v > thresh:
                    addr = max(0, i-10)
                    break
            swing_info['address_frame'] = addr
            swing_info['follow_through_start'] = impact_idx + 1
        else:
            swing_info = {}
    except Exception:
        swing_info = {}

    # For integration, callers may want swing_info (angles/frames). We return the path
    # and the swing_info could be returned or logged; keep signature simple and return path.
    return output_path
