"""
FastAPI server for asynchronous golf video processing.
This allows the Mac Mini to process videos in the background without keeping connections open.
"""

import os
import re
import shutil
import logging
from pathlib import Path
from typing import Optional
import boto3
from botocore.exceptions import ClientError

from fastapi import FastAPI, File, UploadFile, BackgroundTasks, HTTPException, Security, Depends
from fastapi.security.api_key import APIKeyHeader
from fastapi.responses import JSONResponse

from utils.overlay import process_video_with_overlay

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Golf Video Processing API",
    description="Asynchronous video processing for Reel Caddie Daddy",
    version="1.0.0"
)

INPUT_DIR = Path("/Users/marcusduggs/videos/input")
OUTPUT_DIR = Path("/Users/marcusduggs/videos/output")

INPUT_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

S3_BUCKET_NAME = os.getenv("S3_BUCKET_NAME", "")
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")

# Shared-secret API key for all endpoints — set VIDEO_API_KEY env var
_API_KEY = os.getenv("VIDEO_API_KEY", "")
_API_KEY_HEADER = APIKeyHeader(name="X-API-Key", auto_error=True)

_ALLOWED_VIDEO_EXTENSIONS = {'.mp4', '.mov', '.avi', '.mkv', '.m4v', '.wmv', '.webm'}
_ALLOWED_VIDEO_MIMETYPES = {'video/'}

# Only allow alphanumeric and hyphens in video IDs to prevent path traversal
_VIDEO_ID_RE = re.compile(r'^[a-zA-Z0-9\-]+$')


def _verify_api_key(api_key: str = Security(_API_KEY_HEADER)) -> str:
    if not _API_KEY:
        raise HTTPException(status_code=503, detail="Server not configured: VIDEO_API_KEY not set.")
    if api_key != _API_KEY:
        raise HTTPException(status_code=403, detail="Invalid API key.")
    return api_key


def upload_to_s3(file_path: str, bucket_name: str, object_name: Optional[str] = None) -> bool:
    if not bucket_name or bucket_name == "your-golf-videos-bucket":
        logger.error("S3_BUCKET_NAME is not configured; skipping upload.")
        return False
    if object_name is None:
        object_name = os.path.basename(file_path)
    s3_client = boto3.client('s3', region_name=AWS_REGION)
    try:
        logger.info(f"Starting S3 upload: {file_path} -> s3://{bucket_name}/{object_name}")
        s3_client.upload_file(file_path, bucket_name, object_name)
        logger.info(f"S3 upload successful: s3://{bucket_name}/{object_name}")
        return True
    except ClientError as e:
        logger.error(f"S3 upload failed: {e}")
        return False


def run_golf_pipeline(input_path: str, output_path: str, upload_to_cloud: bool = True):
    try:
        logger.info(f"[PIPELINE START] Processing video: {input_path}")
        process_video_with_overlay(input_path, output_path)
        logger.info(f"[STEP 1/3] Video processed successfully: {output_path}")

        if not os.path.exists(output_path):
            raise FileNotFoundError(f"Processed video not found at {output_path}")

        output_size = os.path.getsize(output_path) / (1024 * 1024)
        logger.info(f"[STEP 2/3] Output file verified: {output_size:.2f} MB")

        if upload_to_cloud:
            if not S3_BUCKET_NAME or S3_BUCKET_NAME == "your-golf-videos-bucket":
                logger.warning("[STEP 3/3] S3_BUCKET_NAME not configured; skipping upload.")
            else:
                s3_object_name = f"processed/{os.path.basename(output_path)}"
                success = upload_to_s3(output_path, S3_BUCKET_NAME, s3_object_name)
                if success:
                    logger.info(f"[STEP 3/3] S3 upload complete: s3://{S3_BUCKET_NAME}/{s3_object_name}")
                else:
                    logger.warning("[STEP 3/3] S3 upload failed, but local file is saved")
        else:
            logger.info("[STEP 3/3] Skipped S3 upload (disabled)")

        logger.info(f"[PIPELINE COMPLETE] Successfully processed: {os.path.basename(input_path)}")

    except Exception as e:
        logger.error(f"[PIPELINE FAILED] Error processing {input_path}: {str(e)}", exc_info=True)


@app.get("/")
async def root(_: str = Depends(_verify_api_key)):
    return {"status": "online", "service": "Reel Caddie Daddy Video Processor", "version": "1.0.0"}


@app.get("/health")
async def health_check(_: str = Depends(_verify_api_key)):
    return {
        "status": "healthy",
        "input_dir": str(INPUT_DIR),
        "output_dir": str(OUTPUT_DIR),
        "input_dir_exists": INPUT_DIR.exists(),
        "output_dir_exists": OUTPUT_DIR.exists(),
        "s3_configured": bool(S3_BUCKET_NAME and S3_BUCKET_NAME != "your-golf-videos-bucket"),
    }


@app.post("/process-video")
async def process_video(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    upload_to_s3_flag: bool = True,
    _: str = Depends(_verify_api_key),
):
    try:
        # Validate file extension against allowlist (MIME type is user-controlled)
        original_filename = file.filename or "video.mp4"
        extension = Path(original_filename).suffix.lower()
        if extension not in _ALLOWED_VIDEO_EXTENSIONS:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid file type: '{extension}'. Allowed: {sorted(_ALLOWED_VIDEO_EXTENSIONS)}"
            )

        import uuid
        unique_id = str(uuid.uuid4())[:8]
        base_name = Path(original_filename).stem
        input_filename = f"{base_name}_{unique_id}{extension}"
        output_filename = f"{base_name}_{unique_id}_processed.mp4"

        input_path = INPUT_DIR / input_filename
        output_path = OUTPUT_DIR / output_filename

        logger.info(f"[UPLOAD] Receiving video: {original_filename}, assigned ID: {unique_id}")

        with open(input_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        file_size = os.path.getsize(input_path) / (1024 * 1024)
        logger.info(f"[UPLOAD] Saved to disk: {input_path} ({file_size:.2f} MB)")

        background_tasks.add_task(run_golf_pipeline, str(input_path), str(output_path), upload_to_s3_flag)

        return JSONResponse(
            status_code=202,
            content={
                "status": "accepted",
                "message": "Video is processing in background.",
                "video_id": unique_id,
                "input_file": input_filename,
                "output_file": output_filename,
            }
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[UPLOAD] Error handling upload: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Upload failed: {str(e)}")


@app.get("/status/{video_id}")
async def check_status(video_id: str, _: str = Depends(_verify_api_key)):
    # Reject any video_id that isn't a plain alphanumeric/hyphen string
    if not _VIDEO_ID_RE.match(video_id):
        raise HTTPException(status_code=400, detail="Invalid video_id format.")

    input_files = list(INPUT_DIR.glob(f"*{video_id}*"))
    output_files = list(OUTPUT_DIR.glob(f"*{video_id}*"))

    if not input_files:
        raise HTTPException(status_code=404, detail="Video ID not found")

    status = "completed" if output_files else "processing"
    return {
        "video_id": video_id,
        "status": status,
        "input_file": input_files[0].name if input_files else None,
        "output_file": output_files[0].name if output_files else None,
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001, log_level="info")
