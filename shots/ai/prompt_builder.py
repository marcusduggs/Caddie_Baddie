"""
Prompt builder for AI golf coaching.

Converts structured swing metrics into a precise, context-rich prompt
for the OpenAI chat completions API.  The prompt is designed to elicit
PGA-style coaching feedback that is concise and actionable.
"""

from __future__ import annotations

from typing import Any, Dict, Optional


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fmt(value: Any, unit: str = "", precision: int = 1) -> str:
    """Format a metric value for the prompt; returns 'N/A' when None."""
    if value is None:
        return "N/A"
    if isinstance(value, float):
        return f"{value:.{precision}f}{unit}"
    return f"{value}{unit}"


def _balance_label(score: Optional[int]) -> str:
    """Human-readable description of a balance score."""
    if score is None:
        return "unknown"
    if score >= 80:
        return f"{score}/100 (excellent)"
    if score >= 60:
        return f"{score}/100 (acceptable)"
    return f"{score}/100 (needs improvement)"


def _tempo_label(ratio: Optional[float]) -> str:
    """Contextualise a tempo ratio relative to the PGA ~3:1 benchmark."""
    if ratio is None:
        return "N/A"
    if ratio < 1.5:
        return f"{ratio:.2f}:1 (very fast — rushed downswing)"
    if ratio < 2.5:
        return f"{ratio:.2f}:1 (quick — below PGA benchmark of ~3:1)"
    if ratio <= 4.0:
        return f"{ratio:.2f}:1 (on tempo — within PGA range)"
    return f"{ratio:.2f}:1 (slow — long backswing relative to downswing)"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def build_coaching_prompt(metrics: Dict, club: str = "unknown", distance_yards: Optional[float] = None) -> str:
    """Build a golf coaching prompt from extracted swing metrics.

    Args:
        metrics:        Output of metrics_engine.extract_swing_metrics().
        club:           The club used for this shot (e.g. 'Driver', '7-iron').
        distance_yards: Reported shot distance in yards (optional context).

    Returns:
        A formatted string suitable for use as the user message in an OpenAI
        chat completions call.
    """
    hip = _fmt(metrics.get("hip_rotation"), "°")
    shoulder = _fmt(metrics.get("shoulder_rotation"), "°")
    head = _fmt(metrics.get("head_movement"))
    balance = _balance_label(metrics.get("balance_score"))
    wrist = _fmt(metrics.get("wrist_path"))
    tempo = _tempo_label(metrics.get("tempo_ratio"))
    frames = metrics.get("frame_count", 0)

    distance_line = ""
    if distance_yards:
        distance_line = f"- Reported shot distance: {distance_yards:.0f} yards\n"

    prompt = f"""You are a PGA-certified golf swing coach analysing a player's swing from biomechanical data captured via computer vision.

Swing data captured from {frames} video frames:
- Club used: {club}
{distance_line}- Hip rotation (max angular change from address): {hip}
- Shoulder rotation (max angular change from address): {shoulder}
- Head/skull movement (path length, lower = steadier; scale 0-100): {head}
- Balance score (lateral hip stability, 0-100, higher = better): {balance}
- Wrist path arc length (club-path proxy, scale 0-100): {wrist}
- Swing tempo ratio (backswing frames ÷ downswing frames; PGA benchmark ≈ 3:1): {tempo}

Coaching benchmarks for reference:
- A good hip rotation is 40-55° for irons, 45-65° for driver.
- Shoulder rotation should exceed hip rotation by 15-25° (X-factor).
- Head movement below 10 is excellent; above 20 indicates significant drift.
- Balance score 80+ is excellent; below 60 often correlates with power loss.
- PGA Tour tempo ratio averages roughly 3:1.

Based on this data, provide concise PGA-style coaching feedback in the following JSON structure (return ONLY valid JSON, no markdown, no commentary outside the JSON):

{{
  "main_fault": "<One sentence describing the single most important swing fault visible in the data.>",
  "strength": "<One sentence describing the strongest biomechanical element in the swing.>",
  "drill": "<Name and one-sentence description of a specific drill to address the main fault.>",
  "swing_thought": "<A single short swing cue the player should repeat during practice.>"
}}"""

    return prompt


def build_system_prompt() -> str:
    """Return the system-role prompt for the coaching agent."""
    return (
        "You are an expert PGA golf swing coach with 20 years of tour-level coaching experience. "
        "You analyse biomechanical data captured from computer vision and provide precise, "
        "actionable coaching feedback. Always respond in strict JSON as instructed. "
        "Keep each value under 60 words. Avoid generic advice — reference the specific numbers provided."
    )
