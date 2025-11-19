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
from utils.overlay import process_video_with_overlay


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
    return render(request, 'shots/analysis_detail.html', {'analysis': analysis})


def shot_list(request):
    """Show all uploaded shot videos in a responsive Tailwind grid."""
    # Use ShotAnalysis (uploaded videos) ordered newest first
    analyses = ShotAnalysis.objects.order_by('-created_at')[:200]
    return render(request, 'shots/shot_list.html', {'analyses': analyses})


def delete_shot(request, pk):
    """Delete a ShotAnalysis (and its files) and redirect to the shots list.

    This view only accepts POST requests for safety.
    """
    from django.http import HttpResponseNotAllowed
    if request.method != 'POST':
        return HttpResponseNotAllowed(['POST'])

    try:
        sa = ShotAnalysis.objects.get(pk=pk)
    except ShotAnalysis.DoesNotExist:
        return redirect('shots:shot_list')

    # Delete files from storage if present
    try:
        if sa.video:
            try:
                sa.video.delete(save=False)
            except Exception:
                pass
        if sa.processed_video:
            try:
                sa.processed_video.delete(save=False)
            except Exception:
                pass
    except Exception:
        pass

    # Delete the DB record
    sa.delete()
    return redirect('shots:shot_list')
