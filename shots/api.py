import os
import logging
import requests

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.views.decorators.http import require_GET
import difflib
import json

logger = logging.getLogger(__name__)

# Small curated fallback list of popular courses to help with common misspellings
# This is used only when the external Golf Course API returns no candidates.
FALLBACK_COURSES = [
    "Pebble Beach Golf Links",
    "Pebble Beach",
    "Augusta National Golf Club",
    "St Andrews Old Course",
    "Pinehurst No. 2",
    "Royal Melbourne",
    "Winged Foot Golf Club",
    "Shinnecock Hills Golf Club",
    "Oakmont Country Club",
    "Merion Golf Club",
    "Ballybunion Golf Club",
    "Muirfield",
    "Royal County Down",
    "Cypress Point Club",
    "Torrey Pines",
    "Bethpage Black",
    "TPC Sawgrass",
    "Royal St George's",
    "Carnoustie Golf Links",
    "Kiawah Island (Ocean Course)",
    "Whistling Straits",
    "Royal Portrush",
    "Los Angeles Country Club",
    "Valderrama",
    "Royal Birkdale",
]


@login_required
@require_GET
def golf_course_search(request):
    """Search for a golf course by name using the external Golf Course API.

    Query params:
      - course: the course name to search for

    Returns:
      - JSON response from the golf course API, or an error JSON with appropriate status code
    """
    course_name = request.GET.get('course')
    if not course_name:
        return JsonResponse({'error': 'Missing "course" query parameter.'}, status=400)

    api_key = os.environ.get('GOLF_COURSE_API_KEY')
    if not api_key:
        # Try to use a hard-coded override (useful for local testing). This mirrors
        # the same local-testing constant available in `shots.views`.
        try:
            from .views import GOLF_COURSE_API_KEY_HARDCODED
            if GOLF_COURSE_API_KEY_HARDCODED:
                api_key = GOLF_COURSE_API_KEY_HARDCODED
        except Exception:
            # ignore import errors and fall through to error response below
            pass

    if not api_key:
        logger.error('GOLF_COURSE_API_KEY not set in environment or hardcoded override')
        return JsonResponse({'error': 'Server misconfiguration: API key not set.'}, status=500)

    url = 'https://api.golfcourseapi.com/v1/search'
    params = {'search_query': course_name}
    headers = {'Authorization': f'Key {api_key}'}

    try:
        resp = requests.get(url, params=params, headers=headers, timeout=8)
    except requests.RequestException as e:
        logger.exception('Error while calling Golf Course API')
        return JsonResponse({'error': 'Failed to contact Golf Course API', 'detail': str(e)}, status=502)

    # Propagate non-200 responses with a helpful message
    if resp.status_code != 200:
        logger.error('Golf Course API returned non-200: %s %s', resp.status_code, resp.text)
        return JsonResponse({'error': 'Golf Course API error', 'status_code': resp.status_code, 'detail': resp.text}, status=502)

    try:
        data = resp.json()
    except ValueError:
        logger.error('Golf Course API returned invalid JSON')
        return JsonResponse({'error': 'Golf Course API returned invalid JSON'}, status=502)

    # Filter to only the fields the client needs
    courses_raw = data if isinstance(data, list) else data.get('courses', data.get('data', {}).get('courses', []))
    safe_courses = []
    if isinstance(courses_raw, list):
        for c in courses_raw:
            if isinstance(c, dict):
                safe_courses.append({
                    'id': c.get('id') or c.get('course_id') or c.get('courseId'),
                    'name': c.get('name') or c.get('course_name') or c.get('title'),
                    'location': c.get('location') or c.get('city'),
                    'tees': c.get('tees'),
                })
    return JsonResponse({'data': safe_courses})


@login_required
@require_GET
def course_suggestions(request):
    """Return scored course-name suggestions for autocomplete.

    Query params:
      - q: partial course name

    Response:
      - JSON list of suggestions with {name, score, id?, raw}
    """
    q = request.GET.get('q') or request.GET.get('course')
    if not q:
        return JsonResponse({'error': 'Missing "q" query parameter.'}, status=400)

    api_key = os.environ.get('GOLF_COURSE_API_KEY')
    if not api_key:
        try:
            from .views import GOLF_COURSE_API_KEY_HARDCODED
            if GOLF_COURSE_API_KEY_HARDCODED:
                api_key = GOLF_COURSE_API_KEY_HARDCODED
        except Exception:
            pass

    if not api_key:
        logger.error('GOLF_COURSE_API_KEY not set in environment or hardcoded override')
        return JsonResponse({'error': 'Server misconfiguration: API key not set.'}, status=500)

    url = 'https://api.golfcourseapi.com/v1/search'
    params = {'search_query': q}
    headers = {'Authorization': f'Key {api_key}'}

    try:
        resp = requests.get(url, params=params, headers=headers, timeout=8)
        resp.raise_for_status()
    except requests.RequestException as e:
        logger.exception('Error while calling Golf Course API for suggestions')
        return JsonResponse({'error': 'Failed to contact Golf Course API', 'detail': str(e)}, status=502)

    try:
        data = resp.json()
    except ValueError:
        logger.exception('Invalid JSON from Golf Course API')
        return JsonResponse({'error': 'Golf Course API returned invalid JSON'}, status=502)

    # Extract candidate list. The external API may put courses under various keys.
    candidates = []
    if isinstance(data, dict):
        # common shapes: {'courses': [...]}, {'data': {'courses': [...]}} or top-level list
        if 'courses' in data and isinstance(data['courses'], list):
            candidates = data['courses']
        elif 'data' in data and isinstance(data['data'], dict) and 'courses' in data['data']:
            candidates = data['data']['courses']
        else:
            # attempt to find the first list in the payload
            for v in data.values():
                if isinstance(v, list):
                    candidates = v
                    break
    elif isinstance(data, list):
        candidates = data

    # If the external API returned no candidates, fall back to our small curated list
    if not candidates:
        # Use the fallback as simple strings — scoring logic supports strings
        candidates = list(FALLBACK_COURSES)

    # Scoring: try to use rapidfuzz if available for better results, else difflib fallback
    try:
        from rapidfuzz import fuzz
        def score_fn(a, b):
            try:
                return int(fuzz.token_sort_ratio(a or '', b or ''))
            except Exception:
                return int(difflib.SequenceMatcher(None, (a or '').lower(), (b or '').lower()).ratio() * 100)
    except Exception:
        def score_fn(a, b):
            return int(difflib.SequenceMatcher(None, (a or '').lower(), (b or '').lower()).ratio() * 100)

    suggestions = []
    q_norm = q.strip()
    for item in candidates:
        # item could be a string or dict
        if isinstance(item, str):
            name = item
            meta = None
            cid = None
        elif isinstance(item, dict):
            # prefer fields that commonly contain course name
            name = item.get('name') or item.get('course_name') or item.get('title') or None
            meta = item
            cid = item.get('id') or item.get('course_id') or item.get('courseId')
            # if name missing, attempt to construct
            if not name:
                # pick first string-like value
                for v in item.values():
                    if isinstance(v, str) and len(v) > 2:
                        name = v
                        break
            if not name:
                continue
        else:
            continue

        s = score_fn(q_norm, name)
        suggestions.append({'name': name, 'score': s, 'id': cid, 'raw': meta})

    # Sort by score desc, limit to top 10
    suggestions.sort(key=lambda x: x['score'], reverse=True)
    top = suggestions[:10]

    return JsonResponse({'query': q, 'suggestions': top})
