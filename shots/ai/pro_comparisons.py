"""
Tour pro benchmark comparison system.

Matches a player's swing metrics against published biomechanical profiles of
elite tour professionals and returns the closest match with a contextual
explanation.

Benchmark data is sourced from publicly available biomechanics research and
coach commentary.  All ranges are approximate.
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Benchmark data
# ---------------------------------------------------------------------------

# Each profile is a dict of metric -> (min, max) ideal range for that player's style.
# None means the metric is not a defining characteristic of that player.
PRO_PROFILES: List[Dict] = [
    {
        "name": "Rory McIlroy",
        "style": "power with athleticism",
        "tempo_ratio": (2.8, 3.2),
        "x_factor": (48, 58),
        "hip_rotation": (50, 65),
        "shoulder_rotation": (110, 130),
        "balance_score": (75, 100),
        "rotational_sequencing": (75, 100),
        "sway": (0, 6),
        "head_movement": (0, 12),
        "signature": "elite hip clearance and explosive rotational power",
    },
    {
        "name": "Tiger Woods",
        "style": "precision and control",
        "tempo_ratio": (2.7, 3.1),
        "x_factor": (45, 55),
        "hip_rotation": (45, 58),
        "shoulder_rotation": (100, 120),
        "balance_score": (85, 100),
        "rotational_sequencing": (80, 100),
        "sway": (0, 4),
        "head_movement": (0, 8),
        "signature": "exceptional balance, minimal head movement, and precise sequencing",
    },
    {
        "name": "Jon Rahm",
        "style": "compact power",
        "tempo_ratio": (2.4, 2.9),
        "x_factor": (38, 50),
        "hip_rotation": (42, 55),
        "shoulder_rotation": (90, 110),
        "balance_score": (80, 100),
        "rotational_sequencing": (65, 90),
        "sway": (0, 7),
        "head_movement": (0, 15),
        "signature": "shorter backswing with powerful, compact rotation",
    },
    {
        "name": "Scottie Scheffler",
        "style": "efficient sequencing",
        "tempo_ratio": (3.0, 3.6),
        "x_factor": (40, 52),
        "hip_rotation": (44, 56),
        "shoulder_rotation": (95, 115),
        "balance_score": (80, 100),
        "rotational_sequencing": (78, 100),
        "sway": (0, 5),
        "head_movement": (0, 10),
        "signature": "smooth tempo and elite kinematic sequencing",
    },
    {
        "name": "Dustin Johnson",
        "style": "unorthodox power",
        "tempo_ratio": (2.6, 3.2),
        "x_factor": (50, 65),
        "hip_rotation": (55, 70),
        "shoulder_rotation": (115, 135),
        "balance_score": (65, 90),
        "rotational_sequencing": (60, 85),
        "sway": (3, 12),
        "head_movement": (8, 22),
        "signature": "extreme shoulder turn and high X-factor generating tremendous distance",
    },
]

# Metrics used for matching, with their weights
_MATCH_METRICS: Dict[str, float] = {
    "tempo_ratio": 0.25,
    "x_factor": 0.25,
    "hip_rotation": 0.15,
    "rotational_sequencing": 0.15,
    "balance_score": 0.10,
    "head_movement": 0.10,
}


# ---------------------------------------------------------------------------
# Comparison logic
# ---------------------------------------------------------------------------

def _range_score(value: Optional[float], range_min: float, range_max: float) -> float:
    """Return 0.0-1.0 based on how close value is to the ideal range."""
    if value is None:
        return 0.5  # Neutral when we have no data
    mid = (range_min + range_max) / 2.0
    half_width = (range_max - range_min) / 2.0 + 1e-6
    deviation = abs(value - mid) / half_width
    return max(0.0, 1.0 - deviation)


def _match_score(metrics: Dict, profile: Dict) -> float:
    """Compute a 0-1 similarity score between player metrics and a pro profile."""
    total_weight = 0.0
    weighted_score = 0.0
    for metric, weight in _MATCH_METRICS.items():
        range_val = profile.get(metric)
        if range_val is None:
            continue
        player_val = metrics.get(metric)
        sc = _range_score(player_val, range_val[0], range_val[1])
        weighted_score += sc * weight
        total_weight += weight
    if total_weight < 1e-6:
        return 0.0
    return weighted_score / total_weight


def get_pro_comparison(metrics: Dict) -> Dict[str, str]:
    """Find the closest tour pro match and return a contextual comparison.

    Args:
        metrics: Output of metrics_engine.extract_swing_metrics().

    Returns:
        Dict with keys:
            pro_name    – name of the closest matched pro
            similarity  – 'very similar' / 'similar' / 'some similarities'
            description – one-sentence comparison explanation
    """
    if metrics.get("frame_count", 0) == 0:
        return {"pro_name": "", "similarity": "", "description": ""}

    scored: List[Tuple[float, Dict]] = [
        (_match_score(metrics, profile), profile)
        for profile in PRO_PROFILES
    ]
    scored.sort(key=lambda t: t[0], reverse=True)
    best_score, best_profile = scored[0]

    if best_score >= 0.75:
        similarity = "very similar"
    elif best_score >= 0.58:
        similarity = "similar"
    else:
        similarity = "some similarities"

    # Build dimension-specific mention
    highlights: List[str] = []
    tempo = metrics.get("tempo_ratio")
    if tempo is not None:
        t_range = best_profile.get("tempo_ratio")
        if t_range and t_range[0] <= tempo <= t_range[1]:
            highlights.append("swing tempo")
    x_factor = metrics.get("x_factor")
    if x_factor is not None:
        x_range = best_profile.get("x_factor")
        if x_range and x_range[0] <= x_factor <= x_range[1]:
            highlights.append("X-factor")
    seq = metrics.get("rotational_sequencing")
    if seq is not None:
        s_range = best_profile.get("rotational_sequencing")
        if s_range and s_range[0] <= seq <= s_range[1]:
            highlights.append("rotational sequencing")

    if highlights:
        highlight_str = " and ".join(highlights[:2])
        description = (
            f"Your {highlight_str} shows {similarity} characteristics to "
            f"{best_profile['name']}, known for {best_profile['signature']}."
        )
    else:
        description = (
            f"Your swing mechanics show {similarity} characteristics to "
            f"{best_profile['name']}, known for {best_profile['signature']}."
        )

    logger.debug(
        "pro_comparisons: best match=%s score=%.2f",
        best_profile["name"], best_score,
    )
    return {
        "pro_name": best_profile["name"],
        "similarity": similarity,
        "description": description,
    }
