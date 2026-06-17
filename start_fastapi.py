#!/usr/bin/env python3
"""
Startup script for FastAPI Video Processing Server
Run this to start the async video processing service on your Mac Mini.
"""

import os
import sys
from pathlib import Path

# Add the project directory to Python path
project_dir = Path(__file__).parent
sys.path.insert(0, str(project_dir))

def main():
    import uvicorn
    
    print("=" * 70)
    print("🎥  Reel Caddie Daddy - FastAPI Video Processing Server")
    print("=" * 70)
    print()
    print("📡 Server will be accessible at:")
    print("   ➜  http://localhost:8001/")
    print("   ➜  http://0.0.0.0:8001/ (network access)")
    print()
    print("📚 API Documentation:")
    print("   ➜  http://localhost:8001/docs (Swagger UI)")
    print("   ➜  http://localhost:8001/redoc (ReDoc)")
    print()
    print("📝 Endpoints:")
    print("   POST /process-video  - Upload and process video")
    print("   GET  /status/{id}    - Check processing status")
    print("   GET  /health         - Health check")
    print()
    print("⚙️  Configuration:")
    print(f"   Input Dir:  /Users/marcusduggs/videos/input/")
    print(f"   Output Dir: /Users/marcusduggs/videos/output/")
    print(f"   S3 Bucket:  {os.getenv('S3_BUCKET_NAME', 'Not configured')}")
    print()
    print("=" * 70)
    print("Starting server... Press CTRL+C to stop")
    print("=" * 70)
    print()
    
    # Run the FastAPI server
    uvicorn.run(
        "fastapi_server:app",
        host="0.0.0.0",
        port=8001,
        reload=True,  # Auto-reload on code changes (disable in production)
        log_level="info"
    )

if __name__ == "__main__":
    main()
