"""
Swing scoring engine.

Converts raw biomechanical metrics into normalised 0-100 scores for each
dimension of the golf swing, plus an overall weighted swing score.

All functions are pure (no I/O, no Django imports) so they can be used in
tests and scripts without Django setup.
"""

from __future__ import annotations

import logging
import statistics
from typing import Dict, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Per-dimension scorers
# ---------------------------------------------------------------------------

def _score_tempo(tempo_ratio: Optional[float]) -> Optional[int]:
    """Score tempo on 0-100 scale.

    PGA Tour benchmark ≈ 3:1.  Perfect (3:1) = 100.
    Very fast (1:1 or below) = ~15.  Very slow (5:1+) = ~40.
    """
    if tempo_ratio is None:
        return None
    if 2.8 <= tempo_ratio <= 3.2:
        return 100
    if 2.5 <= tempo_ratio < 2.8:
        return int(80 + (tempo_ratio - 2.5) / 0.3 * 20)
    if 3.2 < tempo_ratio <= 3.8:
        return int(80 + (3.8 - tempo_ratio) / 0.6 * 20)
    if tempo_ratio < 2.5:
        return max(10, int(80 - (2.5 - tempo_ratio) * 35))
    return max(20, int(80 - (tempo_ratio - 3.8) * 20))


def _score_balance(balance_score: Optional[int], sway: Optional[float]) -> Optional[int]:
    """Combined balance score from hip stability and sway measurement."""
    components = []
    if balance_score is not None:
        components.append(balance_score)
    if sway is not None:
        # sway < 3 is excellent, > 12 is poor
        sway_score = max(0, min(100, int(100 - (sway / 12.0) * 100)))
        components.append(sway_score)
    if not components:
        return None
    return int(statistics.mean(components))


def _score_rotation(x_factor: Optional[float], shoulder_rotation: Optional[float],
                    hip_rotation: Optional[float]) -> Optional[int]:
    """Score rotation quality based on X-factor and shoulder/hip values.

    Target X-factor (irons): 40-50°.  Target shoulder rotation: 80-100°.
    """
    components = []
    if x_factor is not None:
        # X-factor 40-50 = 100, <10 = 20, >60 = 80 (too loose)
        if x_factor >= 40:
            x_sc = min(100, int(80 + (min(x_factor, 50) - 40) * 2))
        else:
            x_sc = max(10, int(20 + x_factor * 1.5))
        components.append(x_sc)
    if shoulder_rotation is not None:
        sh_sc = max(10, min(100, int((shoulder_rotation / 90.0) * 100)))
        components.append(sh_sc)
    if hip_rotation is not None:
        # Ideal hip rotation: 40-55° for irons
        if 40 <= hip_rotation <= 55:
            hip_sc = 100
        elif hip_rotation < 40:
            hip_sc = max(30, int((hip_rotation / 40.0) * 100))
        else:
            hip_sc = max(50, int(100 - (hip_rotation - 55) * 1.5))
        components.append(hip_sc)
    if not components:
        return None
    return int(statistics.mean(components))


def _score_posture(head_movement: Optional[float], spine_angle: Optional[float]) -> Optional[int]:
    """Score posture from head stability and spine angle consistency."""
    components = []
    if head_movement is not None:
        # head_movement < 8 = excellent, > 30 = poor
        head_sc = max(0, min(100, int(100 - head_movement * 3.2)))
        components.append(head_sc)
    if spine_angle is not None:
        # Good address spine angle 25-40 degrees from vertical
        if 25 <= spine_angle <= 40:
            spine_sc = 100
        else:
            spine_sc = max(20, int(100 - abs(spine_angle - 32.5) * 3))
        components.append(spine_sc)
    if not components:
        return None
    return int(statistics.mean(components))


def _score_sequencing(rotational_sequencing: Optional[int],
                      transition_timing: Optional[float]) -> Optional[int]:
    """Score kinematic sequencing from rotation order and transition timing."""
    components = []
    if rotational_sequencing is not None:
        components.append(rotational_sequencing)
    if transition_timing is not None:
        # Ideal transition at 0.50-0.65 of total swing
        if 0.50 <= transition_timing <= 0.65:
            tt_sc = 100
        elif transition_timing < 0.50:
            tt_sc = max(30, int(100 - (0.50 - transition_timing) * 200))
        else:
            tt_sc = max(40, int(100 - (transition_timing - 0.65) * 150))
        components.append(tt_sc)
    if not components:
        return None
    return int(statistics.mean(components))


def _score_consistency(hand_path_consistency: Optional[int],
                       follow_through: Optional[float]) -> Optional[int]:
    """Score swing consistency from hand path repeatability and follow-through."""
    components = []
    if hand_path_consistency is not None:
        components.append(hand_path_consistency)
    if follow_through is not None:
        # Good follow-through: > 40%, excellent > 50%
        if follow_through >= 50:
            ft_sc = 100
        elif follow_through >= 35:
            ft_sc = int(60 + (follow_through - 35) * 2.7)
        else:
            ft_sc = max(10, int(follow_through * 1.7))
        components.append(ft_sc)
    if not components:
        return None
    return int(statistics.mean(components))


# ---------------------------------------------------------------------------
# Weights for overall score
# ---------------------------------------------------------------------------

_DIMENSION_WEIGHTS: Dict[str, float] = {
    "tempo_score": 0.20,
    "balance_score": 0.20,
    "rotation_score": 0.20,
    "posture_score": 0.15,
    "sequencing_score": 0.15,
    "consistency_score": 0.10,
}


def _overall(scores: Dict[str, Optional[int]]) -> Optional[int]:
    total_weight = 0.0
    weighted_sum = 0.0
    for key, weight in _DIMENSION_WEIGHTS.items():
        val = scores.get(key)
        if val is not None:
            weighted_sum += val * weight
            total_weight += weight
    if total_weight < 0.3:
        return None
    return min(100, max(0, int(weighted_sum / total_weight)))


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def compute_scores(metrics: Dict) -> Dict[str, Optional[int]]:
    """Compute 0-100 scores for each swing dimension plus an overall score.

    Args:
        metrics: Output of metrics_engine.extract_swing_metrics().

    Returns:
        Dict with keys: overall_score, tempo_score, balance_score,
        rotation_score, posture_score, sequencing_score, consistency_score.
        Any score that cannot be computed is None.
    """
    scores: Dict[str, Optional[int]] = {
        "tempo_score": _score_tempo(metrics.get("tempo_ratio")),
        "balance_score": _score_balance(metrics.get("balance_score"), metrics.get("sway")),
        "rotation_score": _score_rotation(
            metrics.get("x_factor"),
            metrics.get("shoulder_rotation"),
            metrics.get("hip_rotation"),
        ),
        "posture_score": _score_posture(
            metrics.get("head_movement"),
            metrics.get("spine_angle"),
        ),
        "sequencing_score": _score_sequencing(
            metrics.get("rotational_sequencing"),
            metrics.get("transition_timing"),
        ),
        "consistency_score": _score_consistency(
            metrics.get("hand_path_consistency"),
            metrics.get("follow_through_completion"),
        ),
    }
    scores["overall_score"] = _overall(scores)
    logger.debug("scoring_engine: scores=%s", scores)
    return scores


def score_label(score: Optional[int]) -> str:
    """Return a human-readable label for a 0-100 score."""
    if score is None:
        return "N/A"
    if score >= 85:
        return "Excellent"
    if score >= 70:
        return "Good"
    if score >= 50:
        return "Average"
    return "Needs Work"


def score_color(score: Optional[int]) -> str:
    """Return a Tailwind colour class string matching green/yellow/red scale."""
    if score is None:
        return "gray"
    if score >= 70:
        return "green"
    if score >= 50:
        return "yellow"
    return "red"
