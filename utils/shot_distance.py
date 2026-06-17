"""Utilities for calculating shot distances using GPS coordinates.

This module provides a haversine implementation and higher-level helpers to
compute distances between shots, tees, and pins. All calculations are server
side and return distances in yards.

Functions:
- haversine_distance(lat1, lng1, lat2, lng2): return distance in meters
- distance_yards(lat1, lng1, lat2, lng2): return distance in yards
- compute_shot_distance(shot_distance_obj): compute and return yardage for a ShotDistance

Comment: This module is intentionally isolated and does not modify models.
"""
import math
from typing import Optional

# Earth's radius in meters
_EARTH_RADIUS_M = 6371000.0


def haversine_distance(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Calculate the great-circle distance between two points.

    Inputs are decimal degrees. Returns distance in meters.
    Handles None inputs by returning 0.0.
    """
    if lat1 is None or lng1 is None or lat2 is None or lng2 is None:
        return 0.0
    # convert degrees to radians
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lng2 - lng1)

    a = math.sin(dphi / 2.0) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2.0) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    return _EARTH_RADIUS_M * c


def distance_yards(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Return distance in yards between two lat/lng points.

    Uses haversine_distance under the hood.
    """
    meters = haversine_distance(lat1, lng1, lat2, lng2)
    yards = meters * 1.0936133
    return yards


def compute_shot_distance(shot_distance_obj) -> Optional[float]:
    """Compute yardage for a ShotDistance instance.

    Returns computed yards as float or None when insufficient data.
    """
    try:
        if shot_distance_obj.origin_lat is None or shot_distance_obj.origin_lng is None:
            return None
        if shot_distance_obj.landing_lat is None or shot_distance_obj.landing_lng is None:
            return None
        yards = distance_yards(
            shot_distance_obj.origin_lat,
            shot_distance_obj.origin_lng,
            shot_distance_obj.landing_lat,
            shot_distance_obj.landing_lng,
        )
        try:
            # Round to two decimal places for consistent UI display
            return round(float(yards), 2)
        except Exception:
            return yards
    except Exception:
        # Fail silently; caller may decide how to surface errors.
        return None
