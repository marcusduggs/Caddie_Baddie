# FastAPI Async Video Processing Server

This FastAPI server allows your Mac Mini to process golf videos **asynchronously** without keeping connections open.

## 🚀 Features

- **Asynchronous Processing**: Upload returns immediately, processing happens in background
- **No Blocking**: Server can handle multiple uploads while processing videos
- **S3 Integration**: Auto-uploads processed videos to Amazon S3
- **GPS Overlay**: Uses your existing `process_video_with_overlay()` function
- **RESTful API**: Easy to integrate with any client (web, mobile, etc.)
- **Auto Documentation**: Built-in Swagger UI at `/docs`

## 📦 Installation

### 1. Install FastAPI Dependencies

```bash
cd /Users/marcusduggs/Golf_Caddie
pip install -r fastapi_requirements.txt
```

### 2. Configure AWS Credentials (Optional - for S3 upload)

```bash
# Set environment variables
export AWS_ACCESS_KEY_ID="your_access_key"
export AWS_SECRET_ACCESS_KEY="your_secret_key"
export S3_BUCKET_NAME="your-golf-videos-bucket"
export AWS_REGION="us-east-1"
```

Or create `~/.aws/credentials`:
```ini
[default]
aws_access_key_id = your_access_key
aws_secret_access_key = your_secret_key
```

### 3. Create Video Directories

```bash
mkdir -p /Users/marcusduggs/videos/input
mkdir -p /Users/marcusduggs/videos/output
```

## 🎬 Usage

### Start the Server

```bash
python start_fastapi.py
```

The server will run on **http://0.0.0.0:8001/**

### API Endpoints

#### 1. **Upload Video for Processing** (Main Endpoint)

```bash
# Upload a video - returns immediately
curl -X POST "http://localhost:8001/process-video" \
  -F "file=@/path/to/golf_swing.mov" \
  -F "upload_to_s3_flag=true"
```

**Response** (202 Accepted):
```json
{
  "status": "accepted",
  "message": "Video is processing in background.",
  "video_id": "a3f7b9c2",
  "input_file": "golf_swing_a3f7b9c2.mov",
  "output_file": "golf_swing_a3f7b9c2_processed.mp4",
  "note": "Processing may take 30-60 seconds. Check output directory or S3 bucket."
}
```

#### 2. **Check Processing Status**

```bash
curl "http://localhost:8001/status/a3f7b9c2"
```

**Response**:
```json
{
  "video_id": "a3f7b9c2",
  "status": "completed",
  "input_file": "/Users/marcusduggs/videos/input/golf_swing_a3f7b9c2.mov",
  "output_file": "/Users/marcusduggs/videos/output/golf_swing_a3f7b9c2_processed.mp4",
  "note": "Check S3 bucket for uploaded file if status is completed"
}
```

#### 3. **Health Check**

```bash
curl "http://localhost:8001/health"
```

### Interactive API Documentation

FastAPI provides automatic interactive docs:

- **Swagger UI**: http://localhost:8001/docs
- **ReDoc**: http://localhost:8001/redoc

You can test uploads directly in the browser!

## 🔧 Customization

### Change Directory Paths

Edit `fastapi_server.py`:

```python
INPUT_DIR = Path("/your/custom/input/path")
OUTPUT_DIR = Path("/your/custom/output/path")
```

### Disable S3 Upload

When uploading, set `upload_to_s3_flag=false`:

```bash
curl -X POST "http://localhost:8001/process-video" \
  -F "file=@video.mov" \
  -F "upload_to_s3_flag=false"
```

### Auto-Delete Input Files

Uncomment these lines in `run_golf_pipeline()`:

```python
# logger.info(f"[CLEANUP] Removing input file: {input_path}")
# os.remove(input_path)
```

### Change Port

Edit `start_fastapi.py`:

```python
port=8002,  # Change from 8001 to any port
```

## 🏗️ How It Works

```
Client                  FastAPI Server              Background Task
  |                           |                            |
  | POST /process-video       |                            |
  |-------------------------->|                            |
  |                           | Save file to input/        |
  |                           | Schedule background task   |
  | <-- 202 Accepted ---------|                            |
  | (returns immediately!)    |                            |
  |                           |                            |
  |                           |  Start processing -------->|
  |                           |                            | 1. Extract GPS
  |                           |                            | 2. Fetch Mapbox
  |                           |                            | 3. Overlay video
  |                           |                            | 4. Upload to S3
  |                           |<------ Complete ---------- |
  |                           |                            |
  | GET /status/{id}          |                            |
  |-------------------------->|                            |
  | <-- status: completed ----|                            |
```

## 📊 Example Workflow

### 1. Upload from Command Line

```bash
# Upload a video
RESPONSE=$(curl -s -X POST "http://localhost:8001/process-video" \
  -F "file=@Marcus.mov")

echo $RESPONSE
# {"status":"accepted","video_id":"a3f7b9c2",...}

# Extract video ID
VIDEO_ID=$(echo $RESPONSE | python -c "import sys, json; print(json.load(sys.stdin)['video_id'])")

# Wait a bit
sleep 30

# Check status
curl "http://localhost:8001/status/$VIDEO_ID"
```

### 2. Upload from Python

```python
import requests

# Upload video
with open("Marcus.mov", "rb") as f:
    response = requests.post(
        "http://localhost:8001/process-video",
        files={"file": f},
        data={"upload_to_s3_flag": "true"}
    )

result = response.json()
print(f"Video ID: {result['video_id']}")

# Check status later
import time
time.sleep(30)

status_response = requests.get(f"http://localhost:8001/status/{result['video_id']}")
print(status_response.json())
```

### 3. Upload from JavaScript/Web

```javascript
const formData = new FormData();
formData.append('file', videoFile);
formData.append('upload_to_s3_flag', 'true');

fetch('http://localhost:8001/process-video', {
  method: 'POST',
  body: formData
})
.then(res => res.json())
.then(data => {
  console.log('Video ID:', data.video_id);
  // Poll status endpoint
  checkStatus(data.video_id);
});
```

## 🔒 Production Considerations

### Run with Gunicorn (Production Server)

```bash
pip install gunicorn
gunicorn fastapi_server:app -w 4 -k uvicorn.workers.UvicornWorker --bind 0.0.0.0:8001
```

### Run as System Service (macOS)

Create `~/Library/LaunchAgents/com.reelcaddiedaddy.fastapi.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.reelcaddiedaddy.fastapi</string>
    <key>ProgramArguments</key>
    <array>
        <string>/path/to/python</string>
        <string>/Users/marcusduggs/Golf_Caddie/start_fastapi.py</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
</dict>
</plist>
```

Load it:
```bash
launchctl load ~/Library/LaunchAgents/com.reelcaddiedaddy.fastapi.plist
```

### Add HTTPS (with ngrok)

```bash
brew install ngrok
ngrok http 8001
```

## 📝 Logging

Logs are printed to stdout/stderr. To save to file:

```bash
python start_fastapi.py > fastapi.log 2>&1 &
```

Or tail logs in real-time:

```bash
python start_fastapi.py 2>&1 | tee fastapi.log
```

## 🐛 Troubleshooting

### Port Already in Use

```bash
# Find process using port 8001
lsof -ti :8001

# Kill it
kill -9 $(lsof -ti :8001)
```

### Import Errors

```bash
# Make sure you're in the correct directory
cd /Users/marcusduggs/Golf_Caddie

# Verify overlay.py exists
ls utils/overlay.py
```

### S3 Upload Fails

Check AWS credentials:
```bash
aws s3 ls s3://your-bucket-name/
```

Disable S3 by setting `upload_to_s3_flag=false` when uploading.

## 🎯 Next Steps

1. **Install dependencies**: `pip install -r fastapi_requirements.txt`
2. **Start server**: `python start_fastapi.py`
3. **Test upload**: Visit http://localhost:8001/docs
4. **Integrate with your app**: Use the API from Django, mobile app, etc.

## 🆚 FastAPI vs Django

- **Django**: Synchronous, blocks during processing, good for web UI
- **FastAPI**: Asynchronous, returns immediately, good for API backend

You can run **both simultaneously**:
- Django on port 8000 (web interface)
- FastAPI on port 8001 (async video processing API)

---

**Created for Reel Caddie Daddy** 🏌️⛳
