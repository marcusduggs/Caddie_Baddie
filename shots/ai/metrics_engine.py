"""
Swing metrics extraction from MediaPipe pose landmarks.

Extended to include advanced biomechanical metrics:
    hip_rotation, shoulder_rotation, x_factor, head_movement,
    balance_score, sway, spine_angle, wrist_lag, hand_path_consistency,
    wrist_path, tempo_ratio, transition_timing, follow_through_completion,
    rotational_sequencing, frame_count

All landmark indices follow the MediaPipe Pose convention:
    0  = nose (head proxy)
    11 = left shoulder,  12 = right shoulder
    13 = left elbow,     14 = right elbow
    15 = left wrist,     16 = right wrist
    23 = left hip,       24 = right hip
    27 = left ankle,     28 = right ankle
"""

from __future__ import annotations

import logging
import math
import os
import statistics
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

import urllib.request

_POSE_MODEL_URL = (
    'https://storage.googleapis.com/mediapipe-models/pose_landmarker/'
    'pose_landmarker_lite/float16/latest/pose_landmarker_lite.task'
)
_POSE_MODEL_PATH = '/tmp/pose_landmarker_lite.task'

try:
    import cv2
except Exception as e:
    print(f'metrics_engine: cv2 import failed: {e}', flush=True)
    cv2 = None

try:
    from mediapipe.tasks import python as _mp_tasks_python
    from mediapipe.tasks.python import vision as _mp_tasks_vision
    from mediapipe import Image as _MpImage, ImageFormat as _MpImageFormat
    _mediapipe_available = True
except Exception as e:
    print(f'metrics_engine: mediapipe import failed: {e}', flush=True)
    _mediapipe_available = False
    _mp_tasks_python = None
    _mp_tasks_vision = None
    _MpImage = None
    _MpImageFormat = None


def _ensure_pose_model() -> Optional[str]:
    """Download the pose landmarker model file if not already cached."""
    if os.path.exists(_POSE_MODEL_PATH):
        return _POSE_MODEL_PATH
    try:
        print(f'metrics_engine: downloading pose model...', flush=True)
        urllib.request.urlretrieve(_POSE_MODEL_URL, _POSE_MODEL_PATH)
        print(f'metrics_engine: pose model ready', flush=True)
        return _POSE_MODEL_PATH
    except Exception as e:
        print(f'metrics_engine: pose model download failed: {e}', flush=True)
        return None


# ---------------------------------------------------------------------------
# Low-level geometry helpers
# ---------------------------------------------------------------------------

def _vec2(a: Dict, b: Dict) -> Tuple[float, float]:
    """2-D vector from landmark a to b."""
    return b["x"] - a["x"], b["y"] - a["y"]


def _angle_deg(v1: Tuple[float, float], v2: Tuple[float, float]) -> float:
    """Unsigned angle in degrees between two 2-D vectors."""
    dot = v1[0] * v2[0] + v1[1] * v2[1]
    mag = math.hypot(*v1) * math.hypot(*v2) + 1e-9
    return math.degrees(math.acos(max(-1.0, min(1.0, dot / mag))))


def _angle_3pt(a: Dict, b: Dict, c: Dict) -> float:
    """Angle at vertex b formed by points a-b-c, in degrees."""
    v1 = (a["x"] - b["x"], a["y"] - b["y"])
    v2 = (c["x"] - b["x"], c["y"] - b["y"])
    return _angle_deg(v1, v2)


def _dist2(a: Dict, b: Dict) -> float:
    """Euclidean distance between two landmarks in normalised coords."""
    return math.hypot(a["x"] - b["x"], a["y"] - b["y"])


def _midpoint(a: Dict, b: Dict) -> Dict:
    return {"x": (a["x"] + b["x"]) / 2.0, "y": (a["y"] + b["y"]) / 2.0}


def _visibility_ok(lm: Dict, threshold: float = 0.4) -> bool:
    return lm.get("visibility", 1.0) >= threshold


def _smooth_series(values: List[Optional[float]], window: int = 3) -> List[Optional[float]]:
    """Apply a simple moving-average to a list with possible None entries."""
    out: List[Optional[float]] = []
    for i, v in enumerate(values):
        if v is None:
            out.append(None)
            continue
        neighbours = [values[j] for j in range(max(0, i - window), min(len(values), i + window + 1))
                      if values[j] is not None]
        out.append(sum(neighbours) / len(neighbours) if neighbours else v)
    return out


# ---------------------------------------------------------------------------
# Per-frame landmark extraction
# ---------------------------------------------------------------------------

def _extract_landmark_frames(video_path: str) -> List[List[Dict]]:
    """Run MediaPipe Pose on video_path and return one landmark list per frame.

    Each list contains 33 dicts with keys x, y, z, visibility (all floats).
    Frames where pose detection fails are excluded.
    Returns [] if mediapipe/opencv are unavailable.
    """
    if not _mediapipe_available or cv2 is None:
        logger.warning("metrics_engine: mediapipe or opencv not available")
        return []

    model_path = _ensure_pose_model()
    if model_path is None:
        logger.warning("metrics_engine: pose model unavailable")
        return []

    if not os.path.exists(video_path):
        logger.error("metrics_engine: video not found: %s", video_path)
        return []

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        logger.error("metrics_engine: cannot open video: %s", video_path)
        return []

    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    FRAME_STEP = 2
    MAX_WIDTH = 640  # resize before MediaPipe — pose detection doesn't need full resolution
    all_frames: List[List[Dict]] = []
    last_lms: Optional[List[Dict]] = None
    frame_idx = 0

    from .gl_utils import ensure_gl_stubs
    ensure_gl_stubs()

    base_options = _mp_tasks_python.BaseOptions(
        model_asset_path=model_path,
        delegate=_mp_tasks_python.BaseOptions.Delegate.CPU,
    )
    options = _mp_tasks_vision.PoseLandmarkerOptions(
        base_options=base_options,
        running_mode=_mp_tasks_vision.RunningMode.VIDEO,
        num_poses=1,
        min_pose_detection_confidence=0.45,
        min_pose_presence_confidence=0.45,
        min_tracking_confidence=0.45,
    )
    try:
        landmarker = _mp_tasks_vision.PoseLandmarker.create_from_options(options)
    except OSError as exc:
        cap.release()
        print(f'metrics_engine: mediapipe C library failed to load ({exc}); pose extraction disabled', flush=True)
        return []

    try:
        while True:
            ret, frame = cap.read()
            if not ret:
                break
            if frame_idx % FRAME_STEP == 0:
                h, w = frame.shape[:2]
                if w > MAX_WIDTH:
                    frame = cv2.resize(frame, (MAX_WIDTH, int(h * MAX_WIDTH / w)), interpolation=cv2.INTER_AREA)
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                mp_image = _MpImage(image_format=_MpImageFormat.SRGB, data=rgb)
                timestamp_ms = int(frame_idx * 1000.0 / fps)
                result = landmarker.detect_for_video(mp_image, timestamp_ms)
                if result.pose_landmarks:
                    last_lms = [
                        {
                            "x": lm.x,
                            "y": lm.y,
                            "z": lm.z,
                            "visibility": getattr(lm, "visibility", 1.0),
                        }
                        for lm in result.pose_landmarks[0]
                    ]
            if last_lms is not None:
                all_frames.append(last_lms)
            frame_idx += 1
    finally:
        cap.release()
        try:
            landmarker.close()
        except Exception:
            pass

    logger.debug("metrics_engine: extracted landmarks from %d frames", len(all_frames))
    return all_frames


def _get_fps(video_path: str) -> float:
    """Return the frame rate of the video, defaulting to 30."""
    if cv2 is None:
        return 30.0
    cap = cv2.VideoCapture(video_path)
    fps = cap.get(cv2.CAP_PROP_FPS) if cap.isOpened() else 30.0
    cap.release()
    return fps or 30.0


# ---------------------------------------------------------------------------
# Wrist speed helper (shared by tempo, follow-through, transition)
# ---------------------------------------------------------------------------

def _wrist_speed_series(frames: List[List[Dict]]) -> List[float]:
    """Per-frame right-wrist speed in normalised coords/frame."""
    speeds: List[float] = []
    prev = None
    for lms in frames:
        rw = lms[16]
        if _visibility_ok(rw, 0.3):
            curr = (rw["x"], rw["y"])
            speeds.append(math.hypot(curr[0] - prev[0], curr[1] - prev[1]) if prev else 0.0)
            prev = curr
        else:
            speeds.append(0.0)
    return speeds


def _find_impact_idx(speeds: List[float]) -> int:
    """Frame index of peak wrist speed (proxy for impact)."""
    return speeds.index(max(speeds)) if speeds and max(speeds) > 1e-6 else len(speeds) // 2


# ---------------------------------------------------------------------------
# Individual metric calculators
# ---------------------------------------------------------------------------

def _hip_rotation(frames: List[List[Dict]]) -> Optional[float]:
    """Maximum hip rotation angle (degrees) relative to the address frame."""
    angles = []
    for lms in frames:
        lh, rh = lms[23], lms[24]
        if _visibility_ok(lh) and _visibility_ok(rh):
            angles.append(_angle_deg(_vec2(lh, rh), (1.0, 0.0)))
    if len(angles) < 2:
        return None
    baseline = angles[0]
    return round(max(abs(a - baseline) for a in angles), 1)


def _shoulder_rotation(frames: List[List[Dict]]) -> Optional[float]:
    """Maximum shoulder rotation angle relative to the address frame."""
    angles = []
    for lms in frames:
        ls, rs = lms[11], lms[12]
        if _visibility_ok(ls) and _visibility_ok(rs):
            angles.append(_angle_deg(_vec2(ls, rs), (1.0, 0.0)))
    if len(angles) < 2:
        return None
    baseline = angles[0]
    return round(max(abs(a - baseline) for a in angles), 1)


def _x_factor(hip_rot: Optional[float], shoulder_rot: Optional[float]) -> Optional[float]:
    """X-factor: maximum differential between shoulder and hip rotation.

    The PGA Tour average X-factor at the top of backswing is ~40-50 degrees.
    A higher X-factor correlates with greater power potential.
    """
    if hip_rot is None or shoulder_rot is None:
        return None
    return round(max(0.0, shoulder_rot - hip_rot), 1)


def _spine_angle(frames: List[List[Dict]]) -> Optional[float]:
    """Mean forward tilt of the torso (degrees from vertical).

    Measured as the angle of the hip-to-shoulder vector from vertical.
    A good address spine angle for irons is roughly 25-40 degrees.
    """
    angles = []
    for lms in frames:
        ls, rs, lh, rh = lms[11], lms[12], lms[23], lms[24]
        if not all(_visibility_ok(l) for l in [ls, rs, lh, rh]):
            continue
        shoulder_mid = _midpoint(ls, rs)
        hip_mid = _midpoint(lh, rh)
        spine_vec = _vec2(hip_mid, shoulder_mid)
        # y-axis points down in image coords so vertical is (0, -1)
        angles.append(_angle_deg(spine_vec, (0.0, -1.0)))
    if len(angles) < 3:
        return None
    # Use early-frame average as representative of setup spine angle
    sample = angles[:max(1, len(angles) // 4)]
    return round(statistics.mean(sample), 1)


def _head_movement(frames: List[List[Dict]]) -> Optional[float]:
    """Total normalised displacement of the nose landmark (×100).

    Lower = steadier head. Excellent < 10, acceptable 10-20, poor > 20.
    """
    positions = [(lms[0]["x"], lms[0]["y"]) for lms in frames if _visibility_ok(lms[0], 0.3)]
    if len(positions) < 2:
        return None
    total = sum(
        math.hypot(positions[i][0] - positions[i - 1][0], positions[i][1] - positions[i - 1][1])
        for i in range(1, len(positions))
    )
    return round(total * 100, 1)


def _sway(frames: List[List[Dict]]) -> Optional[float]:
    """Maximum lateral (x-axis) displacement of hip centre from address (×100).

    Captures body sway independent of overall balance stability. Values above
    5 indicate meaningful lateral movement; above 10 suggests excess sway.
    """
    hip_x = []
    for lms in frames:
        lh, rh = lms[23], lms[24]
        if _visibility_ok(lh) and _visibility_ok(rh):
            hip_x.append((lh["x"] + rh["x"]) / 2.0)
    if len(hip_x) < 3:
        return None
    address_x = hip_x[0]
    return round(max(abs(x - address_x) for x in hip_x) * 100, 1)


def _balance_score(frames: List[List[Dict]]) -> Optional[int]:
    """Score 0-100 for lateral hip stability throughout the swing.

    Computed as 100 minus a scaled standard deviation of the hip-midpoint
    x-coordinate. Lower hip sway yields a higher score.
    """
    hip_x = []
    for lms in frames:
        lh, rh = lms[23], lms[24]
        if _visibility_ok(lh) and _visibility_ok(rh):
            hip_x.append((lh["x"] + rh["x"]) / 2.0)
    if len(hip_x) < 3:
        return None
    stdev = statistics.stdev(hip_x)
    return max(0, min(100, int(100 - (stdev / 0.12) * 100)))


def _wrist_lag(frames: List[List[Dict]]) -> Optional[float]:
    """Peak angle at the right elbow joint during the swing (degrees).

    Approximates wrist/club lag. Higher angles (> 90°) indicate maintained
    lag; collapse to < 70° suggests early release.
    """
    angles = []
    for lms in frames:
        rs, re, rw = lms[12], lms[14], lms[16]
        if all(_visibility_ok(l, 0.35) for l in [rs, re, rw]):
            angles.append(_angle_3pt(rs, re, rw))
    if len(angles) < 3:
        return None
    return round(max(angles), 1)


def _hand_path_consistency(frames: List[List[Dict]]) -> Optional[int]:
    """Score 0-100 for right-wrist path consistency throughout the swing.

    Based on the combined standard deviation of x and y coordinates.
    Higher = more repeatable hand path.
    """
    x_vals = [lms[16]["x"] for lms in frames if _visibility_ok(lms[16], 0.3)]
    y_vals = [lms[16]["y"] for lms in frames if _visibility_ok(lms[16], 0.3)]
    if len(x_vals) < 5:
        return None
    combined = math.hypot(statistics.stdev(x_vals), statistics.stdev(y_vals))
    # Empirical range: 0.08 combined stdev = highly variable path
    return max(0, min(100, int(100 - (combined / 0.08) * 100)))


def _wrist_path(frames: List[List[Dict]]) -> Optional[float]:
    """Total arc length (×100) traced by the right wrist — approximates club path."""
    positions = [(lms[16]["x"], lms[16]["y"]) for lms in frames if _visibility_ok(lms[16], 0.3)]
    if len(positions) < 2:
        return None
    total = sum(
        math.hypot(positions[i][0] - positions[i - 1][0], positions[i][1] - positions[i - 1][1])
        for i in range(1, len(positions))
    )
    return round(total * 100, 1)


def _tempo_ratio(frames: List[List[Dict]], fps: float = 30.0) -> Optional[float]:
    """Backswing-to-downswing frame ratio.

    PGA Tour benchmark ≈ 3:1. Detection uses peak wrist speed as impact proxy.
    """
    if len(frames) < 10:
        return None
    speeds = _wrist_speed_series(frames)
    if not speeds or max(speeds) < 1e-6:
        return None

    peak_val = max(speeds)
    impact_idx = _find_impact_idx(speeds)
    quiet_thresh = peak_val * 0.15

    address_idx = next((i for i in range(impact_idx - 1, -1, -1) if speeds[i] <= quiet_thresh), 0)
    finish_idx = next((i for i in range(impact_idx + 1, len(speeds)) if speeds[i] <= quiet_thresh),
                      len(speeds) - 1)

    backswing = impact_idx - address_idx
    downswing = finish_idx - impact_idx
    if downswing < 1:
        return None
    return round(backswing / downswing, 2)


def _transition_timing(frames: List[List[Dict]]) -> Optional[float]:
    """Normalised position of the swing transition (0.0–1.0).

    Computed as the frame of peak wrist speed divided by total frames.
    Lower values (< 0.5) indicate an early, aggressive transition.
    PGA Tour average is roughly 0.50–0.65.
    """
    if len(frames) < 10:
        return None
    speeds = _wrist_speed_series(frames)
    if not speeds or max(speeds) < 1e-6:
        return None
    impact_idx = _find_impact_idx(speeds)
    return round(impact_idx / len(speeds), 2)


def _follow_through_completion(frames: List[List[Dict]]) -> Optional[float]:
    """Post-impact wrist path as a percentage of total wrist path.

    Good follow-through is generally > 40%. Values below 30% suggest the
    player is decelerating through impact.
    """
    if len(frames) < 10:
        return None
    speeds = _wrist_speed_series(frames)
    if not speeds or max(speeds) < 1e-6:
        return None
    impact_idx = _find_impact_idx(speeds)

    positions = [(lms[16]["x"], lms[16]["y"]) for lms in frames if _visibility_ok(lms[16], 0.3)]
    if len(positions) < 5:
        return None

    # Clamp impact_idx to valid range for the filtered position list
    split = min(impact_idx, len(positions) - 1)

    def path_len(pts: List) -> float:
        return sum(
            math.hypot(pts[i][0] - pts[i - 1][0], pts[i][1] - pts[i - 1][1])
            for i in range(1, len(pts))
        )

    pre = path_len(positions[:split + 1])
    post = path_len(positions[split:])
    total = pre + post
    if total < 1e-9:
        return None
    return round((post / total) * 100, 1)


def _rotational_sequencing(frames: List[List[Dict]]) -> Optional[int]:
    """Sequencing score 0-100 based on whether hips lead shoulders in the downswing.

    Good sequencing (hips initiate the downswing before shoulders) scores 70+.
    A reversed sequence (shoulders lead) scores below 50.
    """
    hip_angles: List[Optional[float]] = []
    shoulder_angles: List[Optional[float]] = []

    for lms in frames:
        lh, rh = lms[23], lms[24]
        ls, rs = lms[11], lms[12]
        hip_angles.append(
            _angle_deg(_vec2(lh, rh), (1.0, 0.0))
            if _visibility_ok(lh) and _visibility_ok(rh) else None
        )
        shoulder_angles.append(
            _angle_deg(_vec2(ls, rs), (1.0, 0.0))
            if _visibility_ok(ls) and _visibility_ok(rs) else None
        )

    valid_hips = [(i, a) for i, a in enumerate(hip_angles) if a is not None]
    valid_shoulders = [(i, a) for i, a in enumerate(shoulder_angles) if a is not None]

    if len(valid_hips) < 6 or len(valid_shoulders) < 6:
        return None

    hip_vals = [a for _, a in valid_hips]
    shoulder_vals = [a for _, a in valid_shoulders]

    peak_hip_global = valid_hips[hip_vals.index(max(hip_vals))][0]
    peak_shoulder_global = valid_shoulders[shoulder_vals.index(max(shoulder_vals))][0]

    # Positive frame_diff means hips peaked first — good sequencing
    frame_diff = peak_shoulder_global - peak_hip_global
    if frame_diff >= 5:
        return min(100, 70 + frame_diff * 3)
    elif frame_diff >= 2:
        return 65
    elif frame_diff >= 0:
        return 50
    else:
        return max(0, 50 + frame_diff * 8)


# ---------------------------------------------------------------------------
# Shot shape estimator
# ---------------------------------------------------------------------------

def _estimate_shot_shape(metrics: Dict) -> str:
    """Estimate shot shape from biomechanical indicators.

    Returns one of: 'slice', 'fade', 'straight', 'draw', 'hook', 'push', 'pull'.
    This is a biomechanical estimate — not ball-tracking data.
    """
    shoulder_rot = metrics.get("shoulder_rotation")
    hip_rot = metrics.get("hip_rotation")
    x_factor = metrics.get("x_factor")
    wrist_path = metrics.get("wrist_path")
    follow_through = metrics.get("follow_through_completion")
    sequencing = metrics.get("rotational_sequencing")

    if shoulder_rot is None or hip_rot is None:
        return "unknown"

    # Over-the-top path (high shoulder/wrist path ratio with poor sequencing)
    if wrist_path is not None and shoulder_rot > 0:
        path_ratio = wrist_path / max(shoulder_rot, 1.0)
        if path_ratio > 2.8 and (sequencing is None or sequencing < 50):
            return "slice"
        if path_ratio > 2.2:
            return "fade"

    # Poor x_factor often leads to a push or blocked shot
    if x_factor is not None and x_factor < 8:
        return "push"

    # Strong hip lead with good follow-through indicates draw tendency
    if sequencing is not None and sequencing >= 70:
        if follow_through is not None and follow_through > 45:
            return "draw"

    # Very high hip rotation with high sequencing can indicate hook
    if hip_rot is not None and hip_rot > 55 and sequencing is not None and sequencing >= 80:
        return "hook"

    return "straight"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def extract_swing_metrics(video_path: str) -> Dict:
    """Extract comprehensive swing metrics from a golf swing video.

    Runs MediaPipe Pose on the video and computes a full suite of biomechanical
    metrics. Returns a dict even if some metrics could not be computed (those
    values will be None).

    Returns:
        Dict with keys: hip_rotation, shoulder_rotation, x_factor, spine_angle,
        head_movement, sway, balance_score, wrist_lag, hand_path_consistency,
        wrist_path, tempo_ratio, transition_timing, follow_through_completion,
        rotational_sequencing, shot_shape, frame_count.
    """
    logger.info("metrics_engine: starting extraction for %s", video_path)
    frames = _extract_landmark_frames(video_path)
    fps = _get_fps(video_path)

    empty: Dict = {
        "hip_rotation": None, "shoulder_rotation": None, "x_factor": None,
        "spine_angle": None, "head_movement": None, "sway": None,
        "balance_score": None, "wrist_lag": None, "hand_path_consistency": None,
        "wrist_path": None, "tempo_ratio": None, "transition_timing": None,
        "follow_through_completion": None, "rotational_sequencing": None,
        "shot_shape": "unknown", "frame_count": 0,
    }

    if not frames:
        logger.warning("metrics_engine: no pose landmarks found")
        return empty

    hip_rot = _hip_rotation(frames)
    shoulder_rot = _shoulder_rotation(frames)

    metrics: Dict = {
        "hip_rotation": hip_rot,
        "shoulder_rotation": shoulder_rot,
        "x_factor": _x_factor(hip_rot, shoulder_rot),
        "spine_angle": _spine_angle(frames),
        "head_movement": _head_movement(frames),
        "sway": _sway(frames),
        "balance_score": _balance_score(frames),
        "wrist_lag": _wrist_lag(frames),
        "hand_path_consistency": _hand_path_consistency(frames),
        "wrist_path": _wrist_path(frames),
        "tempo_ratio": _tempo_ratio(frames, fps),
        "transition_timing": _transition_timing(frames),
        "follow_through_completion": _follow_through_completion(frames),
        "rotational_sequencing": _rotational_sequencing(frames),
        "frame_count": len(frames),
    }

    # Shot shape requires full metrics dict
    metrics["shot_shape"] = _estimate_shot_shape(metrics)

    logger.info("metrics_engine: extracted %d metrics from %d frames", len(metrics), len(frames))
    return metrics
