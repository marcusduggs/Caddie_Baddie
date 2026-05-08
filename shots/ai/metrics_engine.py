"""
Swing metrics extraction from MediaPipe pose landmarks.

This module processes a golf swing video and returns a structured dictionary
of biomechanical metrics used as input to the AI coaching pipeline.

All landmark indices follow the MediaPipe Pose convention:
    11 = left shoulder,  12 = right shoulder
    23 = left hip,       24 = right hip
    15 = left wrist,     16 = right wrist
    0  = nose (head proxy)
    27 = left ankle,     28 = right ankle
"""

from __future__ import annotations

import logging
import math
import os
import statistics
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Avoid hard import failures if mediapipe / opencv are absent on this machine.
try:
    import cv2
except Exception:
    cv2 = None

try:
    import mediapipe as mp
except Exception:
    mp = None


# ---------------------------------------------------------------------------
# Low-level geometry helpers
# ---------------------------------------------------------------------------

def _vec2(a: Dict, b: Dict) -> Tuple[float, float]:
    """Return the 2-D vector from landmark dict a to b (x, y only)."""
    return b["x"] - a["x"], b["y"] - a["y"]


def _angle_deg(v1: Tuple[float, float], v2: Tuple[float, float]) -> float:
    """Return the unsigned angle in degrees between two 2-D vectors."""
    dot = v1[0] * v2[0] + v1[1] * v2[1]
    mag = math.hypot(*v1) * math.hypot(*v2) + 1e-9
    return math.degrees(math.acos(max(-1.0, min(1.0, dot / mag))))


def _dist2(a: Dict, b: Dict) -> float:
    """Euclidean distance between two landmarks in normalised coords."""
    return math.hypot(a["x"] - b["x"], a["y"] - b["y"])


def _midpoint(a: Dict, b: Dict) -> Dict:
    return {"x": (a["x"] + b["x"]) / 2.0, "y": (a["y"] + b["y"]) / 2.0}


def _visibility_ok(lm: Dict, threshold: float = 0.4) -> bool:
    return lm.get("visibility", 1.0) >= threshold


# ---------------------------------------------------------------------------
# Per-frame landmark extraction
# ---------------------------------------------------------------------------

def _extract_landmark_frames(video_path: str) -> List[List[Dict]]:
    """Run MediaPipe Pose on *video_path* and return one landmark list per frame.

    Each landmark list has 33 dicts with keys x, y, z, visibility (all floats).
    Frames where pose detection fails are excluded from the returned list.
    Returns an empty list if mediapipe/opencv are unavailable.
    """
    if mp is None or cv2 is None:
        logger.warning("metrics_engine: mediapipe or opencv not available; returning empty frames")
        return []

    if not os.path.exists(video_path):
        logger.error("metrics_engine: video not found: %s", video_path)
        return []

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        logger.error("metrics_engine: cannot open video: %s", video_path)
        return []

    mp_pose = mp.solutions.pose
    all_frames: List[List[Dict]] = []

    try:
        with mp_pose.Pose(
            static_image_mode=False,
            model_complexity=0,
            min_detection_confidence=0.45,
            min_tracking_confidence=0.45,
        ) as pose:
            while True:
                ret, frame = cap.read()
                if not ret:
                    break
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                results = pose.process(rgb)
                if getattr(results, "pose_landmarks", None):
                    lms = [
                        {
                            "x": lm.x,
                            "y": lm.y,
                            "z": lm.z,
                            "visibility": getattr(lm, "visibility", 1.0),
                        }
                        for lm in results.pose_landmarks.landmark
                    ]
                    all_frames.append(lms)
    finally:
        cap.release()

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
# Individual metric calculators
# ---------------------------------------------------------------------------

def _hip_rotation(frames: List[List[Dict]]) -> Optional[float]:
    """Maximum hip rotation angle (degrees) relative to the address frame."""
    angles = []
    for lms in frames:
        lh, rh = lms[23], lms[24]
        if not (_visibility_ok(lh) and _visibility_ok(rh)):
            continue
        v = _vec2(lh, rh)
        angles.append(_angle_deg(v, (1.0, 0.0)))
    if len(angles) < 2:
        return None
    baseline = angles[0]
    return round(max(abs(a - baseline) for a in angles), 1)


def _shoulder_rotation(frames: List[List[Dict]]) -> Optional[float]:
    """Maximum shoulder rotation angle relative to the address frame."""
    angles = []
    for lms in frames:
        ls, rs = lms[11], lms[12]
        if not (_visibility_ok(ls) and _visibility_ok(rs)):
            continue
        v = _vec2(ls, rs)
        angles.append(_angle_deg(v, (1.0, 0.0)))
    if len(angles) < 2:
        return None
    baseline = angles[0]
    return round(max(abs(a - baseline) for a in angles), 1)


def _head_movement(frames: List[List[Dict]]) -> Optional[float]:
    """Total normalised displacement of the nose landmark (× 100 for readability).

    A lower value means the head stayed steadier throughout the swing.
    """
    positions = []
    for lms in frames:
        nose = lms[0]
        if _visibility_ok(nose, 0.3):
            positions.append((nose["x"], nose["y"]))
    if len(positions) < 2:
        return None
    total = sum(
        math.hypot(positions[i][0] - positions[i - 1][0], positions[i][1] - positions[i - 1][1])
        for i in range(1, len(positions))
    )
    return round(total * 100, 1)


def _balance_score(frames: List[List[Dict]]) -> Optional[int]:
    """Score 0-100 representing centre-of-mass lateral stability.

    Computed as 100 minus a scaled standard deviation of the hip-midpoint
    x-coordinate. A lower hip sway yields a higher score.
    """
    hip_x = []
    for lms in frames:
        lh, rh = lms[23], lms[24]
        if _visibility_ok(lh) and _visibility_ok(rh):
            hip_x.append((lh["x"] + rh["x"]) / 2.0)
    if len(hip_x) < 3:
        return None
    stdev = statistics.stdev(hip_x)
    # Empirically, ±0.05 normalised coords is a typical range; cap at 0.12.
    score = max(0, min(100, int(100 - (stdev / 0.12) * 100)))
    return score


def _wrist_path(frames: List[List[Dict]]) -> Optional[float]:
    """Total arc length (× 100) traced by the right wrist — approximates club path."""
    positions = []
    for lms in frames:
        rw = lms[16]
        if _visibility_ok(rw, 0.3):
            positions.append((rw["x"], rw["y"]))
    if len(positions) < 2:
        return None
    total = sum(
        math.hypot(positions[i][0] - positions[i - 1][0], positions[i][1] - positions[i - 1][1])
        for i in range(1, len(positions))
    )
    return round(total * 100, 1)


def _wrist_speed_series(frames: List[List[Dict]]) -> List[float]:
    """Per-frame right-wrist speed in normalised coords/frame."""
    speeds = [0.0]
    prev = None
    for lms in frames:
        rw = lms[16]
        if _visibility_ok(rw, 0.3):
            curr = (rw["x"], rw["y"])
            if prev is not None:
                speeds.append(math.hypot(curr[0] - prev[0], curr[1] - prev[1]))
            else:
                speeds.append(0.0)
            prev = curr
        else:
            speeds.append(0.0)
    return speeds[1:] if len(speeds) > 1 else speeds


def _tempo_ratio(frames: List[List[Dict]], fps: float = 30.0) -> Optional[float]:
    """Backswing-to-downswing frame ratio (a PGA benchmark is ~3:1).

    Detection heuristic:
    - Impact = frame with peak wrist speed.
    - Address  = last "quiet" frame (speed < 15% of peak) before impact.
    - Finish   = first "quiet" frame after impact.
    Returns backswing_frames / downswing_frames, or None if indeterminate.
    """
    if len(frames) < 10:
        return None
    speeds = _wrist_speed_series(frames)
    if not speeds or max(speeds) < 1e-6:
        return None

    peak_val = max(speeds)
    impact_idx = speeds.index(peak_val)
    quiet_thresh = peak_val * 0.15

    # Find address: last quiet frame before impact
    address_idx = 0
    for i in range(impact_idx - 1, -1, -1):
        if speeds[i] <= quiet_thresh:
            address_idx = i
            break

    # Find finish: first quiet frame after impact
    finish_idx = len(speeds) - 1
    for i in range(impact_idx + 1, len(speeds)):
        if speeds[i] <= quiet_thresh:
            finish_idx = i
            break

    backswing = impact_idx - address_idx
    downswing = finish_idx - impact_idx
    if downswing < 1:
        return None
    return round(backswing / downswing, 2)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def extract_swing_metrics(video_path: str) -> Dict:
    """Extract structured swing metrics from a golf swing video.

    Runs MediaPipe Pose on the video and computes biomechanical metrics used
    by the AI coaching pipeline. Returns a dict even if some metrics could not
    be computed (values will be None in that case).

    Args:
        video_path: Absolute path to the video file (input or processed).

    Returns:
        Dict with keys:
            hip_rotation       – max hip-line angle change from address (degrees)
            shoulder_rotation  – max shoulder-line angle change (degrees)
            head_movement      – total nose path length (scaled ×100, lower = steadier)
            balance_score      – lateral stability score 0-100 (higher = better)
            wrist_path         – right-wrist arc length (scaled ×100)
            tempo_ratio        – backswing / downswing frame ratio
            frame_count        – number of frames with successful pose detection
    """
    logger.info("metrics_engine: starting extraction for %s", video_path)
    frames = _extract_landmark_frames(video_path)
    fps = _get_fps(video_path)

    if not frames:
        logger.warning("metrics_engine: no pose landmarks found; returning empty metrics")
        return {
            "hip_rotation": None,
            "shoulder_rotation": None,
            "head_movement": None,
            "balance_score": None,
            "wrist_path": None,
            "tempo_ratio": None,
            "frame_count": 0,
        }

    metrics: Dict = {
        "hip_rotation": _hip_rotation(frames),
        "shoulder_rotation": _shoulder_rotation(frames),
        "head_movement": _head_movement(frames),
        "balance_score": _balance_score(frames),
        "wrist_path": _wrist_path(frames),
        "tempo_ratio": _tempo_ratio(frames, fps),
        "frame_count": len(frames),
    }

    logger.info("metrics_engine: extracted metrics: %s", metrics)
    return metrics
