"""
FastAPI server for asynchronous golf video processing.
This allows the Mac Mini to process videos in the background without keeping connections open.
"""

import os
import shutil
import logging
from pathlib import Path
from typing import Optional
import boto3
from botocore.exceptions import ClientError

from fastapi import FastAPI, File, UploadFile, BackgroundTasks, HTTPException
from fastapi.responses import JSONResponse

# Import your existing video processing function
# Adjust this import based on your actual module structure
from utils.overlay import process_video_with_overlay

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Initialize FastAPI app
app = FastAPI(
    title="Golf Video Processing API",
    description="Asynchronous video processing for Reel Caddie Daddy",
    version="1.0.0"
)

# Directory configuration - customize these paths
INPUT_DIR = Path("/Users/marcusduggs/videos/input")
OUTPUT_DIR = Path("/Users/marcusduggs/videos/output")

# Ensure directories exist
INPUT_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# AWS S3 Configuration (set these via environment variables)
S3_BUCKET_NAME = os.getenv("S3_BUCKET_NAME", "your-golf-videos-bucket")
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")


def upload_to_s3(file_path: str, bucket_name: str, object_name: Optional[str] = None) -> bool:
    """
    Upload a file to an S3 bucket.
    
    Args:
        file_path: Path to file to upload
        bucket_name: Bucket to upload to
        object_name: S3 object name. If not specified, file_path basename is used
    
    Returns:
        True if file was uploaded, else False
    """
    # If S3 object_name was not specified, use file_path basename
    if object_name is None:
        object_name = os.path.basename(file_path)
    
    # Upload the file
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
    """
    Background task that processes the golf video.
    This runs asynchronously without blocking the API response.
    
    Args:
        input_path: Path to the input video file
        output_path: Path where processed video will be saved
        upload_to_cloud: Whether to upload to S3 after processing
    """
    try:
        logger.info(f"[PIPELINE START] Processing video: {input_path}")
        
        # Step 1: Process the video with GPS overlay
        logger.info("[STEP 1/3] Running video processing with GPS overlay...")
        process_video_with_overlay(input_path, output_path)
        logger.info(f"[STEP 1/3] ✓ Video processed successfully: {output_path}")
        
        # Step 2: Verify output file exists
        if not os.path.exists(output_path):
            raise FileNotFoundError(f"Processed video not found at {output_path}")
        
        output_size = os.path.getsize(output_path) / (1024 * 1024)  # Size in MB
        logger.info(f"[STEP 2/3] ✓ Output file verified: {output_size:.2f} MB")
        
        # Step 3: Upload to S3 (if enabled)
        if upload_to_cloud:
            logger.info("[STEP 3/3] Uploading to S3...")
            s3_object_name = f"processed/{os.path.basename(output_path)}"
            success = upload_to_s3(output_path, S3_BUCKET_NAME, s3_object_name)
            
            if success:
                logger.info(f"[STEP 3/3] ✓ S3 upload complete: s3://{S3_BUCKET_NAME}/{s3_object_name}")
            else:
                logger.warning("[STEP 3/3] ⚠ S3 upload failed, but local file is saved")
        else:
            logger.info("[STEP 3/3] Skipped S3 upload (disabled)")
        
        # Step 4: Cleanup - optionally delete input file to save space
        # Uncomment the next lines if you want to auto-delete input files
        # logger.info(f"[CLEANUP] Removing input file: {input_path}")
        # os.remove(input_path)
        
        logger.info(f"[PIPELINE COMPLETE] ✓ Successfully processed: {os.path.basename(input_path)}")
        
    except Exception as e:
        logger.error(f"[PIPELINE FAILED] ✗ Error processing {input_path}: {str(e)}", exc_info=True)
        # In production, you might want to:
        # - Send an error notification (email, Slack, etc.)
        # - Update a database status field
        # - Move failed files to a 'failed' directory


@app.get("/")
async def root():
    """Health check endpoint."""
    return {
        "status": "online",
        "service": "Reel Caddie Daddy Video Processor",
        "version": "1.0.0"
    }


@app.get("/health")
async def health_check():
    """Detailed health check."""
    return {
        "status": "healthy",
        "input_dir": str(INPUT_DIR),
        "output_dir": str(OUTPUT_DIR),
        "input_dir_exists": INPUT_DIR.exists(),
        "output_dir_exists": OUTPUT_DIR.exists(),
        "s3_bucket": S3_BUCKET_NAME
    }


@app.post("/process-video")
async def process_video(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    upload_to_s3_flag: bool = True
):
    """
    Upload and process a golf video asynchronously.
    
    The video processing happens in the background, so this endpoint
    returns immediately without waiting for processing to complete.
    
    Args:
        background_tasks: FastAPI's BackgroundTasks (injected automatically)
        file: The uploaded video file
        upload_to_s3_flag: Whether to upload processed video to S3 (default: True)
    
    Returns:
        JSON response with status and video ID
    """
    try:
        # Validate file type
        if not file.content_type or not file.content_type.startswith('video/'):
            raise HTTPException(
                status_code=400,
                detail=f"Invalid file type: {file.content_type}. Must be a video file."
            )
        
        # Generate unique filename to avoid collisions
        import uuid
        unique_id = str(uuid.uuid4())[:8]
        original_filename = file.filename or "video.mp4"
        base_name = Path(original_filename).stem
        extension = Path(original_filename).suffix
        
        # Create input and output paths
        input_filename = f"{base_name}_{unique_id}{extension}"
        output_filename = f"{base_name}_{unique_id}_processed.mp4"
        
        input_path = INPUT_DIR / input_filename
        output_path = OUTPUT_DIR / output_filename
        
        logger.info(f"[UPLOAD] Receiving video: {original_filename}")
        logger.info(f"[UPLOAD] Assigned ID: {unique_id}")
        
        # Save uploaded file to input directory
        with open(input_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        
        file_size = os.path.getsize(input_path) / (1024 * 1024)  # Size in MB
        logger.info(f"[UPLOAD] ✓ Saved to disk: {input_path} ({file_size:.2f} MB)")
        
        # Schedule background processing
        # This is NON-BLOCKING - the function returns immediately
        background_tasks.add_task(
            run_golf_pipeline,
            str(input_path),
            str(output_path),
            upload_to_s3_flag
        )
        
        logger.info(f"[UPLOAD] ✓ Background task scheduled for: {input_filename}")
        
        # Return immediately - processing happens in background
        return JSONResponse(
            status_code=202,  # 202 Accepted
            content={
                "status": "accepted",
                "message": "Video is processing in background.",
                "video_id": unique_id,
                "input_file": input_filename,
                "output_file": output_filename,
                "note": "Processing may take 30-60 seconds. Check output directory or S3 bucket."
            }
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[UPLOAD] ✗ Error handling upload: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Upload failed: {str(e)}")


@app.get("/status/{video_id}")
async def check_status(video_id: str):
    """
    Check the processing status of a video by its ID.
    
    Args:
        video_id: The unique video ID returned from /process-video
    
    Returns:
        Status information about the video
    """
    # Look for files with this video_id
    input_files = list(INPUT_DIR.glob(f"*{video_id}*"))
    output_files = list(OUTPUT_DIR.glob(f"*{video_id}*"))
    
    if not input_files:
        raise HTTPException(status_code=404, detail="Video ID not found")
    
    status = "processing"
    output_path = None
    
    if output_files:
        status = "completed"
        output_path = str(output_files[0])
    
    return {
        "video_id": video_id,
        "status": status,
        "input_file": str(input_files[0]) if input_files else None,
        "output_file": output_path,
        "note": "Check S3 bucket for uploaded file if status is completed"
    }


if __name__ == "__main__":
    import uvicorn
    
    # Run the server
    # Use 0.0.0.0 to accept connections from other devices on the network
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8001,  # Different port from Django (8000)
        log_level="info"
    )
