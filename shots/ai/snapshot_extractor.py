"""
Swing frame snapshot extractor.

Identifies four key positions in a golf swing video and saves them as JPEG
images to the media directory:

    setup   – address/setup position (early frames)
    top     – top of backswing (maximum wrist height before impact)
    impact  – impact zone (peak wrist speed frame)
    finish  – finish position (late frames)

Saved paths are relative to MEDIA_ROOT so they can be served via MEDIA_URL.
"""

from __future__ import annotations

import logging
import os
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

try:
    import cv2
except Exception:
    cv2 = None

try:
    import mediapipe as mp
    from mediapipe.python.solutions import pose as _mp_pose_solutions
except Exception:
    mp = None
    _mp_pose_solutions = None


# ---------------------------------------------------------------------------
# Key-frame detection helpers
# ---------------------------------------------------------------------------

def _wrist_speed_series(wrist_positions: List[Optional[tuple]]) -> List[float]:
    """Frame-by-frame right-wrist speed from a position series."""
    import math
    speeds: List[float] = [0.0]
    for i in range(1, len(wrist_positions)):
        a, b = wrist_positions[i - 1], wrist_positions[i]
        if a and b:
            speeds.append(math.hypot(b[0] - a[0], b[1] - a[1]))
        else:
            speeds.append(0.0)
    return speeds


def _find_key_frame_indices(frame_count: int, wrist_positions: List[Optional[tuple]]) -> Dict[str, int]:
    """Return frame indices for setup, top, impact, and finish."""
    speeds = _wrist_speed_series(wrist_positions)

    # Impact: frame of peak wrist speed
    if speeds and max(speeds) > 1e-6:
        impact_idx = speeds.index(max(speeds))
    else:
        impact_idx = int(frame_count * 0.60)

    # Setup: frame at ~8% of total frames
    setup_idx = max(0, int(frame_count * 0.08))

    # Top: frame of minimum wrist y-coordinate before impact (wrist is highest = smallest y)
    min_y_idx = setup_idx
    min_y = float("inf")
    for i in range(setup_idx, impact_idx):
        pos = wrist_positions[i] if i < len(wrist_positions) else None
        if pos and pos[1] < min_y:
            min_y = pos[1]
            min_y_idx = i
    top_idx = min_y_idx

    # Finish: frame at ~88% of total frames (well past impact)
    finish_idx = min(frame_count - 1, int(frame_count * 0.88))

    return {
        "setup": setup_idx,
        "top": top_idx,
        "impact": impact_idx,
        "finish": finish_idx,
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def extract_snapshots(video_path: str, analysis_pk: int) -> Dict[str, str]:
    """Extract four key-position snapshots from a golf swing video.

    Saves JPEG images to:
        media/snapshots/<analysis_pk>/setup.jpg
        media/snapshots/<analysis_pk>/top.jpg
        media/snapshots/<analysis_pk>/impact.jpg
        media/snapshots/<analysis_pk>/finish.jpg

    Args:
        video_path:   Absolute path to the input video.
        analysis_pk:  Primary key of the ShotAnalysis (used for directory naming).

    Returns:
        Dict mapping position name -> MEDIA_ROOT-relative path.
        Empty dict on failure.
    """
    if cv2 is None:
        logger.warning("snapshot_extractor: opencv not available")
        return {}

    if not os.path.exists(video_path):
        logger.error("snapshot_extractor: video not found: %s", video_path)
        return {}

    # Build output directory
    try:
        from django.conf import settings
        snapshot_dir = os.path.join(settings.MEDIA_ROOT, "snapshots", str(analysis_pk))
        os.makedirs(snapshot_dir, exist_ok=True)
    except Exception:
        logger.exception("snapshot_extractor: cannot create snapshot directory")
        return {}

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        logger.error("snapshot_extractor: cannot open video: %s", video_path)
        return {}

    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    if total_frames < 10:
        cap.release()
        logger.warning("snapshot_extractor: video too short (%d frames)", total_frames)
        return {}

    # Run MediaPipe on every Nth frame to cut CPU time; carry forward last known position.
    FRAME_STEP = 3

    # First pass: collect wrist positions (no frame storage — saves memory)
    wrist_positions: List[Optional[tuple]] = []

    if mp is not None and _mp_pose_solutions is not None:
        mp_pose = _mp_pose_solutions
        frame_idx = 0
        last_wrist: Optional[tuple] = None
        try:
            with mp_pose.Pose(
                static_image_mode=False,
                model_complexity=0,
                min_detection_confidence=0.4,
                min_tracking_confidence=0.4,
            ) as pose:
                while True:
                    ret, frame = cap.read()
                    if not ret:
                        break
                    if frame_idx % FRAME_STEP == 0:
                        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                        results = pose.process(rgb)
                        if getattr(results, "pose_landmarks", None):
                            rw = results.pose_landmarks.landmark[16]
                            last_wrist = (rw.x, rw.y)
                        else:
                            last_wrist = None
                    wrist_positions.append(last_wrist)
                    frame_idx += 1
        except Exception:
            logger.exception("snapshot_extractor: pose detection pass failed")
        finally:
            cap.release()
    else:
        frame_idx = 0
        while True:
            ret, frame = cap.read()
            if not ret:
                break
            wrist_positions.append(None)
            frame_idx += 1
        cap.release()

    frame_count = len(wrist_positions)
    if frame_count == 0:
        logger.warning("snapshot_extractor: no frames extracted from video")
        return {}

    key_indices = _find_key_frame_indices(frame_count, wrist_positions)

    # Second pass: seek only to the 4 key frames (avoids storing all frames in RAM)
    unique_indices = set(key_indices.values())
    all_frames: Dict[int, any] = {}
    cap2 = cv2.VideoCapture(video_path)
    if cap2.isOpened():
        fi = 0
        while len(all_frames) < len(unique_indices):
            ret, frame = cap2.read()
            if not ret:
                break
            if fi in unique_indices:
                all_frames[fi] = frame.copy()
            fi += 1
        cap2.release()

    # Save snapshots
    saved: Dict[str, str] = {}
    labels = {"setup": "Setup", "top": "Top", "impact": "Impact", "finish": "Finish"}

    for position, frame_i in key_indices.items():
        frame_i = max(0, min(frame_i, frame_count - 1))
        img = all_frames.get(frame_i)
        if img is None:
            continue

        # Overlay label text
        label = labels[position]
        h, w = img.shape[:2]
        cv2.rectangle(img, (0, h - 36), (w, h), (0, 0, 0), -1)
        cv2.putText(
            img, label,
            (12, h - 12),
            cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2, cv2.LINE_AA,
        )

        filename = f"{position}.jpg"
        abs_path = os.path.join(snapshot_dir, filename)
        rel_path = os.path.join("snapshots", str(analysis_pk), filename)

        try:
            cv2.imwrite(abs_path, img, [cv2.IMWRITE_JPEG_QUALITY, 85])
            saved[position] = rel_path
            logger.debug("snapshot_extractor: saved %s -> %s", position, abs_path)
        except Exception:
            logger.exception("snapshot_extractor: failed to save %s", abs_path)

    logger.info("snapshot_extractor: saved %d snapshots for analysis %s", len(saved), analysis_pk)
    return saved
