"""
Persistent swing memory and trend analysis.

Tracks recurring swing tendencies per user across sessions and generates
improvement summaries by comparing the current swing against recent history.

All model access is wrapped in try/except so a DB error never blocks video
processing.
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Tendency definitions
# ---------------------------------------------------------------------------

# Each tendency is a (label, detector_fn) pair.
# The detector returns True if the tendency is present in the metrics dict.

def _has_fast_tempo(m: Dict) -> bool:
    t = m.get("tempo_ratio")
    return t is not None and t < 2.0


def _has_slow_tempo(m: Dict) -> bool:
    t = m.get("tempo_ratio")
    return t is not None and t > 4.0


def _has_poor_balance(m: Dict) -> bool:
    b = m.get("balance_score")
    return b is not None and b < 50


def _has_excess_sway(m: Dict) -> bool:
    s = m.get("sway")
    return s is not None and s > 10.0


def _has_head_drift(m: Dict) -> bool:
    h = m.get("head_movement")
    return h is not None and h > 20.0


def _has_low_xfactor(m: Dict) -> bool:
    x = m.get("x_factor")
    return x is not None and x < 20.0


def _has_early_extension(m: Dict) -> bool:
    # Proxy: poor balance + low x_factor + poor sequencing
    return _has_poor_balance(m) and _has_low_xfactor(m)


def _has_poor_sequencing(m: Dict) -> bool:
    s = m.get("rotational_sequencing")
    return s is not None and s < 45


def _has_over_the_top(m: Dict) -> bool:
    # Proxy: wrist path high relative to shoulder rotation + poor sequencing
    wrist = m.get("wrist_path")
    shoulder = m.get("shoulder_rotation")
    seq = m.get("rotational_sequencing")
    if wrist is None or shoulder is None or shoulder < 1:
        return False
    return (wrist / shoulder) > 2.5 and (seq is None or seq < 50)


def _has_slice_tendency(m: Dict) -> bool:
    return m.get("shot_shape") in ("slice", "fade")


def _has_hook_tendency(m: Dict) -> bool:
    return m.get("shot_shape") in ("hook", "draw")


def _has_poor_followthrough(m: Dict) -> bool:
    ft = m.get("follow_through_completion")
    return ft is not None and ft < 30.0


TENDENCY_DETECTORS: List[Tuple[str, str, callable]] = [
    ("fast_tempo", "Rushed downswing / fast tempo", _has_fast_tempo),
    ("slow_tempo", "Slow tempo / long backswing", _has_slow_tempo),
    ("poor_balance", "Poor lateral balance", _has_poor_balance),
    ("excess_sway", "Excess lateral sway", _has_excess_sway),
    ("head_drift", "Head movement / drift", _has_head_drift),
    ("low_xfactor", "Limited X-factor / shoulder turn", _has_low_xfactor),
    ("early_extension", "Early extension tendency", _has_early_extension),
    ("poor_sequencing", "Poor rotational sequencing", _has_poor_sequencing),
    ("over_the_top", "Over-the-top swing path", _has_over_the_top),
    ("slice_tendency", "Slice / fade ball flight", _has_slice_tendency),
    ("hook_tendency", "Hook / draw ball flight", _has_hook_tendency),
    ("poor_followthrough", "Incomplete follow-through", _has_poor_followthrough),
]


# ---------------------------------------------------------------------------
# Tendency detection
# ---------------------------------------------------------------------------

def detect_tendencies(metrics: Dict) -> List[str]:
    """Return a list of tendency type keys present in this swing's metrics."""
    return [key for key, _, detector in TENDENCY_DETECTORS if detector(metrics)]


# ---------------------------------------------------------------------------
# Database interaction
# ---------------------------------------------------------------------------

def update_swing_memory(user_id: int, analysis_pk: int, metrics: Dict) -> None:
    """Persist detected tendencies for this swing to the SwingTendency model.

    Creates or updates a SwingTendency record for each detected tendency.
    All errors are caught so a DB issue never blocks video processing.
    """
    try:
        from shots.models import SwingTendency, ShotAnalysis
        sa = ShotAnalysis.objects.get(pk=analysis_pk)
        tendencies = detect_tendencies(metrics)

        for key, label, _ in TENDENCY_DETECTORS:
            if key in tendencies:
                obj, created = SwingTendency.objects.get_or_create(
                    user_id=user_id,
                    tendency_type=key,
                    defaults={"label": label, "last_seen_analysis": sa, "occurrence_count": 1},
                )
                if not created:
                    obj.occurrence_count += 1
                    obj.last_seen_analysis = sa
                    obj.label = label
                    obj.save(update_fields=["occurrence_count", "last_seen_analysis", "label", "last_seen_at"])
                    logger.debug("swing_memory: updated tendency %s count=%d", key, obj.occurrence_count)
            else:
                # Don't decrement — just don't increment for absent tendencies
                pass
    except Exception:
        logger.exception("swing_memory: failed to update tendency records for user %s", user_id)


def get_user_tendencies(user_id: int, min_occurrences: int = 2) -> List[Dict]:
    """Return the user's recurring swing tendencies.

    Only returns tendencies seen at least min_occurrences times.
    """
    try:
        from shots.models import SwingTendency
        qs = (
            SwingTendency.objects
            .filter(user_id=user_id, occurrence_count__gte=min_occurrences)
            .order_by("-occurrence_count")
        )
        return [
            {"type": t.tendency_type, "label": t.label, "count": t.occurrence_count}
            for t in qs
        ]
    except Exception:
        logger.exception("swing_memory: failed to load tendencies for user %s", user_id)
        return []


# ---------------------------------------------------------------------------
# Trend summary generation
# ---------------------------------------------------------------------------

def _pct_change(old: Optional[float], new: Optional[float]) -> Optional[float]:
    if old is None or new is None or old == 0:
        return None
    return round((new - old) / abs(old) * 100, 1)


def generate_trend_summary(user_id: int, current_metrics: Dict, lookback: int = 5) -> str:
    """Compare current swing against recent history and build a trend summary.

    Args:
        user_id:         Django user pk.
        current_metrics: Metrics from the most recent swing.
        lookback:        How many recent swings to compare against.

    Returns:
        A multi-sentence string describing observed trends.
        Returns empty string if insufficient history.
    """
    try:
        import json
        from shots.models import ShotAnalysis
        recent = (
            ShotAnalysis.objects
            .filter(user_id=user_id, ai_metrics_json__isnull=False)
            .exclude(ai_metrics_json="")
            .order_by("-created_at")[:lookback]
        )
        past_metrics_list = []
        for sa in recent:
            try:
                m = json.loads(sa.ai_metrics_json)
                if m.get("frame_count", 0) > 0:
                    past_metrics_list.append(m)
            except Exception:
                pass
    except Exception:
        logger.exception("swing_memory: failed to load recent swings for user %s", user_id)
        return ""

    if len(past_metrics_list) < 2:
        return ""

    # Compute averages for key metrics from recent history
    def avg(key: str) -> Optional[float]:
        vals = [m.get(key) for m in past_metrics_list if m.get(key) is not None]
        return round(sum(vals) / len(vals), 1) if vals else None

    insights: List[str] = []

    # Tempo trend
    avg_tempo = avg("tempo_ratio")
    curr_tempo = current_metrics.get("tempo_ratio")
    if avg_tempo and curr_tempo:
        pct = _pct_change(avg_tempo, curr_tempo)
        if pct is not None:
            if pct > 15:
                insights.append(f"Your tempo has slowed by {abs(pct):.0f}% compared to recent swings — trending toward the PGA 3:1 benchmark." if curr_tempo < 3.5 else f"Your tempo has slowed significantly ({abs(pct):.0f}%) — consider a more dynamic transition.")
            elif pct < -15:
                insights.append(f"Your tempo has become {abs(pct):.0f}% faster than your recent average — focus on a smooth transition at the top.")

    # Balance trend
    avg_bal = avg("balance_score")
    curr_bal = current_metrics.get("balance_score")
    if avg_bal and curr_bal:
        diff = curr_bal - avg_bal
        if diff >= 10:
            insights.append(f"Your balance has improved {diff:.0f} points compared to your last {len(past_metrics_list)} swings.")
        elif diff <= -10:
            insights.append(f"Your balance score has dropped {abs(diff):.0f} points — pay attention to lateral stability through the swing.")

    # Hip rotation trend
    avg_hip = avg("hip_rotation")
    curr_hip = current_metrics.get("hip_rotation")
    if avg_hip and curr_hip:
        pct = _pct_change(avg_hip, curr_hip)
        if pct and abs(pct) >= 12:
            direction = "improved" if pct > 0 else "decreased"
            insights.append(f"Your hip rotation has {direction} {abs(pct):.0f}% over your last {len(past_metrics_list)} swings.")

    # X-factor trend
    avg_xf = avg("x_factor")
    curr_xf = current_metrics.get("x_factor")
    if avg_xf and curr_xf:
        diff = curr_xf - avg_xf
        if abs(diff) >= 5:
            direction = "increased" if diff > 0 else "decreased"
            insights.append(f"Your X-factor has {direction} by {abs(diff):.0f}° — {'more rotational power potential' if diff > 0 else 'address your shoulder turn for more power'}.")

    # Recurring tendency warning
    tendencies = get_user_tendencies(user_id, min_occurrences=3)
    if tendencies:
        top = tendencies[0]
        insights.append(f"Recurring pattern: {top['label']} has appeared in {top['count']} recent sessions — make this a practice priority.")

    if not insights:
        return ""

    return " ".join(insights)
