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
import threading
import requests
import urllib.parse
import logging
import re


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
        # Call ffprobe to get format tags
        cmd = [FFMPEG_PATH or 'ffprobe', '-v', 'quiet', '-print_format', 'json', '-show_format', path]
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


def process_video_background(analysis_pk, input_path, output_path, hole_par=None):
    """Background worker to process a video file and attach the processed file to the ShotAnalysis.

    Updates ShotAnalysis.status and error_message fields.
    """
    try:
        sa = ShotAnalysis.objects.get(pk=analysis_pk)
        sa.status = 'processing'
        sa.save()

        logger.info(f"Background processing started for analysis {analysis_pk}: {input_path} -> {output_path}")

        # Run the overlay processing (wrap any exceptions)
        try:
            process_video_with_overlay(
                input_path,
                output_path,
                None,
                sa.course_name,
                sa.hole_number,
                sa.hole_yardage,
                sa.club,
                hole_par=hole_par,
                overlay_map_requested=getattr(sa, 'include_map', False),
                include_course_text=getattr(sa, 'include_course_text', False)
            )
        except Exception as e:
            logger.exception('Overlay/map processing failed for analysis %s', analysis_pk)
            sa.status = 'failed'
            sa.error_message = f'Overlay processing failed: {e}'
            sa.save()
            return

        # Attach processed file to model
        if os.path.exists(output_path):
            with open(output_path, 'rb') as f:
                sa.processed_video.save(os.path.basename(output_path), File(f), save=False)

        # If user requested a pose overlay, render it onto the processed video file
        # We render to a temporary file first, then replace the processed_video with
        # the overlayed result so the user sees a single processed video (no separate
        # overlayed_video file).
        if getattr(sa, 'overlay_requested', False):
            sa.overlay_status = 'overlaying'
            sa.save()
            try:
                from .video_processing import render_pose_wireframe
                import tempfile
                fd, overlay_tmp = tempfile.mkstemp(suffix='.mp4')
                os.close(fd)
                try:
                    overlay_path = render_pose_wireframe(output_path, output_path=overlay_tmp)
                    if overlay_path and os.path.exists(overlay_path):
                        # Only attach the overlayed file if it is non-empty. Some renderer
                        # failures leave an empty file behind; we must avoid overwriting
                        # a valid processed video with a zero-byte file.
                        try:
                            if os.path.getsize(overlay_path) > 0:
                                with open(overlay_path, 'rb') as ofp:
                                    # Use the same filename as the original processed output so URLs remain stable.
                                    sa.processed_video.save(os.path.basename(output_path), File(ofp), save=False)
                                sa.overlay_status = 'completed'
                                sa.overlay_error_message = ''
                            else:
                                sa.overlay_status = 'failed'
                                sa.overlay_error_message = 'Overlay renderer produced an empty file; processed video preserved.'
                        except Exception as e:
                            sa.overlay_status = 'failed'
                            sa.overlay_error_message = f'Failed to attach overlayed file: {e}'
                    else:
                        sa.overlay_status = 'failed'
                        sa.overlay_error_message = 'Overlay renderer did not produce output.'
                except Exception as e:
                    sa.overlay_status = 'failed'
                    sa.overlay_error_message = str(e)
                finally:
                    try:
                        if os.path.exists(overlay_tmp):
                            os.remove(overlay_tmp)
                    except Exception:
                        pass
            except Exception as e:
                sa.overlay_status = 'failed'
                sa.overlay_error_message = str(e)
            finally:
                try:
                    sa.save()
                except Exception:
                    pass
        # Persist hole_par to the DB in case it was provided transiently
        try:
            if hole_par is not None:
                sa.hole_par = int(hole_par)
        except Exception:
            # Ignore parsing errors for safety
            pass
        sa.status = 'completed'
        sa.error_message = ''
        sa.save()
        logger.info(f"Background processing completed for analysis {analysis_pk}")
    except Exception as e:
        logger.exception("Error in background video processing")
        try:
            sa = ShotAnalysis.objects.get(pk=analysis_pk)
            sa.status = 'failed'
            sa.error_message = str(e)
            sa.save()
        except Exception:
            logger.exception('Failed to save ShotAnalysis after processing error')


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
    shots = Shot.objects.order_by('-created_at')[:100]
    count = shots.count()
    avg_distance = shots.aggregate_avg = None
    if count:
        try:
            avg_distance = sum(s.distance for s in shots) / count
        except Exception:
            avg_distance = None
    context = {
        'shots': shots,
        'count': count,
        'avg_distance': avg_distance,
    }
    return render(request, 'shots/home.html', context)


def create_shot(request):
    if request.method == 'POST':
        form = ShotForm(request.POST, request.FILES)
        if form.is_valid():
            shot = form.save(commit=False)
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

        form = ShotAnalysisForm(request.POST, request.FILES)
        try:
            # Inject dynamic choices into the bound form before validation
            form.fields['selected_tee'].choices = combined
        except Exception:
            pass
        if form.is_valid():
            # Save the form to create the analysis object
            analysis = form.save(commit=False)
            
            # Get the uploaded file
            uploaded_file = request.FILES.get('input_video')
            
            if uploaded_file:
                # Save the uploaded file to the input_video field (saves to MEDIA_ROOT/input/)
                analysis.input_video.save(uploaded_file.name, uploaded_file, save=False)
                
                try:
                    # Get the full path to the uploaded file
                    input_path = analysis.input_video.path
                    
                    # Generate output filename (same base name as input)
                    base_name = os.path.splitext(os.path.basename(uploaded_file.name))[0]
                    output_filename = f"{base_name}_processed.mp4"
                    output_path = os.path.join(settings.MEDIA_ROOT, 'output', output_filename)
                    
                    # Call the overlay processing function and wait for it to finish
                    try:
                        import logging
                        logger = logging.getLogger(__name__)
                        logger.info(f"Starting video processing: {input_path} -> {output_path}")

                        # If the user requested a pose overlay, run the renderer first
                        try:
                            overlay_requested = bool(request.POST.get('overlay_pose'))
                        except Exception:
                            overlay_requested = False
                        processed_input = input_path
                        if overlay_requested:
                            try:
                                logger.info(f"Generating pose overlay for: {input_path}")
                                overlay_path = render_pose_wireframe(input_path)
                                if overlay_path and os.path.exists(overlay_path):
                                    processed_input = overlay_path
                                    logger.info(f"Pose overlay written to: {overlay_path}")
                            except Exception as e:
                                logger.exception('Pose overlay generation failed, continuing without overlay')

                        process_video_with_overlay(processed_input, output_path)

                        logger.info(f"Video processing completed: {output_path}")
                        
                        # Record overlay preference and save processed video to the model
                        try:
                            analysis.overlay_requested = overlay_requested
                            analysis.overlay_status = 'pending'
                        except Exception:
                            pass
                        with open(output_path, 'rb') as f:
                            analysis.processed_video.save(output_filename, File(f), save=False)
                        
                        # Save the analysis to the database
                        analysis.save()

                        # Success! Redirect to the round page if this analysis was attached
                        # to a round; otherwise go to the analysis detail page.
                        messages.success(request, 'Video processed successfully!')
                        try:
                            if getattr(analysis, 'round', None):
                                return redirect('shots:round_holes', round_pk=analysis.round.pk)
                        except Exception:
                            # fallback to analysis detail on any error
                            pass
                        return redirect('shots:analysis_detail', pk=analysis.pk)
                        
                    except FileNotFoundError as e:
                        # Processing failed - file not found
                        import logging
                        logger = logging.getLogger(__name__)
                        logger.error(f'File not found during processing: {str(e)}')
                        messages.error(request, f'Video processing failed: Required file not found - {str(e)}')
                        # Save the analysis anyway (without processed video)
                        analysis.save()
                        return redirect('shots:analysis_detail', pk=analysis.pk)
                    except Exception as e:
                        # Processing failed - show error message
                        import logging
                        import traceback
                        logger = logging.getLogger(__name__)
                        logger.error(f'Video processing failed: {str(e)}\n{traceback.format_exc()}')
                        messages.error(request, f'Video processing failed: {str(e)}')
                        # Save the analysis anyway (without processed video)
                        analysis.save()
                        return redirect('shots:analysis_detail', pk=analysis.pk)
                        
                except Exception as e:
                    # Error accessing the uploaded file
                    messages.error(request, f'Error saving video: {str(e)}')
                    return render(request, 'shots/analyze_form.html', {'form': form})
            else:
                messages.error(request, 'No video file uploaded.')
                return render(request, 'shots/analyze_form.html', {'form': form})
    else:
        form = ShotAnalysisForm()
    
    # Provide existing rounds for the user so they can attach uploads to a round
    rounds = []
    try:
        from .models import ShotRound
        rounds = ShotRound.objects.filter(user=request.user).order_by('-played_at', '-created_at')[:50]
        try:
            logger.info(f"analyze_upload: found rounds for user {getattr(request.user,'pk',None)} -> {[r.pk for r in rounds]}")
        except Exception:
            logger.info("analyze_upload: found rounds (unable to list ids)")
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


def analysis_detail(request, pk):
    """Display the analysis detail page showing both original and processed videos."""
    analysis = get_object_or_404(ShotAnalysis, pk=pk)
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

    return render(request, 'shots/analysis_detail.html', {'analysis': analysis, 'overlay_info': overlay_info})


from django.http import JsonResponse

@login_required
def overlay_status(request, pk):
    """Return JSON with overlay status for a ShotAnalysis (used for frontend polling)."""
    sa = get_object_or_404(ShotAnalysis, pk=pk)
    if sa.user != request.user:
        return JsonResponse({'error': 'forbidden'}, status=403)
    return JsonResponse({'overlay_status': sa.overlay_status or 'pending', 'overlay_error': sa.overlay_error_message or ''})


from django.contrib.auth.decorators import login_required

@login_required
@login_required
def shot_list(request):
    """Show all uploaded shot videos for the logged-in user."""
    # Only show shots marked as favorites on the shots index (shared shots)
    analyses = ShotAnalysis.objects.filter(user=request.user, is_favorite=True).order_by('-created_at')[:200]
    return render(request, 'shots/shot_list.html', {'analyses': analyses})


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
        # Prefer explicit next param, otherwise fall back to HTTP_REFERER, then to shots list
        redirect_to = request.POST.get('next') or request.GET.get('next') or request.META.get('HTTP_REFERER')
        if not redirect_to:
            try:
                from django.urls import reverse
                redirect_to = reverse('shots:shot_list')
            except Exception:
                redirect_to = '/shots/'
        return redirect(redirect_to)

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
    course_items = [{'name': c['course_name'], 'slug': slugify(c['course_name']), 'count': c['count']} for c in courses]
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
    """Render analyze form with the course preselected/locked. POST still handled by analyze_upload.
    This view only renders GET; the form posts to /analyze/ unchanged.
    """
    from .models import Course
    course = get_object_or_404(Course, pk=pk, user=request.user)
    form = ShotAnalysisForm()
    # existing rounds for attach list - only rounds played at this course
    from .models import ShotRound
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

    return render(request, 'shots/analyze_form.html', {
        'form': form,
        'rounds': rounds,
        'fixed_course': True,
        'fixed_course_obj': course,
        'fixed_course_name': course.name,
        'selected_round_id': selected_round,
        'prefetched_tee_names': ordered,
        'initial_course': course.name,
    })


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
    return render(request, 'shots/rounds_list.html', {'rounds': rounds, 'course_slug': course_slug, 'fixed_course_name': fixed_course_name})


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
        return redirect(request.META.get('HTTP_REFERER', 'shots:rounds_list'))

    round_obj = get_object_or_404(ShotRound, pk=round_pk)
    if round_obj.user_id != getattr(request.user, 'pk', None):
        messages.error(request, 'You do not have permission to delete this round.')
        return redirect(request.META.get('HTTP_REFERER', 'shots:rounds_list'))

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

    return redirect(request.META.get('HTTP_REFERER', 'shots:shot_list'))


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
            age = datetime.datetime.utcnow() - cm.fetched_at.replace(tzinfo=None)
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
        analyses = ShotAnalysis.objects.filter(user=request.user, course_name=course_name, hole_number=hole).order_by('-created_at')
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
    analyses = ShotAnalysis.objects.filter(user=request.user, round=r, hole_number=hole).order_by('-created_at')
    # Try to fetch hole-specific info (yardage, par, handicap) from the Golf Course API.
    hole_info = {}
    try:
        if r.course_name:
            hole_info = fetch_hole_info(r.course_name, hole)
    except Exception:
        hole_info = {}

    return render(request, 'shots/hole_shots.html', {'analyses': analyses, 'course_name': r.course_name or '', 'hole': hole, 'course_slug': slugify(r.course_name) if r.course_name else '', 'hole_info': hole_info, 'round': r})


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





@login_required
def analyze_upload(request):
    """Handle uploading a video, read course/hole inputs, start background processing, and return result.

    This view saves the uploaded file, starts background processing (so the request doesn't block),
    queries the Golf Course API to obtain hole yardage (if the user provided course + hole),
    and redirects to the analysis detail page including course/hole/yardage in query params so
    the frontend overlay can show them immediately.
    """
    if request.method == 'POST':
        # Respect user opt-in for map/text overlays
        include_map = bool(request.POST.get('include_map'))
        include_text = bool(request.POST.get('include_course_text'))

        # Ensure the bound form accepts dynamic tee names returned by the Golf Course API
        course_candidate = (request.POST.get('course') or request.GET.get('course')) if include_map else None
        prefetched_tee_names = []
        try:
            api_key = GOLF_COURSE_API_KEY_HARDCODED or os.environ.get('GOLF_COURSE_API_KEY')
            if include_map and api_key and course_candidate:
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

        static_choices = getattr(ShotAnalysisForm, 'TEE_CHOICES', []) or []
        seen = set()
        combined = [('', 'Any')]
        for n in prefetched_tee_names:
            if n and n not in seen:
                seen.add(n)
                combined.append((n, n))
        for val, label in static_choices:
            if val and val not in seen:
                seen.add(val)
                combined.append((val, label))

        form = ShotAnalysisForm(request.POST, request.FILES)
        try:
            form.fields['selected_tee'].choices = combined
        except Exception:
            pass
        try:
            logger.info(f"analyze_upload POST start: user={getattr(request.user,'pk',None)} form_valid_attempt")
        except Exception:
            pass
        if form.is_valid():
            try:
                logger.info("analyze_upload: form.is_valid() == True")
            except Exception:
                pass
            # Read optional fields from POST (apply to all uploaded files)
            course_name = request.POST.get('course', '').strip() or None
            hole_str = request.POST.get('hole', '').strip() or None
            selected_tee = request.POST.get('selected_tee', '').strip() or None
            try:
                hole_number = int(hole_str) if hole_str else None
            except Exception:
                hole_number = None

            # Round handling: allow user to attach uploads to an existing round or create a new one
            round_obj = None
            try:
                round_id = request.POST.get('round_id')
                new_round_name = request.POST.get('new_round_name', '').strip() or None
                new_round_played_at = request.POST.get('new_round_played_at', '').strip() or None
                if round_id:
                    try:
                        from .models import ShotRound
                        round_obj = ShotRound.objects.filter(pk=int(round_id), user_id=getattr(request.user, 'pk', None)).first()
                        if round_obj:
                            logger.info(f"Using existing round {round_obj.pk} for user {request.user.pk}")
                            try:
                                messages.info(request, f"Using existing round: {round_obj.name or round_obj.pk}")
                            except Exception:
                                pass
                    except Exception:
                        round_obj = None
                elif new_round_name or new_round_played_at:
                    from .models import ShotRound
                    try:
                        played_at_dt = None
                        if new_round_played_at:
                            from dateutil import parser as _dp
                            try:
                                played_at_dt = _dp.parse(new_round_played_at)
                                if played_at_dt.tzinfo:
                                    import datetime as _dt
                                    played_at_dt = played_at_dt.astimezone(_dt.timezone.utc).replace(tzinfo=None)
                            except Exception:
                                played_at_dt = None
                        round_obj = ShotRound.objects.create(user=request.user, name=new_round_name or None, course_name=course_name, hole_number=hole_number, played_at=played_at_dt)
                        logger.info(f"Created new round {round_obj.pk} name={round_obj.name!r} user={request.user.pk}")
                        try:
                            messages.success(request, f"Created new round: {round_obj.name or round_obj.pk}")
                        except Exception:
                            pass
                    except Exception:
                        round_obj = None
            except Exception:
                round_obj = None

            uploaded_files = request.FILES.getlist('input_video') or []
            try:
                logger.info(f"analyze_upload: uploaded_files count={len(uploaded_files)}")
            except Exception:
                pass
            if not uploaded_files:
                messages.error(request, 'No video file uploaded.')
                try:
                    logger.warning('analyze_upload: no uploaded_files found in POST')
                except Exception:
                    pass
                return render(request, 'shots/analyze_form.html', {'form': form})

            # Server-side defensive check: ensure per-file club and distance are provided.
            # The client names per-file inputs using the ORIGINAL upload index (club_0, distance_0),
            # but Django's uploaded_files order may differ. Therefore detect indices from POST.
            import re
            idxs = set()
            for k in request.POST.keys():
                m = re.match(r'^(?:club|distance)_(\d+)$', k)
                if m:
                    try:
                        idxs.add(int(m.group(1)))
                    except Exception:
                        pass

            try:
                logger.info(f"analyze_upload: detected per-file indices in POST: {sorted(list(idxs))}")
            except Exception:
                pass

            missing_meta = []
            if idxs:
                for idx in sorted(idxs):
                    club_val = (request.POST.get(f'club_{idx}', '') or '').strip()
                    dist_val = (request.POST.get(f'distance_{idx}', '') or '').strip()
                    if not club_val or not dist_val:
                        missing_meta.append(idx)
            else:
                # fallback: ensure at least one club/distance exists when files were uploaded
                for idx, _ in enumerate(uploaded_files):
                    club_val = (request.POST.get(f'club_{idx}', '') or '').strip()
                    dist_val = (request.POST.get(f'distance_{idx}', '') or '').strip()
                    if not club_val or not dist_val:
                        missing_meta.append(idx)

            if missing_meta:
                messages.error(request, 'Please select a club and provide a distance (yards) for each selected video before analyzing.')
                # Re-render the form with existing rounds and context so the user can correct entries
                rounds = []
                try:
                    from .models import ShotRound, Course
                    rounds = ShotRound.objects.filter(user_id=getattr(request.user, 'pk', None)).order_by('-played_at', '-created_at')[:50]
                except Exception:
                    rounds = []

                # Preserve fixed course context when available (add-round flow passes course hidden input)
                context = {'form': form, 'rounds': rounds}
                try:
                    course_name_post = request.POST.get('course', '').strip() or None
                    if course_name_post:
                        from .models import Course
                        cobj = Course.objects.filter(user=request.user, name=course_name_post).first()
                        if cobj:
                            context['fixed_course'] = True
                            context['fixed_course_obj'] = cobj
                        else:
                            # still pass the course string so the input remains filled
                            context['course'] = course_name_post
                except Exception:
                    pass

                try:
                    logger.warning(f"analyze_upload: missing_meta indices={missing_meta}; re-rendering analyze_form")
                except Exception:
                    pass
                return render(request, 'shots/analyze_form.html', context)

            created_pks = []
            # Determine global club/distance from form.cleaned_data if present
            try:
                global_club = form.cleaned_data.get('club')
                global_distance = form.cleaned_data.get('distance')
            except Exception:
                global_club = None
                global_distance = None

            # Build (uploaded_file, capture_time, original_index) list
            file_time_pairs = []
            for idx, uploaded_file in enumerate(uploaded_files):
                # temporarily save to a temp path to allow probing if file-like doesn't have path
                tmp_path = None
                try:
                    # If InMemoryUploadedFile, save to temp location
                    if hasattr(uploaded_file, 'temporary_file_path'):
                        tmp_path = uploaded_file.temporary_file_path()
                    else:
                        # write to a temp file in MEDIA_ROOT/input_tmp
                        tmp_dir = os.path.join(settings.MEDIA_ROOT, 'input_tmp')
                        os.makedirs(tmp_dir, exist_ok=True)
                        tmp_path = os.path.join(tmp_dir, f"upload_{uuid.uuid4().hex}_{uploaded_file.name}")
                        with open(tmp_path, 'wb') as tf:
                            for chunk in uploaded_file.chunks():
                                tf.write(chunk)
                except Exception:
                    tmp_path = None
                try:
                    ts = probe_video_creation_time(tmp_path) if tmp_path else None
                except Exception:
                    ts = None
                # include original index so we can read per-file metadata (club_0, distance_0)
                file_time_pairs.append({'file': uploaded_file, 'tmp_path': tmp_path, 'timestamp': ts, 'index': idx})

            # Sort by timestamp ascending (None treated as far future so it appears last)
            import datetime
            def _sort_key(item):
                if item['timestamp'] is None:
                    return datetime.datetime.max
                return item['timestamp']

            file_time_pairs.sort(key=_sort_key)

            # Assign stroke numbers starting at 1 based on sorted order
            processing_queue = []
            for stroke_num, pair in enumerate(file_time_pairs, start=1):
                uploaded_file = pair['file']
                tmp_path = pair.get('tmp_path')
                original_index = pair.get('index')
                # Per-file metadata keys use the original upload index (club_0, distance_0)
                per_club = request.POST.get(f'club_{original_index}', '').strip() or None
                per_distance_raw = request.POST.get(f'distance_{original_index}', '').strip() or None
                try:
                    per_distance = float(per_distance_raw) if per_distance_raw else None
                except Exception:
                    per_distance = None
                # Create a new ShotAnalysis instance per uploaded file
                analysis = ShotAnalysis()
                analysis.user = request.user
                # copy fields from form.cleaned_data where present
                try:
                    cleaned = form.cleaned_data
                except Exception:
                    cleaned = {}
                # Use per-file values if provided, otherwise fall back to global values
                analysis.club = per_club or global_club or (cleaned.get('club') if cleaned else None)
                analysis.distance = per_distance if per_distance is not None else (global_distance if global_distance is not None else (cleaned.get('distance') if cleaned else None))

                # Save uploaded file to model (this writes to MEDIA_ROOT/input/)
                analysis.input_video.save(uploaded_file.name, uploaded_file, save=False)

                # Probe the saved file with ffprobe to extract authoritative creation_time
                try:
                    saved_path = analysis.input_video.path
                    probe_dt = probe_video_creation_time(saved_path)
                    if probe_dt:
                        analysis.probe_creation_time = probe_dt
                except Exception:
                    # don't block upload/process on probe failures
                    pass

                # Read client-side selection timestamp (upload_time_{original_index}) and store it
                try:
                    upload_time_raw = request.POST.get(f'upload_time_{original_index}', '').strip() or None
                    if upload_time_raw:
                        from dateutil import parser as _dp
                        try:
                            dt = _dp.parse(upload_time_raw)
                            # Convert aware to naive UTC
                            import datetime as _dt
                            if dt.tzinfo:
                                dt = dt.astimezone(_dt.timezone.utc).replace(tzinfo=None)
                            analysis.client_added_time = dt
                        except Exception:
                            pass
                except Exception:
                    pass

                # Attach round if one was selected/created
                try:
                    if round_obj:
                        analysis.round = round_obj
                except Exception:
                    pass

                # Generate thumbnail per file (best-effort)
                try:
                    base_name = os.path.splitext(os.path.basename(uploaded_file.name))[0]
                    thumb_dir = os.path.join(settings.MEDIA_ROOT, 'thumbnails')
                    os.makedirs(thumb_dir, exist_ok=True)
                    thumb_filename = f"{base_name}.jpg"
                    thumb_path = os.path.join(thumb_dir, thumb_filename)
                    ff_cmd = [FFMPEG_PATH or 'ffmpeg', '-y', '-ss', '00:00:01', '-i', analysis.input_video.path, '-vframes', '1', '-q:v', '2', thumb_path]
                    try:
                        subprocess.run(ff_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
                        if os.path.exists(thumb_path):
                            with open(thumb_path, 'rb') as tf:
                                analysis.thumbnail.save(thumb_filename, File(tf), save=False)
                    except Exception:
                        pass
                except Exception:
                    pass

                # Try to fetch hole yardage from Golf Course API if course+hole provided
                yardage = None
                par = None
                used_tee = None
                if course_name and hole_number:
                    api_key = GOLF_COURSE_API_KEY_HARDCODED or os.environ.get('GOLF_COURSE_API_KEY')
                    if api_key:
                        try:
                            api_url = 'https://api.golfcourseapi.com/v1/search'
                            resp = requests.get(api_url, params={'search_query': course_name}, headers={'Authorization': f'Key {api_key}'}, timeout=8)
                            if resp.status_code == 200:
                                try:
                                    payload = resp.json()

                                    # continue using API payload for yardage/par

                                    def find_yardage_recursive(obj, hole, preferred_tee=None):
                                        """Recursively search API payload for hole yardage.

                                        Matching priority when preferred_tee is provided:
                                        1) direct case-insensitive equality on tee_name
                                        2) normalized exact match (alnum only)
                                        3) token/substring match via _tee_matches
                                        """
                                        try:
                                            def _norm(s):
                                                return re.sub(r'[^a-z0-9]+', '', (s or '').lower()).strip()

                                            # Helper to extract yard/par from a holes list at index
                                            def _extract_from_holes(holes, hole_idx):
                                                if not isinstance(holes, list):
                                                    return None
                                                if 0 <= hole_idx < len(holes):
                                                    he = holes[hole_idx]
                                                    y = he.get('yardage') or he.get('yards') or he.get('length')
                                                    p = he.get('par') or he.get('par_value') or he.get('par_total')
                                                    if y is not None:
                                                        try:
                                                            p_val = int(p) if p is not None else None
                                                        except Exception:
                                                            p_val = None
                                                        return (int(y), p_val)
                                                return None

                                            # If dict with tees/courses
                                            if isinstance(obj, dict):
                                                # Collect candidate tees
                                                candidates = []
                                                # If payload has courses
                                                if 'courses' in obj and isinstance(obj.get('courses'), list):
                                                    for course in obj.get('courses'):
                                                        tees = course.get('tees') if isinstance(course.get('tees'), dict) else None
                                                        if tees:
                                                            for group, tlist in tees.items():
                                                                if isinstance(tlist, list):
                                                                    for tee in tlist:
                                                                        candidates.append((group, tee))
                                                # If top-level tees dict
                                                elif 'tees' in obj and isinstance(obj.get('tees'), dict):
                                                    for group, tlist in obj.get('tees').items():
                                                        if isinstance(tlist, list):
                                                            for tee in tlist:
                                                                candidates.append((group, tee))

                                                hole_idx = int(hole) - 1

                                                # 1) direct equality
                                                if preferred_tee:
                                                    pref = (preferred_tee or '').strip().lower()
                                                    if pref:
                                                        for group, tee in candidates:
                                                            tn = (tee.get('tee_name') or '')
                                                            holes = tee.get('holes')
                                                            if tn and tn.strip().lower() == pref:
                                                                extracted = _extract_from_holes(holes, hole_idx)
                                                                if extracted:
                                                                    yv, pv = extracted
                                                                    try:
                                                                        logger.info(f"find_yardage_recursive: direct equality match preferred={preferred_tee!r} matched_tee={tn!r}")
                                                                    except Exception:
                                                                        pass
                                                                    return (yv, pv, tn)

                                                # 2) normalized exact match
                                                if preferred_tee:
                                                    pnorm = _norm(preferred_tee)
                                                    if pnorm:
                                                        for group, tee in candidates:
                                                            tn = (tee.get('tee_name') or '')
                                                            holes = tee.get('holes')
                                                            if _norm(tn) == pnorm:
                                                                extracted = _extract_from_holes(holes, hole_idx)
                                                                if extracted:
                                                                    yv, pv = extracted
                                                                    try:
                                                                        logger.info(f"find_yardage_recursive: exact match preferred={preferred_tee!r} matched_tee={tn!r}")
                                                                    except Exception:
                                                                        pass
                                                                    return (yv, pv, tn)

                                                # 3) token/substring fallback
                                                if preferred_tee:
                                                    try:
                                                        cand_names = [tee.get('tee_name') or '' for _, tee in candidates]
                                                        logger.info(f"find_yardage_recursive: fallback candidates={cand_names} preferred={preferred_tee!r}")
                                                    except Exception:
                                                        pass
                                                    for group, tee in candidates:
                                                        tn = (tee.get('tee_name') or '')
                                                        holes = tee.get('holes')
                                                        if _tee_matches(preferred_tee, tn):
                                                            extracted = _extract_from_holes(holes, hole_idx)
                                                            if extracted:
                                                                yv, pv = extracted
                                                                try:
                                                                    logger.info(f"find_yardage_recursive: fallback match preferred={preferred_tee!r} matched_tee={tn!r}")
                                                                except Exception:
                                                                    pass
                                                                return (yv, pv, tn)

                                                # No preferred match: return first available tee hole
                                                for group, tee in candidates:
                                                    holes = tee.get('holes')
                                                    extracted = _extract_from_holes(holes, hole_idx)
                                                    if extracted:
                                                        yv, pv = extracted
                                                        return (yv, pv, f"{group}.{(tee.get('tee_name') or '')}")

                                            # If obj directly contains 'holes' list
                                            if 'holes' in obj and isinstance(obj.get('holes'), list):
                                                holes = obj.get('holes')
                                                idx = int(hole) - 1
                                                extracted = None
                                                if 0 <= idx < len(holes):
                                                    he = holes[idx]
                                                    y = he.get('yardage') or he.get('yards') or he.get('length')
                                                    p = he.get('par') or he.get('par_value') or he.get('par_total')
                                                    if y is not None:
                                                        try:
                                                            p_val = int(p) if p is not None else None
                                                        except Exception:
                                                            p_val = None
                                                        return (int(y), p_val, None)

                                            # Heuristics: numeric hole field
                                            possible_num = None
                                            for k in ('number', 'hole', 'hole_number'):
                                                if k in obj:
                                                    possible_num = obj.get(k)
                                                    break
                                            if possible_num is not None:
                                                try:
                                                    if int(possible_num) == int(hole):
                                                        for yk in ('yardage', 'yards', 'length', 'tee_yards'):
                                                            if yk in obj and obj.get(yk) is not None:
                                                                try:
                                                                    yv = int(obj.get(yk))
                                                                    p = obj.get('par') or obj.get('par_value') or obj.get('par_total')
                                                                    try:
                                                                        p_val = int(p) if p is not None else None
                                                                    except Exception:
                                                                        p_val = None
                                                                    return (yv, p_val, None)
                                                                except Exception:
                                                                    pass
                                                except Exception:
                                                    pass

                                            # Recurse into dict values
                                            for v in obj.values():
                                                res = find_yardage_recursive(v, hole, preferred_tee)
                                                if res is not None:
                                                    return res
                                            return None

                                        except Exception:
                                            return None

                                    res = find_yardage_recursive(payload, hole_number, selected_tee)
                                    if res:
                                        yardage, par, used_tee = res
                                    else:
                                        yardage = None
                                        par = None
                                        used_tee = None
                                except ValueError:
                                    yardage = None
                        except requests.RequestException:
                            yardage = None

                # Persist course/hole/yardage on the analysis and save; queue for background work
                if course_name:
                    analysis.course_name = course_name
                if hole_number:
                    analysis.hole_number = hole_number
                if selected_tee:
                    analysis.selected_tee = selected_tee
                if yardage:
                    analysis.hole_yardage = yardage
                if par is not None:
                    analysis.hole_par = par
                if used_tee:
                    analysis.used_tee = used_tee

                # Persist whether the user requested a pose overlay for this analysis
                try:
                    analysis.overlay_requested = bool(request.POST.get('overlay_pose'))
                    analysis.include_map = bool(request.POST.get('include_map'))
                    analysis.include_course_text = bool(request.POST.get('include_course_text'))
                    analysis.overlay_status = 'pending'
                except Exception:
                    pass

                analysis.save()

                # Queue for background processing (start later after tee confirmation)
                try:
                    input_path = analysis.input_video.path
                    base_name = os.path.splitext(os.path.basename(uploaded_file.name))[0]
                    output_filename = f"{base_name}_processed.mp4"
                    output_path = os.path.join(settings.MEDIA_ROOT, 'output', output_filename)
                    processing_queue.append((analysis, input_path, output_path, par))
                except Exception:
                    processing_queue.append((analysis, None, None, par))

                # persist stroke ordering
                try:
                    analysis.stroke_number = stroke_num
                    if round_obj:
                        logger.info(f"Attaching analysis to round: analysis temp save stroke={stroke_num} user={request.user.pk} round={round_obj.pk}")
                    analysis.save()
                except Exception:
                    analysis.save()
                created_pks.append(analysis.pk)

                # Cleanup temp file if created
                try:
                    if tmp_path and os.path.exists(tmp_path):
                        os.remove(tmp_path)
                except Exception:
                    pass

            # After creating analyses, decide whether we need to ask the user to confirm their selected tee.
            # Start background processing threads per analysis immediately (previous behavior)
            for (analysis, input_path, output_path, par_val) in processing_queue:
                try:
                    if input_path and output_path:
                        thread = threading.Thread(target=process_video_background, args=(analysis.pk, input_path, output_path, par_val), daemon=False)
                        thread.start()
                except Exception:
                    logger.exception('Failed to start background processing for analysis %s', getattr(analysis, 'pk', 'unknown'))
            try:
                logger.info(f"analyze_upload: created analyses pks={created_pks}")
            except Exception:
                pass
            messages.success(request, f'{len(created_pks)} video(s) uploaded successfully! Processing has started.')
            try:
                # Prefer redirecting to the round page if we attached these analyses to a round.
                # Use getattr to avoid referencing an undefined name in any code path.
                if 'round_obj' in locals() and getattr(round_obj, 'pk', None):
                    try:
                        logger.info(f"analyze_upload: redirecting to round_holes round_pk={round_obj.pk}")
                    except Exception:
                        pass
                    return redirect('shots:round_holes', round_pk=round_obj.pk)
            except Exception:
                pass
            return redirect('shots:shot_list')
        else:
            try:
                logger.warning(f"analyze_upload: form.is_valid() == False, errors={form.errors}")
            except Exception:
                pass
            # Build helpful debug context similar to GET so the template can surface errors and posted keys
            rounds = []
            try:
                from .models import ShotRound
                rounds = ShotRound.objects.filter(user_id=getattr(request.user, 'pk', None)).order_by('-played_at', '-created_at')[:50]
            except Exception:
                rounds = []

            all_rounds = []
            try:
                from .models import ShotRound
                all_rounds = list(ShotRound.objects.all().values('pk', 'user_id', 'name', 'played_at'))
            except Exception:
                all_rounds = []

            db_path = None
            try:
                db_path = settings.DATABASES.get('default', {}).get('NAME')
            except Exception:
                db_path = None
            request_user_info = {'pk': getattr(request.user, 'pk', None), 'is_authenticated': getattr(request.user, 'is_authenticated', False), 'repr': repr(request.user)}

            # Prefetch tees if possible (same logic as GET path) to keep the UI similar
            prefetched_tee_names = []
            try:
                api_key = GOLF_COURSE_API_KEY_HARDCODED or os.environ.get('GOLF_COURSE_API_KEY')
                course_query = request.POST.get('course') or request.GET.get('course')
                if api_key and course_query:
                    api_url = 'https://api.golfcourseapi.com/v1/search'
                    resp = requests.get(api_url, params={'search_query': course_query}, headers={'Authorization': f'Key {api_key}'}, timeout=6)
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

            seen = set()
            ordered = []
            for n in prefetched_tee_names:
                if n and n not in seen:
                    seen.add(n)
                    ordered.append(n)

            context = {'form': form, 'rounds': rounds, 'all_rounds': all_rounds, 'db_path': db_path, 'request_user_info': request_user_info, 'prefetched_tee_names': ordered, 'form_errors': str(form.errors), 'posted_keys': list(request.POST.keys())}
            return render(request, 'shots/analyze_form.html', context)
    else:
        form = ShotAnalysisForm()

    # Provide existing rounds for the user so they can attach uploads to a round
    rounds = []
    try:
        from .models import ShotRound
        rounds = ShotRound.objects.filter(user_id=getattr(request.user, 'pk', None)).order_by('-played_at', '-created_at')[:50]
        try:
            logger.info(f"analyze_upload (GET): found rounds for user {getattr(request.user,'pk',None)} -> {[r.pk for r in rounds]}")
        except Exception:
            logger.info("analyze_upload (GET): found rounds (unable to list ids)")
    except Exception:
        logger.exception('Error fetching rounds for analyze_upload (GET)')
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

    # Server-side prefetch of tee names (fallback in case client cannot fetch API)
    prefetched_tee_names = []
    try:
        api_key = GOLF_COURSE_API_KEY_HARDCODED or os.environ.get('GOLF_COURSE_API_KEY')
        course_query = None
        # If page was rendered with a fixed course, use it; otherwise leave to client
        if 'fixed_course_obj' in locals() and getattr(locals().get('fixed_course_obj'), 'name', None):
            course_query = locals().get('fixed_course_obj').name
        else:
            # try to use a recently suggested course from session or query params
            from django.http import HttpRequest
            try:
                course_query = form.initial.get('course') if hasattr(form, 'initial') else None
            except Exception:
                course_query = None

        # Allow override from query params for testing and prefill flows
        try:
            if not course_query:
                course_query = request.GET.get('course')
        except Exception:
            pass

        if api_key and course_query:
            try:
                api_url = 'https://api.golfcourseapi.com/v1/search'
                resp = requests.get(api_url, params={'search_query': course_query}, headers={'Authorization': f'Key {api_key}'}, timeout=6)
                if resp.status_code == 200:
                    payload = resp.json()
                    # Extract tee names from payload.courses[*].tees.*[].tee_name
                    try:
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
                        pass
            except Exception:
                pass

    except Exception:
        prefetched_tee_names = []

    # Deduplicate while preserving order
    seen = set()
    ordered = []
    for n in prefetched_tee_names:
        if n and n not in seen:
            seen.add(n)
            ordered.append(n)

    return render(request, 'shots/analyze_form.html', {'form': form, 'rounds': rounds, 'all_rounds': all_rounds, 'db_path': db_path, 'request_user_info': request_user_info, 'prefetched_tee_names': ordered})
