"""
Prompt builder for AI golf coaching.

Converts structured swing metrics, scores, and contextual history into a
precise coaching prompt for the OpenAI chat completions API.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

def _fmt(value: Any, unit: str = "", precision: int = 1) -> str:
    if value is None:
        return "N/A"
    if isinstance(value, float):
        return f"{value:.{precision}f}{unit}"
    return f"{value}{unit}"


def _score_label(score: Optional[int]) -> str:
    if score is None:
        return "N/A"
    if score >= 85:
        return f"{score}/100 (excellent)"
    if score >= 70:
        return f"{score}/100 (good)"
    if score >= 50:
        return f"{score}/100 (average)"
    return f"{score}/100 (needs work)"


def _tempo_label(ratio: Optional[float]) -> str:
    if ratio is None:
        return "N/A"
    if ratio < 1.5:
        return f"{ratio:.2f}:1 (very rushed — significantly below PGA 3:1 benchmark)"
    if ratio < 2.5:
        return f"{ratio:.2f}:1 (quick — below PGA 3:1 benchmark)"
    if ratio <= 3.5:
        return f"{ratio:.2f}:1 (on tempo — within PGA benchmark range)"
    return f"{ratio:.2f}:1 (slow — long backswing relative to downswing)"


def _shot_shape_context(shape: Optional[str]) -> str:
    explanations = {
        "slice":    "Biomechanical indicators suggest an over-the-top club path causing a left-to-right ball flight.",
        "fade":     "Mechanics indicate a slight left-to-right flight — controlled fade or mild over-the-top path.",
        "straight": "Club path indicators suggest a neutral to straight ball flight.",
        "draw":     "Mechanics indicate an inside-out path producing a right-to-left draw.",
        "hook":     "Biomechanical data suggests an aggressive inside-out path — possible hook tendency.",
        "push":     "Path indicators suggest a blocked/pushed shot — limited x-factor and hip clearing.",
        "pull":     "Path indicators suggest a pulled shot — over-the-top with face pointing left.",
    }
    if not shape or shape == "unknown":
        return "Shot shape: N/A"
    return f"Estimated shot shape: {shape.title()} — {explanations.get(shape, '')}"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def build_coaching_prompt(
    metrics: Dict,
    club: str = "unknown",
    distance_yards: Optional[float] = None,
    scores: Optional[Dict] = None,
    trend_summary: Optional[str] = None,
    pro_comparison: Optional[str] = None,
) -> str:
    """Build a personalised, data-rich golf coaching prompt.

    Args:
        metrics:        Output of metrics_engine.extract_swing_metrics().
        club:           Club used (e.g. 'Driver', '7-iron').
        distance_yards: Reported shot distance in yards.
        scores:         Output of scoring_engine.compute_scores() (optional).
        trend_summary:  Player trend summary from swing_memory (optional).
        pro_comparison: Pro comparison description from pro_comparisons (optional).

    Returns:
        A formatted prompt string for the OpenAI chat completions API.
    """
    frames = metrics.get("frame_count", 0)
    hip = _fmt(metrics.get("hip_rotation"), "°")
    shoulder = _fmt(metrics.get("shoulder_rotation"), "°")
    x_factor = _fmt(metrics.get("x_factor"), "°")
    spine_angle = _fmt(metrics.get("spine_angle"), "°")
    head = _fmt(metrics.get("head_movement"))
    sway = _fmt(metrics.get("sway"))
    wrist_lag = _fmt(metrics.get("wrist_lag"), "°")
    hand_consistency = _fmt(metrics.get("hand_path_consistency"))
    wrist_path = _fmt(metrics.get("wrist_path"))
    tempo = _tempo_label(metrics.get("tempo_ratio"))
    transition = _fmt(metrics.get("transition_timing"))
    follow_through = _fmt(metrics.get("follow_through_completion"), "%")
    sequencing = _fmt(metrics.get("rotational_sequencing"))
    shot_shape_line = _shot_shape_context(metrics.get("shot_shape"))

    distance_line = f"- Reported shot distance: {distance_yards:.0f} yards\n" if distance_yards else ""

    # Scores block
    scores_block = ""
    if scores:
        scores_block = f"""
Computed swing scores (0–100):
- Overall swing score: {_score_label(scores.get('overall_score'))}
- Tempo score: {_score_label(scores.get('tempo_score'))}
- Balance score: {_score_label(scores.get('balance_score'))}
- Rotation score: {_score_label(scores.get('rotation_score'))}
- Posture score: {_score_label(scores.get('posture_score'))}
- Sequencing score: {_score_label(scores.get('sequencing_score'))}
- Consistency score: {_score_label(scores.get('consistency_score'))}
"""

    # History/trend block
    history_block = ""
    if trend_summary:
        history_block = f"\nPlayer trend history:\n{trend_summary}\n"
    if pro_comparison:
        history_block += f"\nPro comparison context:\n{pro_comparison}\n"

    prompt = f"""You are a PGA-certified golf swing coach analysing a player's swing from biomechanical computer-vision data.

Shot context:
- Club used: {club}
{distance_line}- Analysis based on {frames} pose-detected video frames

BIOMECHANICAL METRICS:
Rotation:
- Hip rotation (max change from address): {hip}   [Benchmark: irons 40-55°, driver 45-65°]
- Shoulder rotation (max change from address): {shoulder}   [Benchmark: 90-110°]
- X-factor (shoulder–hip differential): {x_factor}   [Benchmark PGA Tour: 40-50°]
- Rotational sequencing score (hip-leads-shoulders): {sequencing}/100   [70+ = good]

Posture & Stability:
- Spine angle from vertical: {spine_angle}   [Benchmark: 25-40° forward tilt at setup]
- Head movement (total path ×100, lower = steadier): {head}   [<10 excellent, >20 poor]
- Balance score (lateral hip stability): {_fmt(metrics.get('balance_score'))}/100   [80+ excellent]
- Lateral sway (max hip displacement ×100): {sway}   [<5 excellent, >10 problematic]

Swing Path & Timing:
- Wrist lag / elbow angle at peak: {wrist_lag}   [>90° = good lag]
- Hand path consistency score: {hand_consistency}/100   [80+ = repeatable path]
- Wrist path arc length (club-path proxy ×100): {wrist_path}
- Swing tempo ratio (backswing ÷ downswing): {tempo}   [PGA ≈ 3:1]
- Transition timing (0–1 scale, where 0.5–0.65 = ideal): {transition}
- Follow-through completion: {follow_through}   [>40% = complete finish]

{shot_shape_line}
{scores_block}{history_block}
COACHING BENCHMARKS:
- PGA Tour X-factor average at top: ~45°
- PGA Tour tempo: ~3:1 (Ernie Els 3.5:1, Nick Price 2.4:1)
- Head movement under 8 (×100) = tour-level stability
- Hips should clear 5+ frames before shoulder peak for elite sequencing

Based on all of the above, provide personalised PGA-quality coaching feedback.
Reference the SPECIFIC numbers — do not give generic advice.
Where history/trends exist, acknowledge improvement or regression.
Explain the mechanical WHY behind each fault (how the number causes the miss).

Return ONLY valid JSON — no markdown, no text outside the JSON:

{{
  "main_fault": "<One sentence identifying the single most important swing fault, referencing the specific metric value and explaining why it causes a problem.>",
  "strength": "<One sentence describing the strongest element, referencing the specific number and what it means for the swing.>",
  "drill": "<Name of drill and one sentence on how to execute it to address the main fault.>",
  "swing_thought": "<A single short swing cue — vivid, memorable, under 10 words.>"
}}"""

    return prompt


def build_system_prompt() -> str:
    return (
        "You are an expert PGA golf swing coach with 20 years of tour-level coaching experience. "
        "You analyse biomechanical data from computer vision and provide precise, personalised coaching. "
        "Always reference specific metric values. Never give generic advice. "
        "Explain the mechanical cause-and-effect behind each issue. "
        "Respond in strict JSON as instructed. Keep each value under 80 words."
    )
