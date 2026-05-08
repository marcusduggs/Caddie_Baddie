"""
AI Golf Coach agent.

Sends structured swing metrics to the OpenAI chat completions API and returns
parsed coaching feedback.  Requires OPENAI_API_KEY to be set in the environment.

Usage:
    from shots.ai.coach_agent import analyze_swing
    result = analyze_swing(metrics, club="Driver", distance_yards=250)
"""

from __future__ import annotations

import json
import logging
import os
from typing import Dict, Optional

from .prompt_builder import build_coaching_prompt, build_system_prompt

logger = logging.getLogger(__name__)

# Model to use; can be overridden via OPENAI_COACH_MODEL env var.
_DEFAULT_MODEL = "gpt-4o-mini"

# Fallback response returned when the API call fails so that the background
# task can still complete without crashing the entire pipeline.
_FALLBACK_RESPONSE: Dict[str, str] = {
    "main_fault": "Unable to generate AI feedback at this time.",
    "strength": "N/A",
    "drill": "N/A",
    "swing_thought": "Keep practising with consistent fundamentals.",
}


def _get_client():
    """Instantiate an OpenAI client.  Raises EnvironmentError if key missing."""
    try:
        from openai import OpenAI  # openai >= 1.0.0
    except ImportError as exc:
        raise ImportError(
            "openai package is not installed. Run: pip install openai"
        ) from exc

    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise EnvironmentError(
            "OPENAI_API_KEY environment variable is not set. "
            "Add it to your server environment or .env file."
        )
    return OpenAI(api_key=api_key)


def _parse_coach_response(content: str) -> Dict[str, str]:
    """Extract and validate the JSON coaching response from the model output.

    The model is instructed to return raw JSON, but may occasionally wrap it
    in a markdown code fence.  This function strips common wrappers before
    parsing.
    """
    text = content.strip()
    # Strip markdown code fences if present
    if text.startswith("```"):
        lines = text.splitlines()
        # Drop first line (```json or ```) and last line (```)
        text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        logger.warning("coach_agent: failed to parse JSON response: %s — raw: %.200s", exc, content)
        return _FALLBACK_RESPONSE.copy()

    required_keys = {"main_fault", "strength", "drill", "swing_thought"}
    if not required_keys.issubset(parsed.keys()):
        missing = required_keys - parsed.keys()
        logger.warning("coach_agent: response missing keys %s", missing)
        # Fill missing keys with fallback values
        for k in missing:
            parsed[k] = _FALLBACK_RESPONSE.get(k, "N/A")

    # Coerce all values to strings and trim length
    return {k: str(parsed.get(k, "N/A"))[:500] for k in required_keys}


def analyze_swing(
    metrics: Dict,
    club: str = "unknown",
    distance_yards: Optional[float] = None,
) -> Dict[str, str]:
    """Send swing metrics to OpenAI and return structured coaching feedback.

    Args:
        metrics:        Output dict from metrics_engine.extract_swing_metrics().
        club:           Club used (e.g. 'Driver', '7-iron').
        distance_yards: Reported shot distance in yards (adds context to prompt).

    Returns:
        Dict with keys: main_fault, strength, drill, swing_thought.
        On API errors, returns a safe fallback dict rather than raising.
    """
    # If metrics are essentially empty, return fallback without calling API.
    if metrics.get("frame_count", 0) == 0:
        logger.warning("coach_agent: no pose frames detected; skipping AI analysis")
        return {
            "main_fault": "Pose detection produced no data for this video — ensure the golfer is fully visible in the frame.",
            "strength": "N/A",
            "drill": "Ensure the camera captures a full side-on or face-on view of the swing.",
            "swing_thought": "Set up so the full body is visible throughout the swing.",
        }

    try:
        client = _get_client()
    except (ImportError, EnvironmentError) as exc:
        logger.error("coach_agent: cannot initialise OpenAI client: %s", exc)
        return _FALLBACK_RESPONSE.copy()

    model = os.environ.get("OPENAI_COACH_MODEL", _DEFAULT_MODEL)
    system_prompt = build_system_prompt()
    user_prompt = build_coaching_prompt(metrics, club=club, distance_yards=distance_yards)

    logger.info(
        "coach_agent: calling OpenAI model=%s for club=%s distance=%s",
        model, club, distance_yards,
    )

    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.4,       # low temperature for consistent, factual coaching
            max_tokens=400,
            response_format={"type": "json_object"},  # enforce JSON mode (gpt-4o family)
        )
    except Exception as exc:
        # Broad except: network errors, quota exceeded, invalid model, etc.
        logger.error("coach_agent: OpenAI API call failed: %s", exc, exc_info=True)
        return _FALLBACK_RESPONSE.copy()

    raw_content = response.choices[0].message.content or ""
    logger.debug("coach_agent: raw response: %.300s", raw_content)

    result = _parse_coach_response(raw_content)
    logger.info("coach_agent: coaching feedback generated successfully")
    return result
