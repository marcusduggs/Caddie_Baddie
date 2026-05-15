from django.contrib.auth.decorators import login_required

@login_required
def upload_shot(request):
    if request.method == "POST":
        form = ShotForm(request.POST, request.FILES)
        if form.is_valid():
            shot = form.save(commit=False)
            shot.user = request.user
            shot.save()
            return redirect("shots:my_shots")
    else:
        form = ShotForm()
    return render(request, "upload_shot.html", {"form": form})
from django.contrib.auth.decorators import login_required

from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.contrib import messages
from .models import Shot
from django.db.models import Count
from .forms import ShotForm
from . import utils
from . import overlay_map
import os
from django.conf import settings
from .forms import ShotAnalysisForm
from .models import ShotAnalysis
from .models import CourseMetadata
from .models import ShotRound
from django.core.files import File
import shutil
from django.utils.text import slugify
import subprocess
import uuid
from utils.overlay import process_video_with_overlay, FFMPEG_PATH
from .video_processing import render_pose_wireframe
import requests
from django_q.tasks import async_task
import urllib.parse
import logging
import re
import json


logger = logging.getLogger(__name__)


def _tee_matches(preferred, name):
    """Return True if the preferred tee matches the tee name based on token or substring."""
    try:
        if not preferred or not name:
            return False
        pn = preferred.strip().lower()
        tn_tokens = [t for t in re.split(r"[^a-z0-9]+", (name or '').lower()) if t]
        if pn in tn_tokens:
            return True
        return pn in (name or '').lower()
    except Exception:
        return False


def _normalize_tee_names(names):
    """Normalize and deduplicate a list of tee names.

    - Strips whitespace, collapses internal whitespace, preserves original casing of
      the first-seen form, and deduplicates case-insensitively while preserving order.
    """
    out = []
    seen = set()
    if not names:
        return out
    for n in names:
        try:
            if not n:
                continue
            s = re.sub(r"\s+", ' ', str(n).strip())
            key = s.lower()
            if key not in seen:
                seen.add(key)
                out.append(s)
        except Exception:
            continue
    return out


def probe_video_creation_time(path):
    """Try to extract creation_time metadata from a video using ffprobe.
    Returns a naive datetime in UTC if found, otherwise None.
    Falls back to file mtime externally if ffprobe not available or no metadata.
    """
    ffprobe_dt = None
    try:
        # Call ffprobe to get format tags (must use ffprobe binary, not ffmpeg)
        import shutil as _shutil
        ffprobe_bin = _shutil.which('ffprobe') or 'ffprobe'
        cmd = [ffprobe_bin, '-v', 'quiet', '-print_format', 'json', '-show_format', path]
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
        if proc.returncode == 0 and proc.stdout:
            import json
            payload = json.loads(proc.stdout.decode('utf-8'))
            fmt = payload.get('format', {})
            tags = fmt.get('tags', {})
            # Common tag names: creation_time, CreationTime
            for key in ('creation_time', 'CreationTime'):
                if key in tags and tags[key]:
                    try:
                        from dateutil import parser as dateparser
                        dt = dateparser.parse(tags[key])
                        # Convert to timezone-aware UTC datetime
                        import datetime
                        if dt.tzinfo:
                            dt = dt.astimezone(datetime.timezone.utc)
                        else:
                            # assume naive times are in UTC - attach UTC tzinfo
                            dt = dt.replace(tzinfo=datetime.timezone.utc)
                        ffprobe_dt = dt
                        break
                    except Exception:
                        pass
    except Exception:
        pass
    # File mtime fallback (timezone-aware UTC)
    try:
        import datetime
        mtime_ts = os.path.getmtime(path)
        mtime_dt = datetime.datetime.fromtimestamp(mtime_ts, tz=datetime.timezone.utc)
    except Exception:
        mtime_dt = None

    # Prefer filesystem mtime when it differs significantly from ffprobe tag
    try:
        if ffprobe_dt and mtime_dt:
            # If difference is more than 60 seconds, prefer mtime (Finder/filesystem)
            diff = abs((mtime_dt - ffprobe_dt).total_seconds())
            if diff > 60:
                return mtime_dt
            else:
                return ffprobe_dt
        # If only one available, return it
        if mtime_dt:
            return mtime_dt
        if ffprobe_dt:
            return ffprobe_dt
    except Exception:
        pass

    return None

# Hard-coded Golf Course API key override for local testing.
# WARNING: Hard-coding secrets in source is insecure. Replace the placeholder
# string below with your real key if you understand the risks, or set the
# environment variable GOLF_COURSE_API_KEY instead.
# To disable the hard-coded key, set this to None.
GOLF_COURSE_API_KEY_HARDCODED = 'EFJRDJOWXMKRBIKSQIDZSFLOCY'  # local testing key provided by user


from .tasks import process_video_background  # noqa: F401 — kept for any external callers


@login_required
def delete_round_hole(request, round_pk, hole):
    """Delete all ShotAnalysis records for a given round and hole.

    This deletes associated media files (input, processed, overlay, thumbnail) and
    removes the database records. Only the user who owns the round (or staff) may delete.
    """
    from django.contrib import messages
    from django.shortcuts import redirect

    sr = get_object_or_404(ShotRound, pk=round_pk)
    # Basic permission: only the round owner can delete
    if sr.user != request.user and not request.user.is_staff:
        messages.error(request, 'You do not have permission to delete this hole.')
        return redirect('shots:round_holes', round_pk=round_pk)

    # Find analyses for this round/hole
    analyses = ShotAnalysis.objects.filter(round=sr, hole_number=hole)
    deleted = 0
    for a in analyses:
        # delete files if present
        try:
            for f in ('input_video', 'processed_video', 'overlayed_video', 'thumbnail'):
                ff = getattr(a, f, None)
                if ff and ff.name:
                    try:
                        path = ff.path
                        if os.path.exists(path):
                            os.remove(path)
                    except Exception:
                        # best-effort file removal
                        pass
        except Exception:
            pass
        a.delete()
        deleted += 1

    messages.success(request, f'Deleted {deleted} shot(s) for hole {hole}.')
    return redirect('shots:round_holes', round_pk=round_pk)


def home(request):
    shots = []
    count = 0
    avg_distance = None

    if request.user.is_authenticated:
        shots = Shot.objects.filter(user=request.user).order_by('-created_at')[:100]
        count = shots.count()
        if count:
            try:
                avg_distance = sum(s.distance for s in shots) / count
            except Exception:
                avg_distance = None

        # Redirect to courses when user clicks "View My Courses" from the home page
        try:
            from .models import Course
            if request.GET.get('from_home') == '1':
                has_courses = Course.objects.filter(user=request.user).exists()
                if has_courses:
                    return redirect('shots:courses_list')
                else:
                    from django.contrib import messages
                    messages.info(request, 'You have no courses yet — add a course to get started.')
                    return redirect('shots:add_course')
        except Exception:
            pass

    context = {
        'shots': shots,
        'count': count,
        'avg_distance': avg_distance,
    }
    return render(request, 'shots/home.html', context)


@login_required
def create_shot(request):
    if request.method == 'POST':
        form = ShotForm(request.POST, request.FILES)
        if form.is_valid():
            shot = form.save(commit=False)
            shot.user = request.user
            # If a video was uploaded, try to extract coords
            uploaded = request.FILES.get('video')
            if uploaded:
                tmp_path = None
                try:
                    tmp_path = utils.save_uploaded_tempfile(uploaded)
                    coords = utils.extract_coords_from_video(tmp_path)
                    if coords:
                        lon, lat = coords
                        shot.longitude = lon
                        shot.latitude = lat
                finally:
                    try:
                        if tmp_path and os.path.exists(tmp_path):
                            os.remove(tmp_path)
                    except Exception:
                        pass

            shot.save()
            # Redirect to the shots list page
            return redirect('shots:shot_list')
    else:
        form = ShotForm()
    return render(request, 'shots/shot_form.html', {'form': form})


@login_required
def analyze_upload(request):
    """Handle uploading a video, run overlay processing, and show the result."""
    if request.method == 'POST':
        # Build dynamic tee choices from the provided course name so the ChoiceField
        # accepts API-returned tee names (e.g. 'Silver'). This prevents validation
        # errors when the client populated the select from the API.
        course_candidate = request.POST.get('course') or request.GET.get('course')
        prefetched_tee_names = []
        try:
            api_key = GOLF_COURSE_API_KEY_HARDCODED or os.environ.get('GOLF_COURSE_API_KEY')
            if api_key and course_candidate:
                api_url = 'https://api.golfcourseapi.com/v1/search'
                resp = requests.get(api_url, params={'search_query': course_candidate}, headers={'Authorization': f'Key {api_key}'}, timeout=6)
                if resp.status_code == 200:
                    payload = resp.json()
                    data = payload.get('data') if isinstance(payload, dict) and 'data' in payload else payload
                    courses = data.get('courses') if isinstance(data, dict) and 'courses' in data else (data if isinstance(data, list) else [])
                    if isinstance(courses, list):
                        for c in courses:
                            tees = c.get('tees') if isinstance(c, dict) else None
                            if isinstance(tees, dict):
                                for arr in tees.values():
                                    if isinstance(arr, list):
                                        for t in arr:
                                            try:
                                                name = t.get('tee_name') or t.get('teeName') or t.get('name')
                                                if name:
                                                    prefetched_tee_names.append(name)
                                            except Exception:
                                                pass
        except Exception:
            prefetched_tee_names = []

        # Normalize prefetched tee names and combine with static choices while preserving order
        prefetched_tee_names = _normalize_tee_names(prefetched_tee_names)
        static_choices = getattr(ShotAnalysisForm, 'TEE_CHOICES', []) or []
        seen = set()
        combined = [('', 'Any')]
        for n in prefetched_tee_names:
            if n and n.lower() not in seen:
                seen.add(n.lower())
                combined.append((n, n))
        # Ensure the posted selected_tee is accepted even if API parsing missed it
        posted_selected = request.POST.get('selected_tee')
        if posted_selected and posted_selected not in seen:
            try:
                seen.add(posted_selected)
                combined.insert(1, (posted_selected, posted_selected))
            except Exception:
                pass
        for val, label in static_choices:
            if val and val.lower() not in seen:
                seen.add(val.lower())
                combined.append((val, label))

        # Make a mutable copy of POST so we can inject a selected_tee when it's missing
        data = request.POST.copy()
        # If selected_tee is missing but round_id is provided, inherit the round's selected_tee
        posted_selected = data.get('selected_tee', '').strip()
        if not posted_selected and data.get('round_id'):
            try:
                from .models import ShotRound
                rr = ShotRound.objects.filter(pk=data.get('round_id')).first()
                if rr and getattr(rr, 'selected_tee', None):
                    data['selected_tee'] = rr.selected_tee
            except Exception:
                # best-effort; do not crash upload on lookup error
                pass

        # Bind form with the possibly modified data copy
        form = ShotAnalysisForm(data, request.FILES)

        # Inject dynamic choices into the bound form before validation.
        # Do NOT delete the field from the bound form (that causes the validation
        # machinery to ignore our injected choices and fail on unexpected labels).
        try:
            # If the bound form somehow lacks the field (edge cases), recreate it
            if 'selected_tee' not in form.fields:
                from django import forms as django_forms
                form.fields['selected_tee'] = django_forms.ChoiceField(choices=combined, required=False, label='Preferred tee')
            else:
                form.fields['selected_tee'].choices = combined

            # Double-check posted value is allowed; if not, append it so validation accepts it
            if posted_selected:
                vals = [str(c[0]).lower() for c in form.fields['selected_tee'].choices]
                if str(posted_selected).lower() not in vals:
                    form.fields['selected_tee'].choices = list(form.fields['selected_tee'].choices) + [(posted_selected, posted_selected)]

            # Make the field optional at form-level to avoid browser/disabled select edge-cases
            try:
                form.fields['selected_tee'].required = False
            except Exception:
                pass

            # Diagnostic logging to help trace invalid-choice issues
            try:
                logger.info(f"analyze_upload diagnostic: posted_selected={posted_selected!r}, combined_choices={combined[:20]}, bound_field_choices={form.fields['selected_tee'].choices[:20]}, posted_keys={list(data.keys())}")
            except Exception:
                pass
        except Exception:
            pass
        if form.is_valid():
            # Save the form to create the analysis object
            analysis = form.save(commit=False)
            # Persist course name from the posted data so course-scoped views can find this analysis
            try:
                posted_course = (data.get('course') or '').strip()
                if posted_course:
                    analysis.course_name = posted_course
            except Exception:
                pass
            # Ensure the analysis has an owner user to satisfy the NOT NULL FK
            try:
                analysis.user = request.user
            except Exception:
                # As a last-resort fallback, leave assignment to the DB layer (will raise)
                pass
            # Attach or create a round when requested so uploads are grouped correctly.
            try:
                from .models import ShotRound
                # Prefer explicit round_id when provided
                posted_round_id = data.get('round_id') or ''
                if posted_round_id:
                    try:
                        rr = ShotRound.objects.filter(pk=int(posted_round_id), user=request.user).first()
                        if rr:
                            analysis.round = rr
                            # If a round was attached, inherit its course_name so course-scoped views can find the analysis
                            try:
                                if getattr(rr, 'course_name', None):
                                    analysis.course_name = rr.course_name
                            except Exception:
                                pass
                    except Exception:
                        pass
                else:
                    # If the client provided a new round name, create the ShotRound and attach it
                    new_round_name = (data.get('new_round_name') or '').strip()
                    if new_round_name:
                        try:
                            course_name_val = (data.get('course') or '').strip() or None
                            rr = ShotRound.objects.create(user=request.user, name=new_round_name, course_name=course_name_val)
                            analysis.round = rr
                            # Also set course_name on analysis when creating a new round
                            try:
                                if course_name_val:
                                    analysis.course_name = course_name_val
                            except Exception:
                                pass
                        except Exception:
                            pass
            except Exception:
                # best-effort; continue even if round creation fails
                pass
            # Persist selected_tee from the POST copy (either posted or inherited from round)
            final_selected = data.get('selected_tee', '').strip()
            if final_selected:
                analysis.selected_tee = final_selected
            # Attach hole number when provided so the analysis appears in hole listings
            try:
                hole_val = data.get('hole') or ''
                if hole_val:
                    try:
                        analysis.hole_number = int(hole_val)
                    except Exception:
                        pass  # leave hole_number unset rather than assigning a non-int
            except Exception:
                pass
            # Defensive: ensure distance is set to a valid float to satisfy the
            # database NOT NULL constraint. Analyzer may overwrite this later.
            try:
                if getattr(analysis, 'distance', None) is None:
                    analysis.distance = 0.0
            except Exception:
                analysis.distance = 0.0
            
            # Support multiple uploaded files: create one ShotAnalysis per file and
            # schedule background processing so the request returns quickly.
            uploaded_files = request.FILES.getlist('input_video')
            if not uploaded_files:
                messages.error(request, 'No video file uploaded.')
                return render(request, 'shots/analyze_form.html', {'form': form})

            created_pks = []
            # Resolve the ShotRound to attach to each analysis once (avoid per-file lookups)
            rr = None
            try:
                rr = getattr(analysis, 'round', None)
            except Exception:
                rr = None

            # Save each uploaded file immediately so we can probe the saved file on disk
            # for creation time. This avoids consuming the UploadedFile iterator via
            # temporary copies and ensures we probe the final stored file.
            # Resolve club/distance from form now so per-file loop can reference them
            club_val = None
            distance_val = None
            try:
                club_val = form.cleaned_data.get('club')
            except Exception:
                club_val = None
            try:
                distance_val = form.cleaned_data.get('distance')
            except Exception:
                distance_val = None

            saved_items = []
            for original_index, uf in enumerate(uploaded_files):
                try:
                    a_temp = ShotAnalysis()
                    try: a_temp.user = request.user
                    except Exception: pass
                    # minimal defaults so save() succeeds
                    try:
                        a_temp.distance = float(distance_val) if distance_val is not None else 0.0
                    except Exception:
                        a_temp.distance = 0.0
                    try:
                        if final_selected:
                            a_temp.selected_tee = final_selected
                    except Exception:
                        pass
                    # Persist course name on each per-file analysis record as well
                    try:
                        posted_course = (data.get('course') or '').strip()
                        if posted_course:
                            a_temp.course_name = posted_course
                    except Exception:
                        pass
                    try:
                        hole_val = data.get('hole') or ''
                        if hole_val:
                            try:
                                a_temp.hole_number = int(hole_val)
                            except Exception:
                                pass  # leave hole_number unset rather than assigning a non-int
                    except Exception:
                        pass
                    # Attach round if previously resolved
                    try:
                        if getattr(analysis, 'round', None):
                            a_temp.round = analysis.round
                        elif rr:
                            a_temp.round = rr
                    except Exception:
                        pass

                    # If the per-file analysis has a round attached but no explicit course was posted,
                    # inherit the round's course_name so course-scoped pages immediately pick up the shot.
                    try:
                        if getattr(a_temp, 'round', None) and not getattr(a_temp, 'course_name', None):
                            try:
                                if getattr(a_temp.round, 'course_name', None):
                                    a_temp.course_name = a_temp.round.course_name
                            except Exception:
                                pass
                    except Exception:
                        pass

                    a_temp.status = 'uploading'
                    a_temp.save()

                    # Save uploaded file to the model's FileField (writes to MEDIA_ROOT)
                    try:
                        a_temp.input_video.save(uf.name, uf, save=True)
                    except Exception:
                        # In case the UploadedFile is exhausted, write contents from temp
                        try:
                            tmp = utils.save_uploaded_tempfile(uf)
                            with open(tmp, 'rb') as fh:
                                a_temp.input_video.save(uf.name, File(fh), save=True)
                        except Exception:
                            pass

                    # Probe the saved file for creation time; fallback to file mtime or model created_at
                    probe_ts = None
                    try:
                        probe_dt = probe_video_creation_time(a_temp.input_video.path)
                        if probe_dt is not None:
                            probe_ts = probe_dt.timestamp()
                    except Exception:
                        probe_ts = None
                    if probe_ts is None:
                        try:
                            probe_ts = float(os.path.getmtime(a_temp.input_video.path))
                        except Exception:
                            probe_ts = None
                    # Final fallback: use model created_at timestamp
                    if probe_ts is None:
                        try:
                            probe_ts = a_temp.created_at.timestamp()
                        except Exception:
                            probe_ts = None

                    # Persist probe_creation_time (use probe_ts when available)
                    try:
                        if probe_ts is not None:
                            import datetime
                            a_temp.probe_creation_time = datetime.datetime.fromtimestamp(float(probe_ts), tz=datetime.timezone.utc)
                            a_temp.save()
                    except Exception:
                        pass

                    # Synchronously attempt a lightweight GPS extraction so the hole map
                    # can show a marker immediately after upload (without waiting for
                    # background processing). This is best-effort and must not block.
                    try:
                        coords = None
                        try:
                            coords = utils.extract_coords_from_video(a_temp.input_video.path)
                        except Exception:
                            coords = None
                        if coords:
                            lon, lat = coords
                            try:
                                from .models import ShotDistance
                                ShotDistance.objects.create(shot=a_temp, origin_lat=float(lat), origin_lng=float(lon), hole_number=getattr(a_temp, 'hole_number', None))
                            except Exception:
                                logger.exception('Failed to create synchronous ShotDistance for analysis %s', a_temp.pk)
                    except Exception:
                        pass

                    saved_items.append({'analysis': a_temp, 'probe_ts': probe_ts, 'original_index': original_index})
                except Exception:
                    logger.exception('Failed to save uploaded file to model')

            # Determine ordering using posted stroke_number_{original_index} values when present.
            try:
                # Build list of posted stroke numbers
                posted_numbers = {}
                for it in saved_items:
                    oi = it.get('original_index')
                    try:
                        val = data.get(f'stroke_number_{oi}')
                        if val is not None and str(val).strip() != '':
                            posted_numbers[oi] = int(val)
                    except Exception:
                        continue
                if posted_numbers:
                    # sort by posted stroke number (ascending)
                    saved_items.sort(key=lambda it: posted_numbers.get(it.get('original_index'), 999999))
                else:
                    # Fallback: sort saved items by probe timestamp oldest -> newest (None goes last)
                    saved_items.sort(key=lambda x: (x['probe_ts'] is None, x['probe_ts'] if x['probe_ts'] is not None else 0))
                    # For items with missing probe_ts, deterministically order them by created_at
                    try:
                        first_none = next((i for i, it in enumerate(saved_items) if it.get('probe_ts') is None), None)
                        if first_none is not None:
                            tail = saved_items[first_none:]
                            tail.sort(key=lambda it: getattr(it.get('analysis'), 'created_at', None) or 0)
                            saved_items[first_none:] = tail
                    except Exception:
                        pass
            except Exception:
                # If any error during ordering, fall back to current order
                pass

            overlay_requested = bool(request.POST.get('overlay_pose'))

            # Finalize saved items: assign stroke numbers and schedule processing
            total_files = len(saved_items)
            for idx, item in enumerate(saved_items, start=1):
                try:
                    a_saved = item.get('analysis')
                    probe_ts = item.get('probe_ts')

                    # assign stroke number (1 = oldest)
                    try:
                        a_saved.stroke_number = int(idx)
                    except Exception:
                        pass

                    # persist probe_creation_time when available
                    try:
                        if probe_ts:
                            import datetime
                            a_saved.probe_creation_time = datetime.datetime.fromtimestamp(float(probe_ts), tz=datetime.timezone.utc)
                    except Exception:
                        pass

                    # ensure status is uploading so background worker picks it up
                    try:
                        a_saved.status = 'uploading'
                        a_saved.overlay_requested = overlay_requested
                        # Persist metadata (course_name/hole_number/stroke_number/status) so list/map views see the shot immediately
                        try:
                            a_saved.save()
                        except Exception:
                            # best-effort; continue even if save fails
                            pass
                    except Exception:
                        pass

                    # Schedule background processing using the saved file path
                    try:
                        base_name = os.path.splitext(os.path.basename(a_saved.input_video.name))[0]
                        output_filename = f"{base_name}_processed.mp4"
                        _out_root = str(settings.MEDIA_ROOT) if settings.MEDIA_ROOT else __import__('tempfile').gettempdir()
                        output_path = os.path.join(_out_root, 'output', output_filename)
                        try:
                            _input_path = a_saved.input_video.path
                        except (NotImplementedError, ValueError):
                            _input_path = a_saved.input_video.url
                        async_task('shots.tasks.process_video_background', a_saved.pk, _input_path, output_path, None)
                    except Exception:
                        logger.exception('Failed to start background processing for analysis %s', getattr(a_saved, 'pk', None))

                    created_pks.append(getattr(a_saved, 'pk', None))
                    # Ensure there is at least one ShotDistance for this analysis; if missing try to extract and persist
                    try:
                        from .models import ShotDistance
                        has_sd = ShotDistance.objects.filter(shot=a_saved).exists()
                        if not has_sd:
                            try:
                                coords = None
                                try:
                                    coords = utils.extract_coords_from_video(a_saved.input_video.path)
                                except Exception:
                                    coords = None
                                if coords:
                                    lonx, latx = coords
                                    ShotDistance.objects.create(shot=a_saved, origin_lat=float(latx), origin_lng=float(lonx), hole_number=getattr(a_saved, 'hole_number', None))
                            except Exception:
                                logger.exception('Failed to persist ShotDistance for analysis %s', getattr(a_saved, 'pk', None))
                    except Exception:
                        pass
                except Exception as e:
                    logger.exception('Failed to finalize saved analysis item: %s', e)

            # Redirect to the hole page for the uploaded shots (prefer round-scoped URL when possible)
            if created_pks:
                try:
                    # Determine hole number from the first created analysis
                    first_pk = created_pks[0]
                    first_analysis = ShotAnalysis.objects.filter(pk=first_pk).first()
                    if first_analysis:
                        hole_num = getattr(first_analysis, 'hole_number', None)
                        if getattr(first_analysis, 'round', None) and hole_num is not None:
                            return redirect('shots:round_hole_shots', first_analysis.round.pk, hole_num)
                        # Fallback: course-scoped hole map (resolve slug)
                        try:
                            from django.utils.text import slugify
                            course_slug = slugify(getattr(first_analysis, 'course_name', '') or '')
                            if course_slug and hole_num is not None:
                                return redirect('shots:hole_shots', course_slug=course_slug, hole=hole_num)
                        except Exception:
                            pass
                except Exception:
                    pass
                # Final fallback: go to the analysis detail if we couldn't build a hole URL
                return redirect('shots:analysis_detail', pk=created_pks[0])
            else:
                messages.error(request, 'Failed to save uploaded videos.')
                return render(request, 'shots/analyze_form.html', {'form': form})
    else:
        form = ShotAnalysisForm()
    
    # Provide existing rounds for the user so they can attach uploads to a round
    rounds = []
    try:
        from .models import ShotRound
        # Only attempt to filter by user when authenticated; AnonymousUser cannot be used in ORM filters
        if getattr(request, 'user', None) and getattr(request.user, 'is_authenticated', False):
            rounds = ShotRound.objects.filter(user=request.user).order_by('-played_at', '-created_at')[:50]
            try:
                logger.info(f"analyze_upload: found rounds for user {getattr(request.user,'pk',None)} -> {[r.pk for r in rounds]}")
            except Exception:
                logger.info("analyze_upload: found rounds (unable to list ids)")
        else:
            rounds = []
    except Exception:
        logger.exception('Error fetching rounds for analyze_upload')
        rounds = []

    # Also pass all rounds (debug) so we can inspect ownership in the UI
    all_rounds = []
    try:
        from .models import ShotRound
        all_rounds = list(ShotRound.objects.all().values('pk', 'user_id', 'name', 'played_at'))
    except Exception:
        all_rounds = []

    # Report DB path and request.user info for debugging environment mismatches
    db_path = None
    try:
        db_path = settings.DATABASES.get('default', {}).get('NAME')
    except Exception:
        db_path = None
    request_user_info = {'pk': getattr(request.user, 'pk', None), 'is_authenticated': getattr(request.user, 'is_authenticated', False), 'repr': repr(request.user)}

    # Prefill course from querystring when present (e.g., Add New Hole from rounds page)
    initial_course = request.GET.get('course') or request.POST.get('course') or None
    # If no explicit course provided, fall back to session-stored current course (if user previously viewed rounds for a course)
    if not initial_course:
        try:
            sess_name = request.session.get('current_course_name')
            if sess_name:
                initial_course = sess_name
                # Note: session-based prefills are not treated as locked by default
        except Exception:
            pass

    # Determine if we should lock the course field (fixed_course) and preselect a round
    fixed_course = False
    fixed_course_obj = None
    fixed_course_name = None
    selected_round_id = request.GET.get('round_id') or request.POST.get('round_id') or None
    if initial_course:
        # If the user has a saved Course record matching this name, prefer that object
        try:
            from .models import Course
            course_obj = Course.objects.filter(user=request.user, name=initial_course).first()
            if course_obj:
                fixed_course = True
                fixed_course_obj = course_obj
                fixed_course_name = course_obj.name
            else:
                # Still lock the course input to the provided name even if no Course record exists
                fixed_course = True
                fixed_course_name = initial_course
        except Exception:
            fixed_course = True
            fixed_course_name = initial_course

    return render(request, 'shots/analyze_form.html', {
        'form': form,
        'rounds': rounds,
        'all_rounds': all_rounds,
        'db_path': db_path,
        'request_user_info': request_user_info,
        'initial_course': initial_course,
        'fixed_course': fixed_course,
        'fixed_course_obj': fixed_course_obj,
        'fixed_course_name': fixed_course_name,
        'selected_round_id': selected_round_id,
    })


@login_required
def analysis_detail(request, pk):
    """Display the analysis detail page showing both original and processed videos."""
    analysis = get_object_or_404(ShotAnalysis, pk=pk)
    if analysis.user != request.user:
        from django.http import Http404
        raise Http404
    # Support POST to save a user-selected landing point for distance calculation.
    if request.method == 'POST':
        # Expect landing_lat and landing_lng in POST data (AJAX or form submit)
        try:
            landing_lat = request.POST.get('landing_lat') or request.POST.get('lat')
            landing_lng = request.POST.get('landing_lng') or request.POST.get('lng')
            prev_id = request.POST.get('previous_distance_id')
            hole_number = request.POST.get('hole_number') or analysis.hole_number
            if landing_lat and landing_lng:
                try:
                    from .models import ShotDistance
                    import json
                    lat_f = float(landing_lat)
                    lng_f = float(landing_lng)
                    sd = ShotDistance.objects.create(
                        shot=analysis,
                        hole_number=hole_number,
                        origin_lat=(analysis.latitude if hasattr(analysis, 'latitude') else None) or None,
                        origin_lng=(analysis.longitude if hasattr(analysis, 'longitude') else None) or None,
                        landing_lat=lat_f,
                        landing_lng=lng_f,
                        previous_shot=ShotDistance.objects.filter(pk=prev_id).first() if prev_id else None,
                    )
                    # Compute distance using util
                    from utils.shot_distance import compute_shot_distance
                    yards = compute_shot_distance(sd)
                    # Attach computed distance as attribute for JSON response
                    resp = {'ok': True, 'distance_yards': yards, 'distance_id': sd.pk}
                    # If AJAX, return JSON
                    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                        return JsonResponse(resp)
                    # Otherwise, redirect back to same page
                    messages.success(request, 'Landing point saved.')
                    return redirect('shots:analysis_detail', pk=analysis.pk)
                except Exception:
                    messages.error(request, 'Failed to save landing point.')
            else:
                messages.error(request, 'Invalid landing coordinates.')
        except Exception:
            messages.error(request, 'Error processing landing coordinates.')
    # Pass any transient overlay info present in query params so the UI can show
    # course/hole/yardage/par immediately after upload (before background processing finishes).
    overlay_info = {}
    course = request.GET.get('course')
    hole = request.GET.get('hole')
    yardage = request.GET.get('yardage')
    par = request.GET.get('par')
    if course:
        overlay_info['course'] = course
    if hole:
        try:
            overlay_info['hole'] = int(hole)
        except Exception:
            overlay_info['hole'] = hole
    if yardage:
        try:
            overlay_info['yardage'] = int(yardage)
        except Exception:
            overlay_info['yardage'] = yardage
    if par:
        try:
            overlay_info['par'] = int(par)
        except Exception:
            overlay_info['par'] = par

    # Compute a fallback 'back to hole' URL so the detail view can link back even when
    # the analysis.round or analysis.hole_number fields are missing.
    back_to_hole_url = None
    try:
        from django.urls import reverse
        # Primary: use explicit relation if present
        if getattr(analysis, 'round', None) and getattr(analysis, 'hole_number', None):
            back_to_hole_url = reverse('shots:round_hole_shots', args=[analysis.round.pk, analysis.hole_number])
        else:
            # Try to use HTTP_REFERER if it looks like a round/hole URL
            ref = request.META.get('HTTP_REFERER', '')
            if ref and '/round/' in ref and '/hole/' in ref:
                back_to_hole_url = ref
            else:
                # Last resort: if we have a course_name and a hole_number, try to find a recent round for that course
                if analysis.course_name and analysis.hole_number:
                    try:
                        from .models import ShotRound
                        # pick most recent round that matches course_name for this user
                        rr = ShotRound.objects.filter(user=analysis.user, course_name=analysis.course_name).order_by('-played_at').first()
                        if rr:
                            back_to_hole_url = reverse('shots:round_hole_shots', args=[rr.pk, analysis.hole_number])
                    except Exception:
                        back_to_hole_url = None
    except Exception:
        back_to_hole_url = None

    # Support a lightweight GET param to return recent distances as JSON for the map picker
    if request.method == 'GET' and request.GET.get('recent_distance'):
        try:
            from .models import ShotDistance
            recent = list(ShotDistance.objects.filter(shot__user=analysis.user).order_by('-created_at').values('pk', 'landing_lat', 'landing_lng')[:10])
            return JsonResponse({'recent': recent})
        except Exception:
            return JsonResponse({'recent': []})

    # Also expose any GPS coords (if present) to the template for map marker placement
    gps = {}
    try:
        # ShotAnalysis may have latitude/longitude fields or the original Shot model may
        if hasattr(analysis, 'latitude') and analysis.latitude:
            gps['lat'] = float(analysis.latitude)
        if hasattr(analysis, 'longitude') and analysis.longitude:
            gps['lng'] = float(analysis.longitude)
        # If the analysis doesn't have direct GPS fields, try to use any saved ShotDistance
        if not gps:
            from .models import ShotDistance
            sd = ShotDistance.objects.filter(shot=analysis).order_by('-created_at').first()
            if sd:
                # Prefer explicit origin saved on ShotDistance, otherwise fall back to landing
                if sd.origin_lat is not None and sd.origin_lng is not None:
                    gps['lat'] = float(sd.origin_lat)
                    gps['lng'] = float(sd.origin_lng)
                elif sd.landing_lat is not None and sd.landing_lng is not None:
                    gps['lat'] = float(sd.landing_lat)
                    gps['lng'] = float(sd.landing_lng)
    except Exception:
        gps = {}

    # Provide MAPBOX_TOKEN from environment to template for progressive enhancement
    try:
        # Prefer settings value, fall back to environment variable for runtime overrides
        mapbox_token = getattr(settings, 'MAPBOX_TOKEN', None) or os.environ.get('MAPBOX_TOKEN', '')
    except Exception:
        mapbox_token = ''

    # Provide recent saved ShotDistance entries for debugging/template use
    recent_distances = []
    try:
        from .models import ShotDistance
        recent_qs = ShotDistance.objects.filter(shot=analysis).order_by('-created_at')[:10]
        for sd in recent_qs:
            recent_distances.append({'id': sd.pk, 'origin_lat': sd.origin_lat, 'origin_lng': sd.origin_lng, 'landing_lat': sd.landing_lat, 'landing_lng': sd.landing_lng, 'created_at': sd.created_at})
    except Exception:
        recent_distances = []

    clubs = ['Driver','3-wood','5-wood','Hybrid','3-iron','4-iron','5-iron','6-iron','7-iron','8-iron','9-iron','PW','SW','LW','Putter','Other']
    return render(request, 'shots/analysis_detail.html', {'analysis': analysis, 'overlay_info': overlay_info, 'back_to_hole_url': back_to_hole_url, 'gps': gps, 'MAPBOX_TOKEN': mapbox_token, 'recent_distances': recent_distances, 'clubs': clubs})


@login_required
def reprocess_overlays(request, pk):
    """Allow the owner to request reprocessing of overlays (map, text, wireframe) and update club/tee.

    This endpoint accepts POST with keys: include_map, include_course_text, overlay_pose, club, used_tee
    It updates the ShotAnalysis record and schedules background reprocessing using the existing
    process_video_background helper.
    """
    from django.contrib import messages
    from django.shortcuts import redirect
    sa = get_object_or_404(ShotAnalysis, pk=pk)
    if sa.user != request.user:
        messages.error(request, 'You do not have permission to modify this shot.')
        return redirect('shots:analysis_detail', pk=pk)

    if request.method != 'POST':
        messages.error(request, 'Invalid request method.')
        return redirect('shots:analysis_detail', pk=pk)

    is_ajax = request.POST.get('ajax') == '1'

    # Read submitted options
    include_map = request.POST.get('include_map') == '1'
    include_text = request.POST.get('include_course_text') == '1'
    overlay_pose = request.POST.get('overlay_pose') == '1'
    club = (request.POST.get('club') or '').strip() or sa.club
    used_tee = (request.POST.get('used_tee') or '').strip() or sa.used_tee

    # Update the ShotAnalysis record
    try:
        sa.include_map = include_map
        sa.include_course_text = include_text
        sa.overlay_requested = overlay_pose
        sa.club = club
        sa.used_tee = used_tee
        sa.overlay_status = 'pending'
        sa.status = 'processing'
        sa.overlay_error_message = ''
        sa.save()
    except Exception:
        if is_ajax:
            return JsonResponse({'error': 'Failed to update shot settings.'}, status=500)
        messages.error(request, 'Failed to update shot settings.')
        return redirect('shots:analysis_detail', pk=pk)

    # Enqueue background reprocessing via Django-Q
    try:
        if sa.input_video:
            try:
                input_path = sa.input_video.path
            except (NotImplementedError, ValueError):
                input_path = sa.input_video.url
        else:
            input_path = None
        import tempfile as _tempfile
        _out_root = str(settings.MEDIA_ROOT) if settings.MEDIA_ROOT else _tempfile.gettempdir()
        if input_path:
            async_task(
                'shots.tasks.process_video_background',
                sa.pk,
                input_path,
                os.path.join(_out_root, 'output', f"reprocess_{sa.pk}.mp4"),
                None,
            )
        else:
            if is_ajax:
                return JsonResponse({'error': 'No input video available to reprocess.'}, status=400)
            messages.error(request, 'No input video available to reprocess.')
            return redirect('shots:analysis_detail', pk=pk)
    except Exception as e:
        if is_ajax:
            return JsonResponse({'error': str(e)}, status=500)
        messages.error(request, f'Failed to queue reprocessing: {e}')
        return redirect('shots:analysis_detail', pk=pk)

    if is_ajax:
        return JsonResponse({'status': 'queued'})
    return redirect('shots:analysis_detail', pk=pk)


from django.http import JsonResponse
from django.views.decorators.http import require_POST

@login_required
def overlay_status(request, pk):
    """Return JSON with overlay status for a ShotAnalysis (used for frontend polling)."""
    sa = get_object_or_404(ShotAnalysis, pk=pk)
    if sa.user != request.user:
        return JsonResponse({'error': 'forbidden'}, status=403)
    # Also expose overall processing status and the processed video URL when available
    processed_url = None
    processed_name = None
    try:
        if sa.processed_video and hasattr(sa.processed_video, 'url'):
            processed_name = sa.processed_video.name
            processed_url = sa.processed_video.url
    except Exception:
        processed_url = None
    print(f'[OVERLAY_STATUS] pk={pk} status={sa.status} overlay_status={sa.overlay_status} processed_video={processed_name} url_set={bool(processed_url)}', flush=True)
    return JsonResponse({
        'overlay_status': sa.overlay_status or 'pending',
        'overlay_error': sa.overlay_error_message or '',
        'status': sa.status or 'pending',
        'processed_video_url': processed_url,
    })


from django.contrib.auth.decorators import login_required

@login_required
def shot_list(request):
    """Show all favorited shots for the logged-in user with filters and pagination."""
    from django.core.paginator import Paginator

    qs = ShotAnalysis.objects.filter(user=request.user, is_favorite=True).order_by('-created_at')

    club_filter  = request.GET.get('club', '').strip()
    shape_filter = request.GET.get('shape', '').strip().lower()
    type_filter  = request.GET.get('type', '').strip()   # 'quick' | 'round' | ''
    score_min    = request.GET.get('score_min', '').strip()
    score_max    = request.GET.get('score_max', '').strip()

    if club_filter:
        qs = qs.filter(club__iexact=club_filter)
    if shape_filter:
        qs = qs.filter(ai_shot_shape__iexact=shape_filter)
    if type_filter == 'quick':
        qs = qs.filter(is_quick_upload=True)
    elif type_filter == 'round':
        qs = qs.filter(is_quick_upload=False)
    try:
        if score_min:
            qs = qs.filter(ai_overall_score__gte=int(score_min))
    except (ValueError, TypeError):
        score_min = ''
    try:
        if score_max:
            qs = qs.filter(ai_overall_score__lte=int(score_max))
    except (ValueError, TypeError):
        score_max = ''

    paginator  = Paginator(qs, 12)
    page_obj   = paginator.get_page(request.GET.get('page'))
    clubs      = ['Driver','3-wood','5-wood','Hybrid','3-iron','4-iron','5-iron','6-iron','7-iron','8-iron','9-iron','PW','SW','LW','Putter','Other']
    shot_shapes = ['straight','draw','fade','slice','hook','push','pull']

    return render(request, 'shots/shot_list.html', {
        'page_obj':      page_obj,
        'total_count':   qs.count(),
        'available_clubs': clubs,
        'shot_shapes':   shot_shapes,
        'club_filter':   club_filter,
        'shape_filter':  shape_filter,
        'type_filter':   type_filter,
        'score_min':     score_min,
        'score_max':     score_max,
    })


@login_required
def delete_shot(request, pk):
    """Delete a ShotAnalysis (and associated files) owned by the current user.

    This view only accepts POST requests. It will remove associated media files
    (input and processed) from disk when possible, then delete the DB record.
    """
    sa = get_object_or_404(ShotAnalysis, pk=pk)
    if sa.user != request.user:
        messages.error(request, 'You do not have permission to delete this shot.')
        return redirect('shots:shot_list')

    if request.method == 'POST':
        # Attempt to remove files from disk
        try:
            if sa.input_video and hasattr(sa.input_video, 'path') and os.path.exists(sa.input_video.path):
                os.remove(sa.input_video.path)
        except Exception:
            pass
        try:
            if sa.processed_video and hasattr(sa.processed_video, 'path') and os.path.exists(sa.processed_video.path):
                os.remove(sa.processed_video.path)
        except Exception:
            pass

        sa.delete()
        messages.success(request, 'Shot deleted successfully.')
        # Only redirect to HTTP_REFERER (same-origin); never follow an attacker-supplied next param
        referer = request.META.get('HTTP_REFERER', '')
        from urllib.parse import urlparse
        parsed = urlparse(referer)
        if parsed.scheme in ('http', 'https') and parsed.netloc == request.get_host():
            return redirect(referer)
        try:
            return redirect(reverse('shots:shot_list'))
        except Exception:
            return redirect('/shots/')

    # For non-POST requests, attempt to send the user back to the page they came from
    back = request.META.get('HTTP_REFERER')
    if back:
        return redirect(back)
    try:
        from django.urls import reverse
        return redirect(reverse('shots:shot_list'))
    except Exception:
        return redirect('/shots/')


@login_required
def courses_list(request):
    """List distinct course names from the user's ShotAnalysis records."""
    # If Course model exists with user records, prefer that
    try:
        from .models import Course
        user_courses = Course.objects.filter(user=request.user).order_by('-created_at')
        if user_courses.exists():
            course_items = []
            rounds_map = {}
            from .models import ShotRound
            for c in user_courses:
                course_items.append({'pk': c.pk, 'name': c.name, 'slug': c.slug, 'count': ShotAnalysis.objects.filter(user=request.user, course_name=c.name).count()})
                # collect recent rounds for this course
                rs = ShotRound.objects.filter(user=request.user, course_name=c.name).order_by('-played_at')[:10]
                rounds_map[c.pk] = [{'pk': r.pk, 'name': r.name or 'Round', 'played_at': r.played_at} for r in rs]
            # build a flattened list of user rounds for quick-add dropdown
            user_rounds = []
            for c in user_courses:
                rs = ShotRound.objects.filter(user=request.user, course_name=c.name).order_by('-played_at')[:50]
                for r in rs:
                    user_rounds.append({'course_pk': c.pk, 'course_name': c.name, 'round_pk': r.pk, 'round_name': r.name or 'Round', 'played_at': r.played_at})
            return render(request, 'shots/courses_list.html', {'courses': course_items, 'course_rounds': rounds_map, 'user_rounds': user_rounds})
    except Exception:
        pass

    # Fallback: Gather non-empty course names from ShotAnalysis
    qs = ShotAnalysis.objects.filter(user=request.user).exclude(course_name__isnull=True).exclude(course_name__exact='')
    courses = qs.values('course_name').annotate(count=Count('id')).order_by('course_name')
    # Provide a 'pk' key (empty) so templates that check c.pk don't error when
    # Course model isn't present and we only have aggregated names.
    course_items = [{'pk': '', 'name': c['course_name'], 'slug': slugify(c['course_name']), 'count': c['count']} for c in courses]
    return render(request, 'shots/courses_list.html', {'courses': course_items})


@login_required
def add_course(request):
    """Simple form to add a user-owned Course."""
    from .models import Course
    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        if not name:
            return render(request, 'shots/add_course.html', {'error': 'Course name required'})
        slug = slugify(name)
        # Ensure unique slug by appending counter if needed
        base = slug
        i = 1
        while Course.objects.filter(slug=slug).exists():
            slug = f"{base}-{i}"
            i += 1
        course = Course.objects.create(user=request.user, name=name, slug=slug)

        # Best-effort: fetch tee names from the Golf Course API and save them on the course
        api_key = GOLF_COURSE_API_KEY_HARDCODED or os.environ.get('GOLF_COURSE_API_KEY')
        if api_key:
            try:
                api_url = 'https://api.golfcourseapi.com/v1/search'
                resp = requests.get(api_url, params={'search_query': name}, headers={'Authorization': f'Key {api_key}'}, timeout=8)
                if resp.status_code == 200:
                    payload = resp.json()
                    data = payload.get('data') if isinstance(payload, dict) and 'data' in payload else payload
                    courses = data.get('courses') if isinstance(data, dict) and 'courses' in data else (data if isinstance(data, list) else [])
                    tee_names = []
                    if isinstance(courses, list):
                        for c in courses:
                            tees = c.get('tees') if isinstance(c, dict) else None
                            if isinstance(tees, dict):
                                for arr in tees.values():
                                    if isinstance(arr, list):
                                        for t in arr:
                                            try:
                                                tname = t.get('tee_name') or t.get('teeName') or t.get('name')
                                                if tname and tname not in tee_names:
                                                    tee_names.append(tname)
                                            except Exception:
                                                pass
                    if tee_names:
                        import json as _json
                        course.tee_names_json = _json.dumps(_normalize_tee_names(tee_names))
                        course.save()
            except Exception:
                # Non-fatal: ignore API failures during course creation
                pass

        messages.success(request, 'Course added.')
        return redirect('shots:courses_list')

    return render(request, 'shots/add_course.html')


@login_required
def course_detail(request, pk):
    from .models import Course, ShotRound
    course = get_object_or_404(Course, pk=pk, user=request.user)
    rounds = ShotRound.objects.filter(user=request.user, course_name=course.name).order_by('-played_at')[:50]
    return render(request, 'shots/course_detail.html', {'course': course, 'rounds': rounds})


@login_required
def refresh_course_tees(request, pk):
    """POST endpoint to re-fetch tee names for a Course and persist them."""
    from .models import Course
    if request.method != 'POST':
        messages.error(request, 'Invalid request method.')
        return redirect('shots:course_detail', pk=pk)

    course = get_object_or_404(Course, pk=pk, user=request.user)
    api_key = GOLF_COURSE_API_KEY_HARDCODED or os.environ.get('GOLF_COURSE_API_KEY')
    updated = False
    if api_key and course.name:
        try:
            api_url = 'https://api.golfcourseapi.com/v1/search'
            resp = requests.get(api_url, params={'search_query': course.name}, headers={'Authorization': f'Key {api_key}'}, timeout=8)
            if resp.status_code == 200:
                payload = resp.json()
                data = payload.get('data') if isinstance(payload, dict) and 'data' in payload else payload
                courses = data.get('courses') if isinstance(data, dict) and 'courses' in data else (data if isinstance(data, list) else [])
                tee_names = []
                if isinstance(courses, list):
                    for c in courses:
                        tees = c.get('tees') if isinstance(c, dict) else None
                        if isinstance(tees, dict):
                            for arr in tees.values():
                                if isinstance(arr, list):
                                    for t in arr:
                                        try:
                                            tname = t.get('tee_name') or t.get('teeName') or t.get('name')
                                            if tname and tname not in tee_names:
                                                tee_names.append(tname)
                                        except Exception:
                                            pass
                if tee_names:
                    import json as _json
                    course.tee_names_json = _json.dumps(_normalize_tee_names(tee_names))
                    course.save()
                    updated = True
        except Exception:
            updated = False

    if updated:
        messages.success(request, 'Course tee sets refreshed.')
    else:
        messages.error(request, 'Failed to refresh tee sets from API.')
    return redirect('shots:course_detail', pk=pk)


@login_required
def add_round(request, pk):
    """Add a new ShotRound for the given Course.

    GET: render a simple "Add Round" form that shows which course the round will be added to.
    POST: create the ShotRound (name + optional played_at date) and redirect to the rounds list
    for the course so the user can view the newly-created round.
    """
    from .models import Course, ShotRound
    course = get_object_or_404(Course, pk=pk, user=request.user)

    if request.method == 'POST':
        name = (request.POST.get('name') or '').strip() or None
        played_at_raw = (request.POST.get('played_at') or '').strip() or None
        played_at = None
        if played_at_raw:
            try:
                from dateutil import parser as _dp
                dt = _dp.parse(played_at_raw)
                # Store naive UTC if tz-aware
                if dt.tzinfo:
                    import datetime as _dt
                    dt = dt.astimezone(_dt.timezone.utc).replace(tzinfo=None)
                played_at = dt
            except Exception:
                played_at = None

        # Accept typed tee input (case-insensitive). If provided, try to match against
        # stored tee names (from Course.tee_names_json). If no match, we'll fall back to
        # selecting the first available tee from stored data or the Golf Course API.
        typed_tee = (request.POST.get('selected_tee') or '').strip() or None
        selected_tee = None

        # Gather stored tee names (if any)
        stored_teenames = []
        try:
            if getattr(course, 'tee_names_json', None):
                import json as _json
                parsed = _json.loads(course.tee_names_json)
                if isinstance(parsed, list):
                    stored_teenames = _normalize_tee_names(parsed)
        except Exception:
            stored_teenames = []

        # If the user typed a tee, try case-insensitive match against stored names
        if typed_tee:
            try:
                lower_map = {t.lower(): t for t in stored_teenames}
                if typed_tee.lower() in lower_map:
                    selected_tee = lower_map[typed_tee.lower()]
                else:
                    # keep the typed value for now; may be validated/normalized later
                    selected_tee = typed_tee
            except Exception:
                selected_tee = typed_tee

        # If no selection yet, pick the first stored tee or fall back to API-first-tee
        if not selected_tee:
            try:
                if stored_teenames:
                    selected_tee = stored_teenames[0]
                else:
                    # Best-effort API lookup if none stored
                    api_key = GOLF_COURSE_API_KEY_HARDCODED or os.environ.get('GOLF_COURSE_API_KEY')
                    if api_key and course.name:
                        try:
                            api_url = 'https://api.golfcourseapi.com/v1/search'
                            resp = requests.get(api_url, params={'search_query': course.name}, headers={'Authorization': f'Key {api_key}'}, timeout=6)
                            if resp.status_code == 200:
                                payload = resp.json()
                                data = payload.get('data') if isinstance(payload, dict) and 'data' in payload else payload
                                courses = data.get('courses') if isinstance(data, dict) and 'courses' in data else (data if isinstance(data, list) else [])
                                if isinstance(courses, list) and courses:
                                    first = courses[0]
                                    tees = first.get('tees') if isinstance(first, dict) else None
                                    if isinstance(tees, dict):
                                        for arr in tees.values():
                                            if isinstance(arr, list) and arr:
                                                t = arr[0]
                                                if isinstance(t, dict):
                                                    tname = t.get('tee_name') or t.get('teeName') or t.get('name')
                                                    if tname:
                                                        selected_tee = tname
                                                        break
                                    elif isinstance(tees, list) and tees:
                                        t = tees[0]
                                        if isinstance(t, dict):
                                            tname = t.get('tee_name') or t.get('teeName') or t.get('name')
                                            if tname:
                                                selected_tee = tname
                        except Exception:
                            pass
            except Exception:
                selected_tee = None
        try:
            round_obj = ShotRound.objects.create(user=request.user, name=name, course_name=course.name, played_at=played_at, selected_tee=selected_tee)
            messages.success(request, 'Round created.')
            # If the form requested to continue to the analyze/upload flow, redirect there
            to_analyze = (request.POST.get('to_analyze') == '1') or (request.GET.get('to_analyze') == '1')
            if to_analyze:
                from urllib.parse import quote_plus
                return redirect(f"{reverse('shots:analyze_upload')}?round_id={round_obj.pk}&course={quote_plus(course.name)}")
            # Otherwise redirect to rounds list for this course
            return redirect('shots:rounds_list_for_course', course_slug=course.slug)
        except Exception:
            messages.error(request, 'Failed to create round. Please try again.')

    # For GET render the simple add-round form
    # existing rounds for attach list - only rounds played at this course
    rounds = ShotRound.objects.filter(user=request.user, course_name=course.name).order_by('-played_at', '-created_at')[:50]
    selected_round = request.GET.get('round_id')

    # Prefer tee names stored on Course model; fall back to API fetch if not present.
    prefetched_tee_names = []
    try:
        import json as _json
        if course.tee_names_json:
            try:
                parsed = _json.loads(course.tee_names_json)
                if isinstance(parsed, list):
                    prefetched_tee_names = _normalize_tee_names(parsed)
            except Exception:
                prefetched_tee_names = []
    except Exception:
        prefetched_tee_names = []

    # If no stored tees, attempt a best-effort API fetch (non-fatal)
    if not prefetched_tee_names:
        try:
            api_key = GOLF_COURSE_API_KEY_HARDCODED or os.environ.get('GOLF_COURSE_API_KEY')
            if api_key and course.name:
                api_url = 'https://api.golfcourseapi.com/v1/search'
                resp = requests.get(api_url, params={'search_query': course.name}, headers={'Authorization': f'Key {api_key}'}, timeout=6)
                if resp.status_code == 200:
                    payload = resp.json()
                    data = payload.get('data') if isinstance(payload, dict) and 'data' in payload else payload
                    courses = data.get('courses') if isinstance(data, dict) and 'courses' in data else (data if isinstance(data, list) else [])
                    if isinstance(courses, list):
                        for c in courses:
                            tees = c.get('tees') if isinstance(c, dict) else None
                            if isinstance(tees, dict):
                                for arr in tees.values():
                                    if isinstance(arr, list):
                                        for t in arr:
                                            try:
                                                name = t.get('tee_name') or t.get('teeName') or t.get('name')
                                                if name and name not in prefetched_tee_names:
                                                    prefetched_tee_names.append(name)
                                            except Exception:
                                                pass
        except Exception:
            prefetched_tee_names = []

    # Deduplicate while preserving order
    seen = set(); ordered = []
    for n in prefetched_tee_names:
        if n and n not in seen:
            seen.add(n); ordered.append(n)

    try:
        logger.info(f"add_round: prefetched {len(ordered)} tees for course={course.name!r} -> {ordered}")
    except Exception:
        pass

    # Render a simple Add Round page which posts back here
    return render(request, 'shots/add_round.html', {
        'course_name': course.name,
        'rounds': rounds,
        'selected_round_id': selected_round,
        'prefetched_tee_names': ordered,
    })


@login_required
def add_hole(request, pk):
    """Quick add a hole for an existing round. The page accepts optional
    round_id in the querystring so the form can prefill the round and course.
    POST creates a placeholder ShotAnalysis for the given round/hole (minimal)
    so it appears in hole listings. If no round_id provided, redirect to add_round.
    """
    from .models import Course, ShotRound, ShotAnalysis
    course = get_object_or_404(Course, pk=pk, user=request.user)
    round_id = request.GET.get('round_id') or request.POST.get('round_id')

    if not round_id:
        # If no round specified, fall back to the add_round flow
        return redirect('shots:add_round', pk=pk)

    round_obj = ShotRound.objects.filter(pk=int(round_id), user=request.user, course_name=course.name).first()
    if not round_obj:
        messages.error(request, 'Selected round not found for this course.')
        return redirect('shots:add_round', pk=pk)

    # This quick-add behavior has been replaced by redirecting users to the analyze
    # upload form where they can attach a video for the hole. If no round_id is
    # supplied, fall back to add_round.
    round_id = request.GET.get('round_id') or request.POST.get('round_id')
    if not round_id:
        return redirect('shots:add_round', pk=pk)
    from urllib.parse import quote_plus
    return redirect(f"{reverse('shots:analyze_upload')}?round_id={round_id}&course={quote_plus(course.name)}")


@login_required
def rounds_list(request, course_slug=None):
    """List rounds for the user. If course_slug provided, filter rounds for that course."""
    from .models import ShotRound
    qs = ShotRound.objects.filter(user_id=getattr(request.user, 'pk', None))
    fixed_course_name = None
    if course_slug:
        # Prefer user-created Course records for this slug
        try:
            from .models import Course
            course_obj = Course.objects.filter(user=request.user, slug=course_slug).first()
            if course_obj:
                qs = qs.filter(course_name=course_obj.name)
                fixed_course_name = course_obj.name
            else:
                # Fallback to mapping against existing ShotAnalysis entries
                all_courses = ShotAnalysis.objects.filter(user=request.user).values_list('course_name', flat=True).distinct()
                slug_map = {slugify(c): c for c in all_courses}
                course_name = slug_map.get(course_slug)
                if course_name:
                    qs = qs.filter(course_name=course_name)
                    fixed_course_name = course_name
        except Exception:
            # If Course model lookup fails for any reason, fallback to old behavior
            all_courses = ShotAnalysis.objects.filter(user=request.user).values_list('course_name', flat=True).distinct()
            slug_map = {slugify(c): c for c in all_courses}
            course_name = slug_map.get(course_slug)
            if course_name:
                qs = qs.filter(course_name=course_name)
                fixed_course_name = course_name
    rounds = qs.order_by('-played_at', '-created_at')[:100]
    # Persist the current course in the user's session so subsequent uploads default to it
    try:
        if course_slug:
            # store slug and friendly name
            request.session['current_course_slug'] = course_slug
            request.session['current_course_name'] = fixed_course_name
        else:
            request.session.pop('current_course_slug', None)
            request.session.pop('current_course_name', None)
    except Exception:
        pass
    fixed_course_obj_pk = None
    try:
        if course_slug and 'course_obj' in locals() and course_obj:
            fixed_course_obj_pk = course_obj.pk
    except Exception:
        fixed_course_obj_pk = None
    return render(request, 'shots/rounds_list.html', {
        'rounds': rounds,
        'course_slug': course_slug,
        'fixed_course_name': fixed_course_name,
        'fixed_course_obj_pk': fixed_course_obj_pk,
    })


@login_required
def delete_round(request, round_pk):
    """Delete a ShotRound and all its associated ShotAnalysis records and media.

    This view only accepts POST and verifies ownership. It removes input and processed
    media files where present before deleting DB records. Redirects back to the
    rounds list after completion.
    """
    from .models import ShotRound
    if request.method != 'POST':
        messages.error(request, 'Invalid request method for deleting a round.')
        return redirect(request.META.get('HTTP_REFERER') or reverse('shots:rounds_list'))

    round_obj = get_object_or_404(ShotRound, pk=round_pk)
    if round_obj.user_id != getattr(request.user, 'pk', None):
        messages.error(request, 'You do not have permission to delete this round.')
        return redirect(request.META.get('HTTP_REFERER') or reverse('shots:rounds_list'))

    # Delete associated ShotAnalysis entries and their files
    related = ShotAnalysis.objects.filter(round=round_obj)
    for sa in related:
        try:
            if sa.input_video and hasattr(sa.input_video, 'path') and os.path.exists(sa.input_video.path):
                os.remove(sa.input_video.path)
        except Exception:
            logger.exception('Failed to remove input file for analysis %s', getattr(sa, 'pk', 'unknown'))
        try:
            if sa.processed_video and hasattr(sa.processed_video, 'path') and os.path.exists(sa.processed_video.path):
                os.remove(sa.processed_video.path)
        except Exception:
            logger.exception('Failed to remove processed file for analysis %s', getattr(sa, 'pk', 'unknown'))
        try:
            sa.delete()
        except Exception:
            logger.exception('Failed to delete ShotAnalysis %s', getattr(sa, 'pk', 'unknown'))

    # Finally delete the round itself
    try:
        round_obj.delete()
        messages.success(request, 'Round and its shots were deleted successfully.')
    except Exception:
        logger.exception('Failed to delete ShotRound %s', getattr(round_obj, 'pk', 'unknown'))
        messages.error(request, 'Failed to delete the round. Please try again.')

    return redirect('shots:rounds_list')



@login_required
def delete_course(request, pk):
    """Delete a Course and all its ShotRound and ShotAnalysis records.

    Accepts POST only and verifies ownership of the Course.
    """
    from .models import Course, ShotRound
    if request.method != 'POST':
        messages.error(request, 'Invalid request method for deleting a course.')
        return redirect(request.META.get('HTTP_REFERER', 'shots:courses_list'))

    course = get_object_or_404(Course, pk=pk)
    if course.user_id != getattr(request.user, 'pk', None):
        messages.error(request, 'You do not have permission to delete this course.')
        return redirect(request.META.get('HTTP_REFERER', 'shots:courses_list'))

    # Find rounds for this course (by course name)
    rounds = ShotRound.objects.filter(user=request.user, course_name=course.name)
    for r in rounds:
        # delete associated analyses and their files
        related = ShotAnalysis.objects.filter(round=r)
        for sa in related:
            try:
                if sa.input_video and hasattr(sa.input_video, 'path') and os.path.exists(sa.input_video.path):
                    os.remove(sa.input_video.path)
            except Exception:
                logger.exception('Failed to remove input file for analysis %s', getattr(sa, 'pk', 'unknown'))
            try:
                if sa.processed_video and hasattr(sa.processed_video, 'path') and os.path.exists(sa.processed_video.path):
                    os.remove(sa.processed_video.path)
            except Exception:
                logger.exception('Failed to remove processed file for analysis %s', getattr(sa, 'pk', 'unknown'))
            try:
                sa.delete()
            except Exception:
                logger.exception('Failed to delete ShotAnalysis %s', getattr(sa, 'pk', 'unknown'))
        # delete the round
        try:
            r.delete()
        except Exception:
            logger.exception('Failed to delete ShotRound %s', getattr(r, 'pk', 'unknown'))

    # Finally delete the Course record
    try:
        course.delete()
        messages.success(request, 'Course and its rounds were deleted successfully.')
    except Exception:
        logger.exception('Failed to delete Course %s', getattr(course, 'pk', 'unknown'))
        messages.error(request, 'Failed to delete the course. Please try again.')

    return redirect('shots:courses_list')





@login_required
def round_holes(request, round_pk):
    """Show holes and their shots for a given round."""
    from .models import ShotRound
    r = get_object_or_404(ShotRound, pk=round_pk, user_id=getattr(request.user, 'pk', None))
    # Gather hole numbers for shots in this round
    qs = ShotAnalysis.objects.filter(user=request.user, round=r).exclude(hole_number__isnull=True)
    holes = qs.values('hole_number').annotate(count=Count('id')).order_by('hole_number')
    hole_items = [{'hole': h['hole_number'], 'count': h['count']} for h in holes]
    # provide course_slug so templates can navigate back to course-scoped rounds
    try:
        from django.utils.text import slugify
        course_slug = slugify(r.course_name) if r.course_name else None
    except Exception:
        course_slug = None
    return render(request, 'shots/round_holes.html', {'round': r, 'holes': hole_items, 'course_slug': course_slug})


@login_required
def toggle_favorite(request, pk):
    """Toggle the is_favorite flag for a ShotAnalysis owned by the user."""
    if request.method != 'POST':
        return redirect('shots:shot_list')

    sa = get_object_or_404(ShotAnalysis, pk=pk)
    if sa.user != request.user:
        messages.error(request, 'You do not have permission to modify this shot.')
        return redirect(request.META.get('HTTP_REFERER', 'shots:shot_list'))

    sa.is_favorite = not bool(sa.is_favorite)
    sa.save()
    if sa.is_favorite:
        messages.success(request, 'Shot shared to favorites.')
    else:
        messages.success(request, 'Shot removed from favorites.')

    return redirect(request.META.get('HTTP_REFERER') or reverse('shots:shot_list'))


@login_required
def course_holes(request, course_slug):
    """List holes for a given course (slug) with counts."""
    # Recreate course name by finding matching records (case-insensitive slug match)
    # We match by slugifying stored course_name values
    all_courses = ShotAnalysis.objects.filter(user=request.user).exclude(course_name__isnull=True).exclude(course_name__exact='')
    # Build mapping slug -> original name
    slug_map = {}
    for c in all_courses.values_list('course_name', flat=True).distinct():
        slug_map[slugify(c)] = c
    course_name = slug_map.get(course_slug)
    if not course_name:
        return render(request, 'shots/course_holes.html', {'course_name': course_slug, 'holes': []})
    # Get holes for this course
    holes_qs = ShotAnalysis.objects.filter(user=request.user, course_name=course_name).exclude(hole_number__isnull=True)
    holes = holes_qs.values('hole_number').annotate(count=Count('id')).order_by('hole_number')
    hole_items = [{'hole': h['hole_number'], 'count': h['count']} for h in holes]

    # Attempt to load cached CourseMetadata
    course_info = {'address': None, 'hole_count': None, 'par_total': None}
    slug = course_slug
    CACHE_TTL_DAYS = 30
    try:
        cm = CourseMetadata.objects.filter(course_slug=slug).first()
        refresh = True
        if cm:
            import datetime
            now_utc = datetime.datetime.now(tz=datetime.timezone.utc)
            fetched_aware = cm.fetched_at if cm.fetched_at.tzinfo else cm.fetched_at.replace(tzinfo=datetime.timezone.utc)
            age = now_utc - fetched_aware
            if age.days < CACHE_TTL_DAYS:
                # use cache
                course_info['address'] = cm.address
                course_info['hole_count'] = cm.hole_count
                course_info['par_total'] = cm.par_total
                refresh = False
    except Exception:
        cm = None
        refresh = True

    if refresh:
        # Fetch from API and upsert cache
        api_key = GOLF_COURSE_API_KEY_HARDCODED or os.environ.get('GOLF_COURSE_API_KEY')
        if api_key:
            try:
                api_url = 'https://api.golfcourseapi.com/v1/search'
                resp = requests.get(api_url, params={'search_query': course_name}, headers={'Authorization': f'Key {api_key}'}, timeout=8)
                if resp.status_code == 200:
                    try:
                        payload = resp.json()

                        def find_address(obj):
                            if isinstance(obj, dict):
                                for k in ('address', 'address_line1', 'formatted_address'):
                                    if k in obj and obj.get(k):
                                        return obj.get(k)
                                for v in obj.values():
                                    res = find_address(v)
                                    if res:
                                        return res
                            elif isinstance(obj, list):
                                for it in obj:
                                    res = find_address(it)
                                    if res:
                                        return res
                            return None

                        def find_hole_info(obj):
                            if isinstance(obj, dict):
                                if 'holes' in obj and isinstance(obj.get('holes'), list):
                                    holes = obj.get('holes')
                                    hole_count = len(holes)
                                    par_sum = 0
                                    found_par = False
                                    for h in holes:
                                        if isinstance(h, dict):
                                            for pkey in ('par', 'par_value', 'par_total'):
                                                if pkey in h and h.get(pkey) is not None:
                                                    try:
                                                        par_sum += int(h.get(pkey))
                                                        found_par = True
                                                    except Exception:
                                                        pass
                                    return (hole_count if hole_count else None, par_sum if found_par else None)

                                for k in ('par_total', 'total_par', 'course_par'):
                                    if k in obj and obj.get(k) is not None:
                                        try:
                                            return (None, int(obj.get(k)))
                                        except Exception:
                                            pass

                                for v in obj.values():
                                    res = find_hole_info(v)
                                    if res and (res[0] or res[1]):
                                        return res

                            elif isinstance(obj, list):
                                for it in obj:
                                    res = find_hole_info(it)
                                    if res and (res[0] or res[1]):
                                        return res
                            return (None, None)

                        addr = find_address(payload)
                        hole_count, par_total = find_hole_info(payload)
                        # update course_info
                        if addr:
                            course_info['address'] = addr
                        if hole_count:
                            course_info['hole_count'] = hole_count
                        if par_total:
                            course_info['par_total'] = par_total

                        # upsert cache
                        try:
                            if cm:
                                cm.address = course_info['address']
                                cm.hole_count = course_info['hole_count']
                                cm.par_total = course_info['par_total']
                                cm.name = course_name
                                cm.save()
                            else:
                                CourseMetadata.objects.create(course_slug=slug, name=course_name, address=course_info['address'], hole_count=course_info['hole_count'], par_total=course_info['par_total'])
                        except Exception:
                            pass
                    except ValueError:
                        pass
            except requests.RequestException:
                pass

    return render(request, 'shots/course_holes.html', {'course_name': course_name, 'course_slug': course_slug, 'holes': hole_items, 'course_info': course_info})


@login_required
def hole_shots(request, course_slug, hole):
    """List ShotAnalysis entries for a given course and hole number."""
    # Resolve course name like above
    all_courses = ShotAnalysis.objects.filter(user=request.user).exclude(course_name__isnull=True).exclude(course_name__exact='')
    slug_map = {slugify(c): c for c in all_courses.values_list('course_name', flat=True).distinct()}
    course_name = slug_map.get(course_slug)
    if not course_name:
        analyses = []
    else:
        analyses = ShotAnalysis.objects.filter(user=request.user, course_name=course_name, hole_number=hole).order_by('stroke_number', 'created_at')
    # Try to fetch hole-specific info (yardage, par, handicap) from the Golf Course API.
    hole_info = {}
    try:
        if course_name:
            hole_info = fetch_hole_info(course_name, hole)
    except Exception:
        hole_info = {}

    return render(request, 'shots/hole_shots.html', {'analyses': analyses, 'course_name': course_name or course_slug, 'hole': hole, 'course_slug': course_slug, 'hole_info': hole_info})


@login_required
def round_hole_shots(request, round_pk, hole):
    """List ShotAnalysis entries for a given round and hole number."""
    from .models import ShotRound
    r = get_object_or_404(ShotRound, pk=round_pk, user=request.user)
    analyses = ShotAnalysis.objects.filter(user=request.user, round=r, hole_number=hole).order_by('stroke_number', 'created_at')
    # Try to fetch hole-specific info (yardage, par, handicap) from the Golf Course API.
    hole_info = {}
    try:
        if r.course_name:
            hole_info = fetch_hole_info(r.course_name, hole)
    except Exception:
        hole_info = {}

    from django.urls import reverse
    back_to_round_url = None
    try:
        back_to_round_url = reverse('shots:round_holes', args=[r.pk])
    except Exception:
        back_to_round_url = None
    return render(request, 'shots/hole_shots.html', {'analyses': analyses, 'course_name': r.course_name or '', 'hole': hole, 'course_slug': slugify(r.course_name) if r.course_name else '', 'hole_info': hole_info, 'round': r, 'back_to_round_url': back_to_round_url})


@login_required
def hole_shot_map(request, hole):
    """Render a Mapbox visualization of ShotDistance records for a given hole.

    URL provides `hole` as a path parameter. Optional GET params:
      - round_pk (int) or course_slug (str)

    This view is read-only and serializes landing coordinates for shots that
    have landing_lat/landing_lng set. Shots are ordered ascending by created_at.
    """
    from django.http import HttpResponseBadRequest
    from django.http import JsonResponse
    try:
        hole_num = int(hole)
    except Exception:
        return HttpResponseBadRequest('Invalid hole number')

    # Base queryset: ShotAnalysis owned by the current user for this hole.
    # We build one marker per ShotAnalysis to ensure shot numbering follows
    # the chronological order in which analyses (shots) were created.
    from .models import ShotDistance, ShotAnalysis
    analyses_qs = ShotAnalysis.objects.filter(user=request.user, hole_number=hole_num)

    # Optional filter by round_pk
    round_pk = request.GET.get('round_pk')
    if round_pk:
        try:
            rp = int(round_pk)
            analyses_qs = analyses_qs.filter(round__pk=rp)
        except Exception:
            pass

    # Optional filter by course_slug (resolve to course_name)
    course_slug = request.GET.get('course_slug')
    if course_slug and not round_pk:
        # Find course name from user's analyses
        slug_map = { slugify(c): c for c in ShotAnalysis.objects.filter(user=request.user).values_list('course_name', flat=True).distinct() }
        course_name = slug_map.get(course_slug)
        if course_name:
            analyses_qs = analyses_qs.filter(course_name=course_name)

    # If no round_pk specified, prefer to show the most recent round only when
    # all available analyses for this hole belong to rounds. If the dataset
    # contains a mix of round-scoped and non-round analyses (common when a
    # user creates a new course/hole or uploads loosely), show all analyses so
    # markers are not unexpectedly omitted.
    if not round_pk:
        try:
            total_count = analyses_qs.count()
            count_with_round = analyses_qs.filter(round__isnull=False).count()
            # Only reduce to the most recent round when every analysis has a round
            if total_count > 0 and count_with_round > 0 and count_with_round == total_count:
                recent_with_round = analyses_qs.filter(round__isnull=False).order_by('-created_at').first()
                if recent_with_round and getattr(recent_with_round, 'round', None):
                    analyses_qs = analyses_qs.filter(round=recent_with_round.round)
        except Exception:
            # fall back to unfiltered analyses_qs on error
            pass

    # Choose ordering: prefer authoritative video timestamp (probe_creation_time)
    # when available for all shots in the queryset. Next prefer client_added_time
    # (browser-side timestamp captured at upload). Then fall back to stroke_number
    # if present for all items, otherwise use created_at.
    try:
        # Prefer the upload-assigned stroke ordering when available so the hole map
        # matches the order shown on the upload/analysis pages. Fall back to the
        # authoritative video timestamp (probe_creation_time), then client-added
        # timestamp, and finally created_at.
        total = analyses_qs.count()
        if total > 0 and analyses_qs.filter(stroke_number__isnull=False).count() == total:
            analyses_qs = analyses_qs.order_by('stroke_number', 'created_at')
        elif total > 0 and analyses_qs.filter(probe_creation_time__isnull=False).count() == total:
            analyses_qs = analyses_qs.order_by('probe_creation_time', 'created_at')
        elif total > 0 and analyses_qs.filter(client_added_time__isnull=False).count() == total:
            analyses_qs = analyses_qs.order_by('client_added_time', 'created_at')
        else:
            analyses_qs = analyses_qs.order_by('created_at')
    except Exception:
        analyses_qs = analyses_qs.order_by('created_at')
    shots = []
    for analysis in analyses_qs:
        lat = None
        lng = None
        coord_type = None
        # Prefer the origin coordinates stored in a related ShotDistance (the earliest origin for the shot)
        try:
            # Prefer a ShotDistance that contains an explicit origin (origin_lat/lng).
            sd_origin = ShotDistance.objects.filter(shot=analysis, origin_lat__isnull=False, origin_lng__isnull=False).order_by('created_at').first()
            if not sd_origin:
                # Fallback: if no origin is present, prefer a ShotDistance that has a landing (user may have set landing first).
                sd_origin = ShotDistance.objects.filter(shot=analysis, landing_lat__isnull=False, landing_lng__isnull=False).order_by('created_at').first()
            if not sd_origin:
                # Final fallback: take the earliest ShotDistance record if any.
                sd_origin = ShotDistance.objects.filter(shot=analysis).order_by('created_at').first()

            if sd_origin and sd_origin.origin_lat is not None and sd_origin.origin_lng is not None:
                lat = sd_origin.origin_lat
                lng = sd_origin.origin_lng
                coord_type = 'origin'
                distance_id = sd_origin.pk
            elif sd_origin and sd_origin.landing_lat is not None and sd_origin.landing_lng is not None:
                # Use landing coords as a marker fallback when no origin exists.
                lat = sd_origin.landing_lat
                lng = sd_origin.landing_lng
                coord_type = 'landing'
                distance_id = sd_origin.pk
            else:
                distance_id = None
        except Exception:
            sd_origin = None
            distance_id = None

        # Fallback to any GPS attached directly on the ShotAnalysis
        try:
            if (lat is None or lng is None) and hasattr(analysis, 'latitude') and analysis.latitude and hasattr(analysis, 'longitude') and analysis.longitude:
                lat = analysis.latitude
                lng = analysis.longitude
                coord_type = 'analysis_gps'
        except Exception:
            pass

        # Best-effort: if no ShotDistance/analysis GPS present, try to extract
        # coordinates from the uploaded video file using ffprobe. This does not
        # persist anything to the DB, but allows the hole map to show markers
        # immediately after upload when the video contains GPS metadata.
        if (lat is None or lng is None):
            try:
                if getattr(analysis, 'input_video', None):
                    _coords = None
                    # Try local path first; fall back to URL (S3-backed files raise
                    # NotImplementedError on .path but ffprobe can fetch from HTTPS).
                    _video_src = None
                    try:
                        _video_src = analysis.input_video.path
                    except Exception:
                        pass
                    if not _video_src:
                        try:
                            _video_src = analysis.input_video.url
                        except Exception:
                            pass
                    if _video_src:
                        try:
                            _coords = utils.extract_coords_from_video(_video_src)
                        except Exception:
                            _coords = None
                    if _coords:
                        try:
                            lon_ex, lat_ex = _coords
                            lat = float(lat_ex)
                            lng = float(lon_ex)
                            coord_type = 'extracted'
                            # Persist a ShotDistance only if none exists yet (avoid duplicate records on page refresh)
                            try:
                                from .models import ShotDistance
                                existing_sd = ShotDistance.objects.filter(shot=analysis).first()
                                if not existing_sd:
                                    ShotDistance.objects.create(shot=analysis, origin_lat=float(lat), origin_lng=float(lng), hole_number=hole_num)
                                distance_id = ShotDistance.objects.filter(shot=analysis).order_by('-created_at').first().pk
                            except Exception:
                                # Non-fatal: log and continue
                                logger.exception('Failed to persist extracted GPS for analysis %s', getattr(analysis, 'pk', None))
                        except Exception:
                            pass
            except Exception:
                # Non-fatal: extraction failures should not prevent the view from rendering
                pass
        if lat is None or lng is None:
            # skip analyses with no usable coordinates
            continue

        # Determine authoritative timestamp for this analysis: prefer probe, then client, then created
        ts = None
        try:
            if getattr(analysis, 'probe_creation_time', None):
                ts = analysis.probe_creation_time
            elif getattr(analysis, 'client_added_time', None):
                ts = analysis.client_added_time
            else:
                ts = analysis.created_at
        except Exception:
            ts = getattr(analysis, 'created_at', None)

        shots.append({
            'lat': float(lat),
            'lng': float(lng),
            'coord_type': coord_type,
            'stroke_number': getattr(analysis, 'stroke_number', None),
            'created_at': analysis.created_at.isoformat(),
            'timestamp': (ts.isoformat() if ts is not None else None),
            'analysis_id': analysis.pk,
            'distance_id': distance_id,
        })

    # Assign 1-based indices in the chosen ordering (oldest/first stroke => index 1)
    for i, s in enumerate(shots, start=1):
        s.setdefault('index', i)

    # Provide MAPBOX_TOKEN from settings/env
    try:
        mapbox_token = getattr(settings, 'MAPBOX_TOKEN', None) or os.environ.get('MAPBOX_TOKEN', '')
    except Exception:
        mapbox_token = ''

    # include course_slug in context so the template back-link can build the URL
    context = {
        'hole': hole_num,
        'shots_json': json.dumps(shots),
        'shots': shots,
        'MAPBOX_TOKEN': mapbox_token,
    'course_slug': course_slug or '',
    'round_pk': (int(round_pk) if round_pk and str(round_pk).isdigit() else None),
    'hole_pin': None,
    'hole_pin_json': 'null',
    }
    # Provide any saved HolePin for this user/hole so the template can lock the pin UI
    try:
        from .models import HolePin
        hp = HolePin.objects.filter(user=request.user, hole_number=hole_num).order_by('-created_at').first()
        if hp:
            pin_obj = {'lat': float(hp.lat), 'lng': float(hp.lng), 'created_at': hp.created_at.isoformat()}
            context['hole_pin'] = pin_obj
            try:
                context['hole_pin_json'] = json.dumps(pin_obj)
            except Exception:
                context['hole_pin_json'] = 'null'
    except Exception:
        pass
    return render(request, 'shots/hole_shot_map.html', context)


@login_required
def api_get_hole_pin(request, hole_id):
    """Return the latest HolePin for the current user and hole as JSON.

    GET /api/holes/<hole_id>/pin/
    Response: { ok: true, hole_pin: { lat, lng, created_at } } or { ok: true, hole_pin: null }
    """
    try:
        from .models import HolePin
        hp = HolePin.objects.filter(user=request.user, hole_number=hole_id).order_by('-created_at').first()
        if not hp:
            return JsonResponse({'ok': True, 'hole_pin': None})
        pin_obj = {'lat': float(hp.lat), 'lng': float(hp.lng), 'created_at': hp.created_at.isoformat()}
        return JsonResponse({'ok': True, 'hole_pin': pin_obj})
    except Exception as e:
        logger.exception('Error in api_get_hole_pin')
        return JsonResponse({'ok': False, 'error': str(e)}, status=500)


@login_required
@require_POST
def save_hole_pin(request, hole_id):
    """Persist a saved pin for a hole and recompute distances for all shots on that hole.

    - Stores a HolePin record (additive).
    - Iterates ShotDistance records for the hole (ordered by created_at asc) and
      recomputes distances using the existing compute_shot_distance util. The
      final shot's landing is treated as the saved pin.
    - Persists computed yards to the related ShotAnalysis.distance field.
    Returns JSON: {ok: True, shots_updated: N}

    Ordering note: shots are processed in chronological order (oldest -> newest)
    so that each ShotDistance's `origin` is considered the previous shot's landing
    when present. If a ShotDistance lacks an explicit origin, we attempt to use
    its stored origin_lat/origin_lng; the final shot uses the saved pin as landing.
    """
    try:
        import json as _json
        lat = request.POST.get('lat')
        lng = request.POST.get('lng')
        if lat is None or lng is None:
            return JsonResponse({'ok': False, 'error': 'Missing lat/lng'}, status=400)
        try:
            lat_f = float(lat); lng_f = float(lng)
        except Exception:
            return JsonResponse({'ok': False, 'error': 'Invalid coordinate format'}, status=400)

        from .models import HolePin, ShotDistance
        # Try to persist a HolePin for this user/hole; non-fatal if it fails
        hp = None
        try:
            # Persist a single user-scoped HolePin per hole. Use update_or_create so
            # subsequent saves overwrite the previous pin instead of creating many.
            hp, created = HolePin.objects.update_or_create(
                user=request.user,
                hole_number=hole_id,
                defaults={'lat': lat_f, 'lng': lng_f},
            )
        except Exception:
            # Log, but continue to recompute distances even if persisting the pin fails.
            logger.exception('Failed to persist HolePin; continuing to recompute distances')

        # Build ordered ShotDistance list following the same ordering used by the
        # hole map: prefer upload-assigned stroke_number when present for all
        # analyses, then probe_creation_time, then client_added_time, then created_at.
        from .models import ShotAnalysis
        analyses_qs = ShotAnalysis.objects.filter(user=request.user, hole_number=hole_id)
        try:
            total = analyses_qs.count()
            if total > 0 and analyses_qs.filter(stroke_number__isnull=False).count() == total:
                analyses_qs = analyses_qs.order_by('stroke_number', 'created_at')
            elif total > 0 and analyses_qs.filter(probe_creation_time__isnull=False).count() == total:
                analyses_qs = analyses_qs.order_by('probe_creation_time', 'created_at')
            elif total > 0 and analyses_qs.filter(client_added_time__isnull=False).count() == total:
                analyses_qs = analyses_qs.order_by('client_added_time', 'created_at')
            else:
                analyses_qs = analyses_qs.order_by('created_at')
        except Exception:
            analyses_qs = analyses_qs.order_by('created_at')

        # For each analysis pick the earliest ShotDistance (origin) so we have one
        # ShotDistance per shot aligned with the analysis ordering.
        sds = []
        for analysis in analyses_qs:
            sd_origin = ShotDistance.objects.filter(shot=analysis).order_by('created_at').first()
            if sd_origin:
                sds.append(sd_origin)
        if not sds:
            return JsonResponse({'ok': True, 'shots_updated': 0})

        from utils.shot_distance import compute_shot_distance
        from types import SimpleNamespace

        updated = 0
        shot_reports = []

        # Build a list of effective origins (may apply a light smoothing pass to
        # mitigate single-point GPS outliers). We do not modify the DB here.
        effective_origins = []
        for sd in sds:
            if sd.origin_lat is not None and sd.origin_lng is not None:
                effective_origins.append((float(sd.origin_lat), float(sd.origin_lng)))
            else:
                effective_origins.append((None, None))

        # Smoothing: if a middle origin is a large jump from previous but
        # previous and next are close, replace the middle origin with the
        # average of its neighbors for computation only.
        def yards_between(a, b):
            try:
                return distance_yards(a[0], a[1], b[0], b[1])
            except Exception:
                return None

        from utils.shot_distance import distance_yards
        n = len(effective_origins)
        for i in range(1, n-1):
            prev = effective_origins[i-1]
            cur = effective_origins[i]
            nxt = effective_origins[i+1]
            if prev[0] is None or cur[0] is None or nxt[0] is None:
                continue
            # distances in yards
            d_prev_cur = yards_between(prev, cur) or 0
            d_cur_next = yards_between(cur, nxt) or 0
            d_prev_next = yards_between(prev, nxt) or 0
            # If cur is far from both neighbors but neighbors are close to each
            # other, cur is likely an outlier (GPS spike). Thresholds conservative.
            if d_prev_cur > 80 and d_cur_next > 80 and d_prev_next < 40:
                # replace cur with midpoint of neighbors for computation
                mid_lat = (prev[0] + nxt[0]) / 2.0
                mid_lng = (prev[1] + nxt[1]) / 2.0
                effective_origins[i] = (mid_lat, mid_lng)

        # Iterate chronological order and compute every shot's distance as follows:
        # - For i in 0..n-2: compute shot_i from its origin -> shot_{i+1}.origin (if both origins exist).
        #   Also persist shot_i.landing to the next origin so the additive ShotDistance reflects the landing.
        # - For the final shot (n-1): set its landing to the saved pin and compute origin->pin.
        n = len(sds)
        for i in range(n):
            try:
                curr = sds[i]
                # If this is not the final shot, attempt to use the next shot's origin as this shot's landing
                if i < n - 1:
                    next_sd = sds[i + 1]
                    # Only compute if both origins are present
                    if curr.origin_lat is not None and curr.origin_lng is not None and next_sd.origin_lat is not None and next_sd.origin_lng is not None:
                        # Set this shot's landing to next shot's origin
                        curr.landing_lat = float(next_sd.origin_lat)
                        curr.landing_lng = float(next_sd.origin_lng)
                        try:
                            curr.save()
                        except Exception:
                            # Non-fatal; continue to computation even if save fails
                            pass
                        temp = SimpleNamespace(origin_lat=curr.origin_lat, origin_lng=curr.origin_lng, landing_lat=next_sd.origin_lat, landing_lng=next_sd.origin_lng)
                        yards = compute_shot_distance(temp)
                        # Record result for diagnostics
                        shot_reports.append({'shot_distance_pk': curr.pk, 'shot_analysis_pk': getattr(curr.shot, 'pk', None), 'origin': (curr.origin_lat, curr.origin_lng), 'landing': (next_sd.origin_lat, next_sd.origin_lng), 'computed_yards': (float(yards) if yards is not None else None)})
                        if yards is not None:
                            try:
                                sa = curr.shot
                                sa.distance = float(yards)
                                sa.save()
                                updated += 1
                            except Exception:
                                pass
                    else:
                        # insufficient origin data to compute this segment; skip
                        continue
                else:
                    # Final shot: set landing to saved pin and compute origin->pin
                    curr.landing_lat = lat_f
                    curr.landing_lng = lng_f
                    try:
                        curr.save()
                    except Exception:
                        pass
                    if curr.origin_lat is not None and curr.origin_lng is not None:
                        yards = compute_shot_distance(curr)
                        shot_reports.append({'shot_distance_pk': curr.pk, 'shot_analysis_pk': getattr(curr.shot, 'pk', None), 'origin': (curr.origin_lat, curr.origin_lng), 'landing': (curr.landing_lat, curr.landing_lng), 'computed_yards': (float(yards) if yards is not None else None)})
                        if yards is not None:
                            try:
                                sa = curr.shot
                                sa.distance = float(yards)
                                sa.save()
                                updated += 1
                            except Exception:
                                pass
            except Exception:
                logger.exception('Failed to recompute for ShotDistance %s', getattr(curr, 'pk', None))

        # Include persisted pin info in the response so the client can lock and render it.
        pin_obj = None
        try:
            if hp:
                pin_obj = {'lat': float(hp.lat), 'lng': float(hp.lng), 'created_at': hp.created_at.isoformat()}
        except Exception:
            pin_obj = None
    # Attempt to include the final computed distance for the last shot if we set it.
        final_distance = None
        try:
            last_sd = sds[-1]
            if last_sd and getattr(last_sd, 'shot', None) and getattr(last_sd.shot, 'distance', None) is not None:
                final_distance = float(last_sd.shot.distance)
        except Exception:
            final_distance = None
        return JsonResponse({'ok': True, 'shots_updated': updated, 'hole_pin': pin_obj, 'final_distance_yards': final_distance, 'per_shot': shot_reports})
    except Exception as e:
        logger.exception('Error in save_hole_pin')
        return JsonResponse({'ok': False, 'error': str(e)}, status=500)


@login_required
@require_POST
def last_shot_landing(request, hole_id):
    """API: Accept a landing coordinate for the last ShotDistance on a hole.

    Behavior:
    - Identifies the last ShotDistance for the given hole owned by the user
      (ordered by created_at desc).
    - Sets landing_lat and landing_lng on that ShotDistance and saves it.
    - Calls the existing compute_shot_distance() utility to compute yards.
    - Persists the computed yards onto the related ShotAnalysis.distance field
      (ShotDistance model is additive and currently does not store a yards
      column; storing on ShotAnalysis keeps the computed value durable without
      requiring a DB schema change).
    - Returns JSON {ok: true, distance_yards: <float>} on success.

    Notes: We intentionally avoid duplicating the haversine logic in JS and
    reuse the server-side utility in `utils.shot_distance.compute_shot_distance`.
    """
    try:
        lat = request.POST.get('landing_lat') or request.POST.get('lat')
        lng = request.POST.get('landing_lng') or request.POST.get('lng')
        if lat is None or lng is None:
            return JsonResponse({'ok': False, 'error': 'Missing coordinates'}, status=400)
        try:
            lat_f = float(lat)
            lng_f = float(lng)
        except Exception:
            return JsonResponse({'ok': False, 'error': 'Invalid coordinate format'}, status=400)

        from .models import ShotDistance
        # Find the most recent ShotDistance for this hole belonging to the user.
        sd = ShotDistance.objects.filter(shot__user=request.user, hole_number=hole_id).order_by('-created_at').first()
        if not sd:
            # If no ShotDistance exists yet, we can't sensibly compute a distance
            return JsonResponse({'ok': False, 'error': 'No shot origin found for this hole'}, status=404)

        # Save landing coords
        sd.landing_lat = lat_f
        sd.landing_lng = lng_f
        sd.save()

        # Compute distance using existing server-side utility
        from utils.shot_distance import compute_shot_distance
        yards = compute_shot_distance(sd)

        # Persist computed yards on the related ShotAnalysis distance field so the
        # value is durable and visible elsewhere in the app. This avoids schema
        # changes while keeping shot data server-authoritative.
        if yards is not None:
            try:
                sa = sd.shot
                sa.distance = float(yards)
                sa.save()
            except Exception:
                # Non-fatal: continue even if saving to ShotAnalysis fails
                pass

        return JsonResponse({'ok': True, 'distance_yards': yards})
    except Exception as e:
        logger.exception('Error in last_shot_landing')
        return JsonResponse({'ok': False, 'error': str(e)}, status=500)


def fetch_hole_info(course_name, hole, preferred_tee=None):
    """Query the Golf Course API for a specific hole and return yardage, par, handicap and used_tee.

    Returns a dict: {'yardage': int|None, 'par': int|None, 'handicap': int|None, 'used_tee': str|None}
    """
    api_key = GOLF_COURSE_API_KEY_HARDCODED or os.environ.get('GOLF_COURSE_API_KEY')
    if not api_key:
        return {}

    try:
        api_url = 'https://api.golfcourseapi.com/v1/search'
        resp = requests.get(api_url, params={'search_query': course_name}, headers={'Authorization': f'Key {api_key}'}, timeout=8)
        if resp.status_code != 200:
            return {}
        payload = resp.json()

        def _extract(obj, hole_num, preferred_tee=None):
            try:
                # Handle 'tees' structured responses (group -> list of tees -> holes)
                if isinstance(obj, dict):
                    if 'tees' in obj and isinstance(obj.get('tees'), dict):
                        for group_name, tee_list in obj.get('tees').items():
                            if isinstance(tee_list, list):
                                # preferred tee match first
                                if preferred_tee:
                                    for tee in tee_list:
                                        tn = (tee.get('tee_name') or '').lower()
                                        if _tee_matches(preferred_tee, tn):
                                            holes = tee.get('holes')
                                            if isinstance(holes, list):
                                                idx = int(hole_num) - 1
                                                if 0 <= idx < len(holes):
                                                    he = holes[idx]
                                                    y = he.get('yardage') or he.get('yards') or he.get('length')
                                                    p = he.get('par') or he.get('par_value') or he.get('par_total')
                                                    hc = he.get('handicap') or he.get('hcp') or he.get('stroke_index')
                                                    return (y, p, hc, f"{tee.get('tee_name')}")
                                # generic tee list fallback
                                for tee in tee_list:
                                    holes = tee.get('holes')
                                    if isinstance(holes, list):
                                        idx = int(hole_num) - 1
                                        if 0 <= idx < len(holes):
                                            he = holes[idx]
                                            y = he.get('yardage') or he.get('yards') or he.get('length')
                                            p = he.get('par') or he.get('par_value') or he.get('par_total')
                                            hc = he.get('handicap') or he.get('hcp') or he.get('stroke_index')
                                            return (y, p, hc, f"{group_name}.{tee.get('tee_name')}")

                    # Handle a top-level 'holes' array
                    if 'holes' in obj and isinstance(obj.get('holes'), list):
                        holes = obj.get('holes')
                        idx = int(hole_num) - 1
                        if 0 <= idx < len(holes):
                            he = holes[idx]
                            y = he.get('yardage') or he.get('yards') or he.get('length')
                            p = he.get('par') or he.get('par_value') or he.get('par_total')
                            hc = he.get('handicap') or he.get('hcp') or he.get('stroke_index')
                            return (y, p, hc, None)

                    # Some APIs include hole dicts with a 'number' field
                    possible_num = None
                    for k in ('number', 'hole', 'hole_number'):
                        if k in obj:
                            possible_num = obj.get(k)
                            break
                    if possible_num is not None:
                        try:
                            if int(possible_num) == int(hole_num):
                                for yk in ('yardage', 'yards', 'length', 'tee_yards'):
                                    if yk in obj and obj.get(yk) is not None:
                                        try:
                                            yv = int(obj.get(yk))
                                            p = obj.get('par') or obj.get('par_value') or obj.get('par_total')
                                            try:
                                                p_val = int(p) if p is not None else None
                                            except Exception:
                                                p_val = None
                                            hc = obj.get('handicap') or obj.get('hcp') or obj.get('stroke_index')
                                            try:
                                                hc_val = int(hc) if hc is not None else None
                                            except Exception:
                                                hc_val = None
                                            return (yv, p_val, hc_val, None)
                                        except Exception:
                                            pass
                        except Exception:
                            pass

                    # Recurse into values
                    for v in obj.values():
                        res = _extract(v, hole_num, preferred_tee)
                        if res is not None:
                            return res

                # Lists: iterate and try to match index or recurse
                if isinstance(obj, list):
                    # If it's a list of hole dicts indexed by hole number
                    if len(obj) > 0 and all(isinstance(it, dict) for it in obj):
                        try:
                            idx = int(hole_num) - 1
                            if 0 <= idx < len(obj):
                                he = obj[idx]
                                y = he.get('yardage') or he.get('yards') or he.get('length')
                                p = he.get('par') or he.get('par_value') or he.get('par_total')
                                hc = he.get('handicap') or he.get('hcp') or he.get('stroke_index')
                                return (y, p, hc, None)
                        except Exception:
                            pass
                    for item in obj:
                        res = _extract(item, hole_num, preferred_tee)
                        if res is not None:
                            return res
                return None
            except Exception:
                return None

        res = _extract(payload, hole, preferred_tee)
        if res:
            y, p, hc, used = res
            try:
                y_val = int(y) if y is not None else None
            except Exception:
                y_val = None
            try:
                p_val = int(p) if p is not None else None
            except Exception:
                p_val = None
            try:
                hc_val = int(hc) if hc is not None else None
            except Exception:
                hc_val = None
            return {'yardage': y_val, 'par': p_val, 'handicap': hc_val, 'used_tee': used}
    except Exception:
        pass
    return {}


# ---------------------------------------------------------------------------
# AI Coach chat endpoint
# ---------------------------------------------------------------------------

@login_required
def ai_coach_chat(request, pk):
    """Accept a follow-up question and return a contextual AI coaching answer.

    POST body (JSON): {"question": "..."}
    Response (JSON): {"answer": "..."} or {"error": "..."}
    """
    import json as _json
    from django.http import JsonResponse
    from .models import ShotAnalysis

    if request.method != 'POST':
        return JsonResponse({'error': 'POST required'}, status=405)

    sa = get_object_or_404(ShotAnalysis, pk=pk, user=request.user)

    try:
        body = _json.loads(request.body)
        question = (body.get('question') or '').strip()
    except Exception:
        return JsonResponse({'error': 'Invalid JSON body'}, status=400)

    if not question:
        return JsonResponse({'error': 'Question is required'}, status=400)

    if len(question) > 500:
        return JsonResponse({'error': 'Question too long (max 500 characters)'}, status=400)

    try:
        from .ai.chat_agent import answer_question
        answer = answer_question(question, sa.pk, request.user.pk)
        return JsonResponse({'answer': answer})
    except Exception:
        logger.exception('ai_coach_chat: unexpected error for analysis %s', pk)
        return JsonResponse({'error': 'Could not process your question. Please try again.'}, status=500)


# ==============================================================================
# QUICK UPLOAD MODE
# Lightweight upload flow that bypasses Course → Round → Hole setup.
# Reuses the full existing AI pipeline (metrics, scoring, coaching, memory).
# ==============================================================================

@login_required
def quick_upload(request):
    """Render and handle the Quick Upload form.

    On POST: creates a ShotAnalysis with is_quick_upload=True, queues the
    existing background processing task, then redirects to the detail page.
    No course, round, or hole is required.
    """
    from .forms import QuickUploadForm

    if request.method == 'POST':
        form = QuickUploadForm(request.POST, request.FILES)
        if form.is_valid():
            video_file = form.cleaned_data['input_video']
            club = (form.cleaned_data.get('club') or '').strip() or 'Unknown'
            notes = (form.cleaned_data.get('notes') or '').strip()

            try:
                import tempfile as _tempfile
                sa = ShotAnalysis(
                    user=request.user,
                    club=club,
                    distance=0.0,          # not required for quick uploads
                    is_quick_upload=True,
                    status='uploading',
                )
                sa.input_video.save(video_file.name, video_file, save=True)

                # Resolve input path — S3-backed files raise NotImplementedError on .path
                try:
                    task_input = sa.input_video.path
                except (NotImplementedError, ValueError):
                    task_input = sa.input_video.url

                # Best-effort thumbnail
                try:
                    import uuid as _uuid
                    thumb_name = f"thumb_{_uuid.uuid4().hex}.jpg"
                    _thumb_root = str(settings.MEDIA_ROOT) if settings.MEDIA_ROOT else _tempfile.gettempdir()
                    thumb_path = os.path.join(_thumb_root, 'thumbnails', thumb_name)
                    os.makedirs(os.path.dirname(thumb_path), exist_ok=True)
                    result = subprocess.run(
                        [FFMPEG_PATH, '-y', '-i', task_input,
                         '-ss', '00:00:01', '-vframes', '1',
                         '-vf', 'scale=480:-2', thumb_path],
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    )
                    if result.returncode == 0 and os.path.exists(thumb_path):
                        with open(thumb_path, 'rb') as tf:
                            sa.thumbnail.save(thumb_name, File(tf), save=False)
                except Exception:
                    pass

                sa.save()

                # Queue the full processing pipeline (same task as round uploads)
                base_name = os.path.splitext(os.path.basename(sa.input_video.name))[0]
                _out_root = str(settings.MEDIA_ROOT) if settings.MEDIA_ROOT else _tempfile.gettempdir()
                output_path = os.path.join(_out_root, 'output', f"{base_name}_processed.mp4")
                async_task(
                    'shots.tasks.process_video_background',
                    sa.pk, task_input, output_path, None,
                )

                return redirect('shots:quick_swing_detail', pk=sa.pk)

            except Exception:
                logger.exception('quick_upload: failed to create ShotAnalysis')
                form.add_error(None, 'Upload failed — please try again.')
    else:
        form = QuickUploadForm()

    return render(request, 'shots/quick_upload.html', {'form': form})


@login_required
def quick_swings(request):
    """Library of all quick-upload swings for the logged-in user.

    Supports optional GET filters:
        club        — exact club name
        shape       — shot shape string (straight, draw, fade, slice, hook…)
        score_min   — minimum overall AI score (0-100)
        score_max   — maximum overall AI score (0-100)
    """
    from django.core.paginator import Paginator

    qs = ShotAnalysis.objects.filter(
        user=request.user,
        is_quick_upload=True,
    ).order_by('-created_at')

    # Filtering
    club_filter = request.GET.get('club', '').strip()
    shape_filter = request.GET.get('shape', '').strip().lower()
    score_min = request.GET.get('score_min', '').strip()
    score_max = request.GET.get('score_max', '').strip()

    if club_filter:
        qs = qs.filter(club__iexact=club_filter)
    if shape_filter:
        qs = qs.filter(ai_shot_shape__iexact=shape_filter)
    try:
        if score_min:
            qs = qs.filter(ai_overall_score__gte=int(score_min))
    except (ValueError, TypeError):
        score_min = ''
    try:
        if score_max:
            qs = qs.filter(ai_overall_score__lte=int(score_max))
    except (ValueError, TypeError):
        score_max = ''

    paginator = Paginator(qs, 12)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    # Build distinct club list for filter dropdown
    from .forms import CLUB_CHOICES
    available_clubs = [c[0] for c in CLUB_CHOICES if c[0]]

    shot_shapes = ['straight', 'draw', 'fade', 'slice', 'hook', 'push', 'pull']

    return render(request, 'shots/quick_swings.html', {
        'page_obj': page_obj,
        'available_clubs': available_clubs,
        'shot_shapes': shot_shapes,
        'club_filter': club_filter,
        'shape_filter': shape_filter,
        'score_min': score_min,
        'score_max': score_max,
        'total_count': qs.count(),
    })


@login_required
def quick_swing_detail(request, pk):
    """Full AI analysis detail page for a quick-upload swing."""
    sa = get_object_or_404(ShotAnalysis, pk=pk, user=request.user, is_quick_upload=True)
    return render(request, 'shots/quick_swing_detail.html', {
        'analysis': sa,
        'overlay_status_url': reverse('shots:overlay_status', args=[sa.pk]),
        'chat_url': reverse('shots:ai_coach_chat', args=[sa.pk]),
    })


@login_required
@require_POST
def quick_reprocess(request, pk):
    """Trigger overlay reprocessing for a quick-upload swing.

    Accepts POST fields:
        wireframe  — '1' to include pose skeleton overlay, '0' to exclude
        map        — '1' to include Mapbox GPS map overlay, '0' to exclude

    Both can be '1' simultaneously. Both '0' reprocesses to a clean video.
    Course/hole text overlays are never applied to quick uploads.
    """
    sa = get_object_or_404(ShotAnalysis, pk=pk, user=request.user, is_quick_upload=True)

    want_wireframe = request.POST.get('wireframe', '0') == '1'
    want_map = request.POST.get('map', '0') == '1'

    sa.overlay_requested = want_wireframe
    sa.include_map = want_map
    sa.include_course_text = False
    sa.overlay_status = 'pending'
    sa.status = 'processing'
    sa.overlay_error_message = ''
    sa.save()

    try:
        if not sa.input_video:
            return JsonResponse({'error': 'No input video available'}, status=400)
        try:
            input_path = sa.input_video.path
        except (NotImplementedError, ValueError):
            input_path = sa.input_video.url

        import tempfile as _tempfile
        _out_root = str(settings.MEDIA_ROOT) if settings.MEDIA_ROOT else _tempfile.gettempdir()
        output_path = os.path.join(_out_root, 'output', f"quick_reprocess_{sa.pk}.mp4")
        async_task(
            'shots.tasks.process_video_background',
            sa.pk, input_path, output_path, None,
        )
    except Exception as e:
        logger.exception('quick_reprocess: failed to queue task for analysis %s', pk)
        return JsonResponse({'error': str(e)}, status=500)

    return JsonResponse({'status': 'queued'})
