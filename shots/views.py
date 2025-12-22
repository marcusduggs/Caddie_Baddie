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
from .forms import ShotForm
from . import utils
from . import overlay_map
import os
from django.conf import settings
from .forms import ShotAnalysisForm
from .models import ShotAnalysis
from django.core.files import File
import shutil
from django.utils.text import slugify
import subprocess
import uuid
from utils.overlay import process_video_with_overlay, FFMPEG_PATH
import threading
import requests
import urllib.parse
import logging


logger = logging.getLogger(__name__)

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
        process_video_with_overlay(input_path, output_path, None, sa.course_name, sa.hole_number, sa.hole_yardage, sa.club, hole_par=hole_par)

        # Attach processed file to model
        if os.path.exists(output_path):
            with open(output_path, 'rb') as f:
                sa.processed_video.save(os.path.basename(output_path), File(f), save=False)
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
        form = ShotAnalysisForm(request.POST, request.FILES)
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
                        
                        process_video_with_overlay(input_path, output_path)
                        
                        logger.info(f"Video processing completed: {output_path}")
                        
                        # Save the processed video to the model
                        with open(output_path, 'rb') as f:
                            analysis.processed_video.save(output_filename, File(f), save=False)
                        
                        # Save the analysis to the database
                        analysis.save()
                        
                        # Success! Redirect to detail page
                        messages.success(request, 'Video processed successfully!')
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
    
    return render(request, 'shots/analyze_form.html', {'form': form})


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


from django.contrib.auth.decorators import login_required

@login_required
@login_required
def shot_list(request):
    """Show all uploaded shot videos for the logged-in user."""
    analyses = ShotAnalysis.objects.filter(user=request.user).order_by('-created_at')[:200]
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
        return redirect('shots:shot_list')

    # For non-POST requests, redirect back
    return redirect('shots:shot_list')


@login_required
def analyze_upload(request):
    """Handle uploading a video, read course/hole inputs, start background processing, and return result.

    This view saves the uploaded file, starts background processing (so the request doesn't block),
    queries the Golf Course API to obtain hole yardage (if the user provided course + hole),
    and redirects to the analysis detail page including course/hole/yardage in query params so
    the frontend overlay can show them immediately.
    """
    if request.method == 'POST':
        form = ShotAnalysisForm(request.POST, request.FILES)
        if form.is_valid():
            analysis = form.save(commit=False)
            analysis.user = request.user
            uploaded_file = request.FILES.get('input_video')

            # Read optional fields from POST
            course_name = request.POST.get('course', '').strip() or None
            hole_str = request.POST.get('hole', '').strip() or None
            selected_tee = request.POST.get('selected_tee', '').strip() or None
            try:
                hole_number = int(hole_str) if hole_str else None
            except Exception:
                hole_number = None

            if uploaded_file:
                # Save uploaded file to model
                analysis.input_video.save(uploaded_file.name, uploaded_file, save=False)

                # Generate a thumbnail frame from the uploaded video (fast, single-frame)
                try:
                    base_name = os.path.splitext(os.path.basename(uploaded_file.name))[0]
                    thumb_dir = os.path.join(settings.MEDIA_ROOT, 'thumbnails')
                    os.makedirs(thumb_dir, exist_ok=True)
                    thumb_filename = f"{base_name}.jpg"
                    thumb_path = os.path.join(thumb_dir, thumb_filename)
                    # Use ffmpeg to grab a frame at 1 second; fallback to 0 if video shorter
                    ff_cmd = [FFMPEG_PATH or 'ffmpeg', '-y', '-ss', '00:00:01', '-i', analysis.input_video.path, '-vframes', '1', '-q:v', '2', thumb_path]
                    try:
                        subprocess.run(ff_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
                        # Save to model field if file created
                        if os.path.exists(thumb_path):
                            with open(thumb_path, 'rb') as tf:
                                analysis.thumbnail.save(thumb_filename, File(tf), save=False)
                    except Exception:
                        # Non-fatal: don't interrupt upload if thumbnail generation fails
                        pass
                except Exception:
                    # Be defensive — if any path or file ops fail, ignore thumbnail creation
                    pass

                # Try to fetch hole yardage from Golf Course API if course+hole provided
                yardage = None
                if course_name and hole_number:
                    # Prefer hard-coded key for local testing if provided, otherwise fall back to env var
                    api_key = GOLF_COURSE_API_KEY_HARDCODED or os.environ.get('GOLF_COURSE_API_KEY')
                    if api_key:
                        try:
                            api_url = 'https://api.golfcourseapi.com/v1/search'
                            resp = requests.get(api_url, params={'search_query': course_name}, headers={'Authorization': f'Key {api_key}'}, timeout=8)
                            if resp.status_code == 200:
                                try:
                                    payload = resp.json()

                                    # robust recursive search for hole yardage
                                    def find_yardage_recursive(obj, hole, preferred_tee=None):
                                        """Walk a nested structure (dict/list) and find yardage for the given hole number.

                                        This function handles different payload shapes from the Golf Course API.
                                        - If it finds a dict with a 'holes' list it will index into that list using
                                          (hole - 1) and return the yardage if present.
                                        - If it finds a list of hole dicts (each containing 'yardage' or 'par') it
                                          will treat the list index+1 as the hole number and return the corresponding
                                          yardage.
                                        - Otherwise it will look for explicit hole-number keys ('number', 'hole',
                                          'hole_number') and yardage keys ('yardage','yards','length','tee_yards').
                                        """
                                        try:
                                            # Dict case: check for explicit 'holes' list (common in sample payload)
                                            if isinstance(obj, dict):
                                                # If this dict contains 'tees', try to honor preferred_tee
                                                if 'tees' in obj and isinstance(obj.get('tees'), dict):
                                                    tees_obj = obj.get('tees')
                                                    # tees_obj may have keys like 'male'/'female' mapping to lists of tee definitions
                                                    # Iterate through groups and tee lists to find a matching tee_name
                                                    for group_name, tee_list in tees_obj.items():
                                                        if isinstance(tee_list, list):
                                                            # First, if preferred_tee provided, try to match it (case-insensitive substring)
                                                            if preferred_tee:
                                                                for tee in tee_list:
                                                                    tn = (tee.get('tee_name') or '').lower()
                                                                    if preferred_tee.lower() in tn:
                                                                        holes = tee.get('holes')
                                                                        if isinstance(holes, list):
                                                                            idx = int(hole) - 1
                                                                            if 0 <= idx < len(holes):
                                                                                hole_entry = holes[idx]
                                                                                y = hole_entry.get('yardage') or hole_entry.get('yards') or hole_entry.get('length')
                                                                                p = hole_entry.get('par') or hole_entry.get('par_value') or hole_entry.get('par_total')
                                                                                if y is not None:
                                                                                    try:
                                                                                        p_val = int(p) if p is not None else None
                                                                                    except Exception:
                                                                                        p_val = None
                                                                                    return (int(y), p_val, f"{group_name}.{tee.get('tee_name')}")
                                                            # If no preferred match, fallback to first tee with holes
                                                            for tee in tee_list:
                                                                holes = tee.get('holes')
                                                                if isinstance(holes, list):
                                                                    idx = int(hole) - 1
                                                                    if 0 <= idx < len(holes):
                                                                        hole_entry = holes[idx]
                                                                        y = hole_entry.get('yardage') or hole_entry.get('yards') or hole_entry.get('length')
                                                                        p = hole_entry.get('par') or hole_entry.get('par_value') or hole_entry.get('par_total')
                                                                        if y is not None:
                                                                            try:
                                                                                p_val = int(p) if p is not None else None
                                                                            except Exception:
                                                                                p_val = None
                                                                            return (int(y), p_val, f"{group_name}.{tee.get('tee_name')}")

                                                # If this dict contains a 'holes' key that's a list, try to index it
                                                if 'holes' in obj and isinstance(obj.get('holes'), list):
                                                    holes = obj.get('holes')
                                                    idx = int(hole) - 1
                                                    if 0 <= idx < len(holes):
                                                        hole_entry = holes[idx]
                                                        y = hole_entry.get('yardage') or hole_entry.get('yards') or hole_entry.get('length')
                                                        p = hole_entry.get('par') or hole_entry.get('par_value') or hole_entry.get('par_total')
                                                        if y is not None:
                                                            try:
                                                                p_val = int(p) if p is not None else None
                                                            except Exception:
                                                                p_val = None
                                                            return (int(y), p_val, None)

                                                # check if this dict looks like a hole entry with an explicit number
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
                                                        # ignore parse errors for possible_num
                                                        pass

                                                # recurse into dict values
                                                for v in obj.values():
                                                    res = find_yardage_recursive(v, hole, preferred_tee)
                                                    if res is not None:
                                                        return res
                                                return None

                                            # List case: if it's a list of hole dicts, use index
                                            if isinstance(obj, list):
                                                # If list looks like list of holes (dicts with 'yardage' or 'par')
                                                if len(obj) > 0 and all(isinstance(it, dict) for it in obj):
                                                    # Treat list index as hole number
                                                    try:
                                                        idx = int(hole) - 1
                                                        if 0 <= idx < len(obj):
                                                            hole_entry = obj[idx]
                                                            y = hole_entry.get('yardage') or hole_entry.get('yards') or hole_entry.get('length')
                                                            p = hole_entry.get('par') or hole_entry.get('par_value') or hole_entry.get('par_total')
                                                            if y is not None:
                                                                try:
                                                                    p_val = int(p) if p is not None else None
                                                                except Exception:
                                                                    p_val = None
                                                                return (int(y), p_val, None)
                                                    except Exception:
                                                        pass

                                                # Otherwise recurse into list items
                                                for item in obj:
                                                    res = find_yardage_recursive(item, hole, preferred_tee)
                                                    if res is not None:
                                                        return res
                                                return None

                                        except Exception:
                                            # Defensive: on any unexpected structure, bail to caller
                                            return None

                                    res = find_yardage_recursive(payload, hole_number, selected_tee)
                                    if res:
                                        # res is a tuple (yardage, par, used_tee) where used_tee may be None
                                        yardage, par, used_tee = res
                                    else:
                                        yardage = None
                                        par = None
                                        used_tee = None
                                except ValueError:
                                    yardage = None
                        except requests.RequestException:
                            yardage = None

                # Persist course/hole/yardage on the analysis and save before starting background work
                if course_name:
                    analysis.course_name = course_name
                if hole_number:
                    analysis.hole_number = hole_number
                if selected_tee:
                    analysis.selected_tee = selected_tee
                if yardage:
                    analysis.hole_yardage = yardage
                if 'par' in locals() and par is not None:
                    # Persist par to the model so it survives reprocesses and can be shown later
                    analysis.hole_par = par

                if 'used_tee' in locals() and used_tee:
                    analysis.used_tee = used_tee

                # If yardage came with a used_tee label returned from extractor, set it (handled below)

                analysis.save()

                # Start background processing thread (processes video and updates analysis when done)
                input_path = analysis.input_video.path
                base_name = os.path.splitext(os.path.basename(uploaded_file.name))[0]
                output_filename = f"{base_name}_processed.mp4"
                output_path = os.path.join(settings.MEDIA_ROOT, 'output', output_filename)

                thread = threading.Thread(target=process_video_background, args=(analysis.pk, input_path, output_path, locals().get('par', None)), daemon=False)
                thread.start()

                # Build redirect with query params so frontend can read course/hole/yardage
                params = {}
                if course_name:
                    params['course'] = course_name
                if hole_number:
                    params['hole'] = str(hole_number)
                if yardage:
                    params['yardage'] = str(yardage)
                if 'par' in locals() and par is not None:
                    params['par'] = str(par)

                query = ('?' + urllib.parse.urlencode(params)) if params else ''
                messages.success(request, 'Video uploaded successfully! Processing has started.')
                return redirect(f"{reverse('shots:analysis_detail', kwargs={'pk': analysis.pk})}{query}")
            else:
                # No file uploaded
                messages.error(request, 'No video file uploaded.')
                return render(request, 'shots/analyze_form.html', {'form': form})
    else:
        form = ShotAnalysisForm()
    return render(request, 'shots/analyze_form.html', {'form': form})
    # Delete the DB record
