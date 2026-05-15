"""
Conversational AI golf coach.

Accepts a natural-language question from the player and responds using their
specific swing data, tendencies, and coaching history as context.  Designed
to feel like a follow-up conversation with their swing coach.

Usage:
    from shots.ai.chat_agent import answer_question
    response = answer_question(question, analysis_pk, user_id)
"""

from __future__ import annotations

import json
import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

_DEFAULT_MODEL = "gpt-4o"
_MAX_RESPONSE_TOKENS = 300


def _build_context(analysis_pk: int, user_id: int) -> str:
    """Build a context block from the player's swing data and history."""
    try:
        from shots.models import ShotAnalysis
        sa = ShotAnalysis.objects.get(pk=analysis_pk)
    except Exception:
        return ""

    lines = [f"Club: {sa.club or 'unknown'}", f"Distance: {sa.distance} yards"]

    if sa.ai_metrics_json:
        try:
            m = json.loads(sa.ai_metrics_json)
            lines.append(
                f"Metrics: hip_rotation={m.get('hip_rotation')}°, "
                f"shoulder_rotation={m.get('shoulder_rotation')}°, "
                f"x_factor={m.get('x_factor')}°, "
                f"tempo={m.get('tempo_ratio')}:1, "
                f"balance={m.get('balance_score')}/100, "
                f"sway={m.get('sway')}, "
                f"sequencing={m.get('rotational_sequencing')}/100"
            )
        except Exception:
            pass

    if sa.ai_overall_score is not None:
        lines.append(f"Swing score: {sa.ai_overall_score}/100")
    if sa.ai_shot_shape:
        lines.append(f"Estimated shot shape: {sa.ai_shot_shape}")
    if sa.ai_main_fault:
        lines.append(f"Identified main fault: {sa.ai_main_fault}")
    if sa.ai_strength:
        lines.append(f"Key strength: {sa.ai_strength}")
    if sa.ai_pro_comparison:
        lines.append(f"Pro comparison: {sa.ai_pro_comparison}")
    if sa.ai_trend_summary:
        lines.append(f"Trend summary: {sa.ai_trend_summary}")

    # Recent tendencies
    try:
        from shots.ai.swing_memory import get_user_tendencies
        tendencies = get_user_tendencies(user_id, min_occurrences=2)
        if tendencies:
            tendency_labels = ", ".join(t["label"] for t in tendencies[:3])
            lines.append(f"Recurring tendencies: {tendency_labels}")
    except Exception:
        pass

    return "\n".join(lines)


def answer_question(
    question: str,
    analysis_pk: int,
    user_id: int,
    history: Optional[list] = None,
) -> str:
    """Answer a player's golf question using their swing data as context.

    Args:
        question:    The player's natural-language question.
        analysis_pk: PK of the ShotAnalysis to use for context.
        user_id:     Django user pk (for loading tendencies/history).
        history:     Prior conversation as [{"role": "user"|"assistant", "content": "..."}].
                     Kept to the last 10 exchanges to avoid token overflow.

    Returns:
        A coaching response string.  Returns a polite fallback on error.
    """
    try:
        from openai import OpenAI
    except ImportError:
        logger.error("chat_agent: openai package not installed")
        return "I'm not able to answer questions right now — the coaching service is unavailable."

    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        return "The AI coach is not configured — please contact support."

    context = _build_context(analysis_pk, user_id)

    system_prompt = (
        "You are an expert PGA golf swing coach with 20 years of tour-level experience. "
        "You are having a follow-up conversation with a player who just had their swing analysed. "
        "Always refer to their specific metrics and data when answering. "
        "Be encouraging but honest. Keep answers under 120 words. "
        "Do not make up numbers — only use the data provided."
    )

    messages = [{"role": "system", "content": system_prompt}]

    # Inject swing data as the opening exchange so history can reference it
    if context:
        messages.append({"role": "user", "content": f"Here is my swing data:\n{context}"})
        messages.append({"role": "assistant", "content": "Got it — I've reviewed your swing data. What would you like to know?"})

    # Append prior conversation (cap at last 10 turns to stay within token budget)
    if history:
        for msg in history[-10:]:
            role = msg.get("role", "")
            content = (msg.get("content") or "").strip()
            if role in ("user", "assistant") and content:
                messages.append({"role": role, "content": content})

    messages.append({"role": "user", "content": question})

    try:
        client = OpenAI(api_key=api_key)
        response = client.chat.completions.create(
            model=os.environ.get("OPENAI_COACH_MODEL", _DEFAULT_MODEL),
            messages=messages,
            temperature=0.5,
            max_tokens=_MAX_RESPONSE_TOKENS,
        )
        return response.choices[0].message.content.strip()
    except Exception as exc:
        logger.error("chat_agent: OpenAI call failed: %s", exc)
        return "I couldn't process your question right now. Please try again in a moment."
