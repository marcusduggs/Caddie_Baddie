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

    # If input_path is an S3/HTTPS URL, download to a local temp file so all
    # downstream tools (ffmpeg, cv2, ffprobe) can read it via a real file path.
    _tmp_input = None
    if input_path.startswith('http://') or input_path.startswith('https://'):
        try:
            import urllib.request
            suffix = os.path.splitext(input_path.split('?')[0])[-1] or '.mp4'
            fd, _tmp_input = tempfile.mkstemp(suffix=suffix)
            os.close(fd)
            logger.info('Downloading remote input %s -> %s', input_path, _tmp_input)
            urllib.request.urlretrieve(input_path, _tmp_input)
            input_path = _tmp_input
        except Exception:
            logger.exception('Failed to download remote input for analysis %s', analysis_pk)
            if _tmp_input and os.path.exists(_tmp_input):
                os.remove(_tmp_input)
            _tmp_input = None

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

        os.makedirs(os.path.dirname(output_path), exist_ok=True)

        # Look up stored GPS coords for map overlay
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

        # Full AI analysis pipeline: metrics → scores → snapshots → memory → coaching
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
    finally:
        if _tmp_input and os.path.exists(_tmp_input):
            try:
                os.remove(_tmp_input)
            except Exception:
                pass


def _apply_pose_overlay(sa, output_path):
    """Render a MediaPipe pose wireframe onto the processed video (in-place)."""
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
    """Run the full AI coaching pipeline for a ShotAnalysis.

    Pipeline order:
        1. Metrics extraction (MediaPipe pose detection)
        2. Swing scoring (0-100 per dimension)
        3. Frame snapshots (setup / top / impact / finish)
        4. Shot shape detection (stored in metrics)
        5. Pro comparison
        6. Swing memory update + trend summary
        7. Coaching prompt + OpenAI feedback generation
        8. Persist all results

    All failures are logged and swallowed — a coaching error must never cause
    the shot record to be marked as failed.
    """
    # ------------------------------------------------------------------
    # 1. Metrics extraction
    # ------------------------------------------------------------------
    try:
        from .ai.metrics_engine import extract_swing_metrics
    except ImportError as exc:
        logger.warning('AI metrics module not available: %s', exc)
        return

    try:
        metrics = extract_swing_metrics(video_path)
    except Exception:
        logger.exception('AI metrics extraction failed for analysis %s', sa.pk)
        return

    try:
        sa.ai_metrics_json = json.dumps(metrics)
        sa.save(update_fields=['ai_metrics_json', 'updated_at'])
    except Exception:
        logger.warning('Could not save ai_metrics_json for analysis %s', sa.pk, exc_info=True)

    if metrics.get('frame_count', 0) == 0:
        logger.warning('No pose frames detected for analysis %s — running AI feedback with empty metrics', sa.pk)
        # Do NOT return here: coach_agent will produce a "no pose data" message for the user

    # ------------------------------------------------------------------
    # 2. Swing scoring
    # ------------------------------------------------------------------
    scores = {}
    try:
        from .ai.scoring_engine import compute_scores
        scores = compute_scores(metrics)
        update_fields = []
        field_map = {
            'overall_score': 'ai_overall_score',
            'tempo_score': 'ai_tempo_score',
            'balance_score': 'ai_balance_score',
            'rotation_score': 'ai_rotation_score',
            'posture_score': 'ai_posture_score',
            'sequencing_score': 'ai_sequencing_score',
            'consistency_score': 'ai_consistency_score',
        }
        for score_key, field_name in field_map.items():
            val = scores.get(score_key)
            if val is not None:
                setattr(sa, field_name, val)
                update_fields.append(field_name)
        if update_fields:
            update_fields.append('updated_at')
            sa.save(update_fields=update_fields)
        logger.info('Scores saved for analysis %s: overall=%s', sa.pk, scores.get('overall_score'))
    except Exception:
        logger.exception('Scoring engine failed for analysis %s', sa.pk)

    # ------------------------------------------------------------------
    # 3. Shot shape (already in metrics from metrics_engine)
    # ------------------------------------------------------------------
    try:
        shot_shape = metrics.get('shot_shape', 'unknown')
        sa.ai_shot_shape = shot_shape
        sa.save(update_fields=['ai_shot_shape', 'updated_at'])
    except Exception:
        logger.warning('Could not save shot shape for analysis %s', sa.pk, exc_info=True)

    # ------------------------------------------------------------------
    # 4. Frame snapshots
    # ------------------------------------------------------------------
    try:
        from .ai.snapshot_extractor import extract_snapshots
        snapshots = extract_snapshots(video_path, sa.pk)
        if snapshots:
            sa.ai_snapshots_json = json.dumps(snapshots)
            sa.save(update_fields=['ai_snapshots_json', 'updated_at'])
            logger.info('Snapshots saved for analysis %s: %s', sa.pk, list(snapshots.keys()))
    except Exception:
        logger.exception('Snapshot extraction failed for analysis %s', sa.pk)

    # ------------------------------------------------------------------
    # 5. Pro comparison
    # ------------------------------------------------------------------
    pro_comparison_text = ''
    try:
        from .ai.pro_comparisons import get_pro_comparison
        comparison = get_pro_comparison(metrics)
        pro_comparison_text = comparison.get('description', '')
        if pro_comparison_text:
            sa.ai_pro_comparison = pro_comparison_text
            sa.save(update_fields=['ai_pro_comparison', 'updated_at'])
    except Exception:
        logger.exception('Pro comparison failed for analysis %s', sa.pk)

    # ------------------------------------------------------------------
    # 6. Swing memory: update tendencies + generate trend summary
    # ------------------------------------------------------------------
    trend_summary = ''
    try:
        from .ai.swing_memory import update_swing_memory, generate_trend_summary
        update_swing_memory(sa.user_id, sa.pk, metrics)
        trend_summary = generate_trend_summary(sa.user_id, metrics)
        if trend_summary:
            sa.ai_trend_summary = trend_summary
            sa.save(update_fields=['ai_trend_summary', 'updated_at'])
    except Exception:
        logger.exception('Swing memory update failed for analysis %s', sa.pk)

    # ------------------------------------------------------------------
    # 7. AI coaching call (OpenAI)
    # ------------------------------------------------------------------
    try:
        from .ai.coach_agent import analyze_swing
        from .ai.prompt_builder import build_coaching_prompt, build_system_prompt
    except ImportError as exc:
        logger.warning('AI coaching modules not available: %s', exc)
        return

    try:
        feedback = analyze_swing(
            metrics,
            club=sa.club or 'unknown',
            distance_yards=sa.distance,
            scores=scores,
            trend_summary=trend_summary,
            pro_comparison=pro_comparison_text,
        )
    except Exception:
        logger.exception('AI coaching call failed for analysis %s', sa.pk)
        return

    # ------------------------------------------------------------------
    # 8. Persist coaching feedback
    # ------------------------------------------------------------------
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
