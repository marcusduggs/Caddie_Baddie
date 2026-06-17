# 🚀 FastAPI Async Video Processing - Quick Start

## What I Created

I've built a **FastAPI server** that processes golf videos **asynchronously** on your Mac Mini without keeping connections open.

### Files Created:
1. **`fastapi_server.py`** - Main FastAPI application
2. **`start_fastapi.py`** - Easy startup script
3. **`test_fastapi.py`** - Test script
4. **`fastapi_requirements.txt`** - Dependencies
5. **`FASTAPI_README.md`** - Full documentation

## ⚡ Quick Start (3 Steps)

### Step 1: Install Dependencies
```bash
cd /Users/marcusduggs/Golf_Caddie
pip install -r fastapi_requirements.txt
```

### Step 2: Start the Server
```bash
python start_fastapi.py
```

Server runs on **http://localhost:8001/**

### Step 3: Test It
```bash
# Test health check
python test_fastapi.py

# Test with a video
python test_fastapi.py media/input/Marcus.mov
```

## 🎯 How to Use

### Upload a Video (Returns Immediately!)

```bash
curl -X POST "http://localhost:8001/process-video" \
  -F "file=@Marcus.mov"
```

**Response** (instant!):
```json
{
  "status": "accepted",
  "video_id": "a3f7b9c2",
  "message": "Video is processing in background."
}
```

### Check Status

```bash
curl "http://localhost:8001/status/a3f7b9c2"
```

### Interactive Docs

Open in browser: **http://localhost:8001/docs**

You can upload and test directly in the browser!

## 🏗️ Architecture

```
iPhone/Client                Mac Mini Server
     |                            |
     | POST video                 |
     |--------------------------->| 1. Save file
     |<--- 202 ACCEPTED ----------| 2. Return immediately
     | (instant response!)        |
     |                            | 3. Process in background
     |                            |    - Extract GPS
     |                            |    - Fetch Mapbox
     |                            |    - Overlay video
     |                            |    - Upload to S3
     |                            |
     | GET /status/id             |
     |--------------------------->|
     |<--- status: completed -----|
```

## ✨ Key Features

✅ **Non-Blocking**: Upload returns in milliseconds  
✅ **Background Processing**: Videos process without keeping connection open  
✅ **S3 Integration**: Auto-uploads to Amazon S3 (optional)  
✅ **Status Tracking**: Check processing status by video ID  
✅ **Auto Documentation**: Built-in Swagger UI  
✅ **Existing Code**: Uses your `process_video_with_overlay()` function  

## 📁 Directory Structure

```
/Users/marcusduggs/videos/
  ├── input/          # Uploaded videos
  └── output/         # Processed videos
```

These directories are auto-created on first run.

## 🔧 Configuration

### Directories (Optional)

Edit `fastapi_server.py`:
```python
INPUT_DIR = Path("/your/custom/path/input")
OUTPUT_DIR = Path("/your/custom/path/output")
```

### AWS S3 (Optional)

```bash
export S3_BUCKET_NAME="your-bucket-name"
export AWS_ACCESS_KEY_ID="your-key"
export AWS_SECRET_ACCESS_KEY="your-secret"
```

Or skip S3 entirely - videos save locally to output directory.

### Port (Optional)

Edit `start_fastapi.py`:
```python
port=8002,  # Change from 8001
```

## 🎬 Example Workflow

### From Python:
```python
import requests
import time

# Upload
response = requests.post(
    "http://localhost:8001/process-video",
    files={"file": open("golf.mov", "rb")}
)
video_id = response.json()["video_id"]

# Wait
time.sleep(30)

# Check status
status = requests.get(f"http://localhost:8001/status/{video_id}")
print(status.json())
```

### From JavaScript:
```javascript
const formData = new FormData();
formData.append('file', videoFile);

fetch('http://localhost:8001/process-video', {
  method: 'POST',
  body: formData
})
.then(res => res.json())
.then(data => console.log('Video ID:', data.video_id));
```

## 🆚 Django vs FastAPI

You can run **BOTH** simultaneously:

| Feature | Django (port 8000) | FastAPI (port 8001) |
|---------|-------------------|---------------------|
| Purpose | Web UI, forms | API, async processing |
| Processing | Synchronous (blocks) | Asynchronous (background) |
| Response | Waits for completion | Returns immediately |
| Use For | User interface | Video uploads from apps |

**Recommendation**: Use FastAPI for video uploads, Django for viewing/browsing.

## 🐛 Troubleshooting

### Server Won't Start
```bash
# Check if port is in use
lsof -ti :8001

# Kill existing process
kill -9 $(lsof -ti :8001)
```

### Import Errors
```bash
# Reinstall dependencies
pip install -r fastapi_requirements.txt

# Verify utils/overlay.py exists
ls utils/overlay.py
```

### Test Connection
```bash
curl http://localhost:8001/health
```

## 📊 Monitoring

### View Logs in Real-Time
```bash
python start_fastapi.py
# Logs print to console
```

### Save Logs to File
```bash
python start_fastapi.py > fastapi.log 2>&1 &
tail -f fastapi.log
```

## 🚀 Production Deployment

### Run as Background Service
```bash
nohup python start_fastapi.py > fastapi.log 2>&1 &
```

### Auto-Start on Mac Boot
See `FASTAPI_README.md` for LaunchAgent setup.

### With Gunicorn (Production Server)
```bash
pip install gunicorn
gunicorn fastapi_server:app -w 4 -k uvicorn.workers.UvicornWorker --bind 0.0.0.0:8001
```

## 📚 Full Documentation

See **`FASTAPI_README.md`** for:
- Detailed API reference
- Production deployment
- S3 configuration
- Advanced customization
- Integration examples

## 🎉 You're Ready!

1. **Install**: `pip install -r fastapi_requirements.txt`
2. **Start**: `python start_fastapi.py`
3. **Test**: Open http://localhost:8001/docs
4. **Upload**: Use the Swagger UI to test uploads

The server processes videos in the background while returning immediately to clients!

---

**Questions?** Check `FASTAPI_README.md` or the interactive docs at http://localhost:8001/docs
