"""
Django-Q task definitions for background video processing.

Run the worker with:
    python manage.py qcluster

Task results and status are visible in the Django admin under Django-Q > Successful/Failed tasks.
"""

import json
import os
import logging
import tempfile

from django.core.files import File

logger = logging.getLogger(__name__)


def process_video_background(analysis_pk, input_path, output_path, hole_par=None):
    """Process a golf swing video and attach the result to a ShotAnalysis record.

    This is the Django-Q task that replaced the old raw threading.Thread approach.
    Django-Q will retry it once on failure (max_attempts=2 in Q_CLUSTER settings)
    and store the result/error in the database for inspection in the admin.

    Args:
        analysis_pk: Primary key of the ShotAnalysis to update.
        input_path:  Absolute path to the uploaded input video file.
        output_path: Absolute path where the processed video should be written.
        hole_par:    Optional par value for the hole (passed transiently from the upload).
    """
    from .models import ShotAnalysis, ShotDistance
    from utils.overlay import process_video_with_overlay, _extract_coords_with_ffprobe

    try:
        sa = ShotAnalysis.objects.get(pk=analysis_pk)
    except ShotAnalysis.DoesNotExist:
        logger.error('process_video_background: ShotAnalysis %s not found', analysis_pk)
        return

    try:
        sa.status = 'processing'
        sa.error_message = ''
        sa.save(update_fields=['status', 'error_message', 'updated_at'])
        logger.info('Processing started for analysis %s: %s -> %s', analysis_pk, input_path, output_path)

        # Best-effort GPS extraction so the map can show a marker straight away
        try:
            coords = _extract_coords_with_ffprobe(input_path)
            if coords:
                lon, lat = coords
                if not ShotDistance.objects.filter(shot=sa).exists():
                    ShotDistance.objects.create(
                        shot=sa,
                        origin_lat=float(lat),
                        origin_lng=float(lon),
                        hole_number=sa.hole_number,
                    )
                    logger.info('Persisted GPS for analysis %s: lat=%s lon=%s', analysis_pk, lat, lon)
        except Exception:
            logger.debug('GPS extraction skipped for analysis %s', analysis_pk, exc_info=True)

        # Ensure the output directory exists before ffmpeg tries to write there
        os.makedirs(os.path.dirname(output_path), exist_ok=True)

        # Look up stored GPS coords so the map overlay can be fetched
        coords = None
        try:
            sd = ShotDistance.objects.filter(
                shot=sa, origin_lat__isnull=False, origin_lng__isnull=False
            ).order_by('created_at').first()
            if sd:
                coords = (sd.origin_lng, sd.origin_lat)
        except Exception:
            logger.debug('Could not resolve GPS coords for analysis %s', analysis_pk, exc_info=True)

        # Run overlay / map burn-in
        try:
            process_video_with_overlay(
                input_path,
                output_path,
                coords,
                sa.course_name,
                sa.hole_number,
                sa.hole_yardage,
                sa.club,
                hole_par=hole_par,
                overlay_map_requested=getattr(sa, 'include_map', False),
                include_course_text=getattr(sa, 'include_course_text', False),
            )
        except Exception as e:
            logger.exception('Overlay processing failed for analysis %s', analysis_pk)
            sa.status = 'failed'
            sa.error_message = f'Overlay processing failed: {e}'
            sa.save(update_fields=['status', 'error_message', 'updated_at'])
            return

        # Attach the processed file
        attached = False
        if os.path.exists(output_path):
            try:
                with open(output_path, 'rb') as f:
                    sa.processed_video.save(os.path.basename(output_path), File(f), save=True)
                attached = True
                logger.info('Attached processed video for analysis %s', analysis_pk)
            except Exception:
                logger.exception('Failed to attach processed video for analysis %s', analysis_pk)
        else:
            logger.warning('Expected output not found for analysis %s: %s', analysis_pk, output_path)

        if not attached:
            sa.status = 'failed'
            sa.error_message = 'Processed file was not created or could not be attached.'
            sa.save(update_fields=['status', 'error_message', 'updated_at'])
            return

        # Optional pose wireframe overlay
        if getattr(sa, 'overlay_requested', False):
            _apply_pose_overlay(sa, output_path)

        # AI Swing Coach: extract biomechanical metrics then request coaching feedback.
        # This runs after overlay processing so the main video pipeline is unaffected
        # if AI analysis fails.  All errors are caught and logged non-fatally.
        _run_ai_analysis(sa, input_path)

        # Persist hole_par if provided transiently
        if hole_par is not None:
            try:
                sa.hole_par = int(hole_par)
            except (TypeError, ValueError):
                pass

        sa.status = 'completed'
        sa.error_message = ''
        sa.save(update_fields=['status', 'error_message', 'hole_par', 'updated_at'])
        logger.info('Processing completed for analysis %s', analysis_pk)

    except Exception as e:
        logger.exception('Unexpected error in process_video_background for analysis %s', analysis_pk)
        try:
            sa.refresh_from_db()
            sa.status = 'failed'
            sa.error_message = str(e)
            sa.save(update_fields=['status', 'error_message', 'updated_at'])
        except Exception:
            logger.exception('Failed to save error state for analysis %s', analysis_pk)


def _apply_pose_overlay(sa, output_path):
    """Render a MediaPipe pose wireframe onto the processed video (in-place).

    Mutates sa.overlay_status / sa.overlay_error_message and saves those fields.
    Does NOT call sa.save() for the main status — that's the caller's job.
    """
    from .video_processing import render_pose_wireframe

    sa.overlay_status = 'overlaying'
    sa.save(update_fields=['overlay_status', 'updated_at'])

    fd, overlay_tmp = tempfile.mkstemp(suffix='.mp4')
    os.close(fd)
    try:
        overlay_path = render_pose_wireframe(output_path, output_path=overlay_tmp)

        if overlay_path is None:
            sa.overlay_status = 'skipped'
            sa.overlay_error_message = 'Pose overlay not available on this system (mediapipe/opencv missing).'
        elif os.path.exists(overlay_path) and os.path.getsize(overlay_path) > 0:
            with open(overlay_path, 'rb') as ofp:
                sa.processed_video.save(os.path.basename(output_path), File(ofp), save=True)
            sa.overlay_status = 'completed'
            sa.overlay_error_message = ''
        else:
            sa.overlay_status = 'failed'
            sa.overlay_error_message = 'Overlay renderer produced no output.'
    except Exception as e:
        logger.exception('Pose overlay failed for analysis %s', sa.pk)
        sa.overlay_status = 'failed'
        sa.overlay_error_message = str(e)
    finally:
        try:
            if os.path.exists(overlay_tmp):
                os.remove(overlay_tmp)
        except Exception:
            pass
        sa.save(update_fields=['overlay_status', 'overlay_error_message', 'updated_at'])


def _run_ai_analysis(sa, video_path: str) -> None:
    """Extract swing metrics and generate AI coaching feedback for a ShotAnalysis.

    Runs after the main video processing pipeline.  All failures are logged
    and swallowed — a coaching API outage must never cause the shot record to
    be marked as failed.

    Args:
        sa:         ShotAnalysis instance (already saved with processed_video).
        video_path: Path to the video file to run pose detection on (input video).
    """
    try:
        from .ai.metrics_engine import extract_swing_metrics
        from .ai.coach_agent import analyze_swing
    except ImportError as exc:
        logger.warning('AI coaching modules not available: %s', exc)
        return

    # --- Metrics extraction ---
    try:
        metrics = extract_swing_metrics(video_path)
    except Exception:
        logger.exception('AI metrics extraction failed for analysis %s', sa.pk)
        return

    # Store raw metrics JSON for inspection / future re-analysis
    try:
        sa.ai_metrics_json = json.dumps(metrics)
        sa.save(update_fields=['ai_metrics_json', 'updated_at'])
    except Exception:
        logger.warning('Could not save ai_metrics_json for analysis %s', sa.pk, exc_info=True)

    # --- AI coaching call ---
    try:
        feedback = analyze_swing(
            metrics,
            club=sa.club or 'unknown',
            distance_yards=sa.distance,
        )
    except Exception:
        logger.exception('AI coaching call failed for analysis %s', sa.pk)
        return

    # --- Persist coaching feedback ---
    try:
        sa.ai_main_fault = feedback.get('main_fault', '')
        sa.ai_strength = feedback.get('strength', '')
        sa.ai_drill = feedback.get('drill', '')
        sa.ai_swing_thought = feedback.get('swing_thought', '')
        sa.save(update_fields=[
            'ai_main_fault', 'ai_strength', 'ai_drill', 'ai_swing_thought', 'updated_at',
        ])
        logger.info('AI coaching feedback saved for analysis %s', sa.pk)
    except Exception:
        logger.exception('Failed to save AI coaching feedback for analysis %s', sa.pk)
