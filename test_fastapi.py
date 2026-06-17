#!/usr/bin/env python3
"""
Test script for FastAPI Video Processing Server
Run this after starting the FastAPI server to test uploads.
"""

import requests
import time
import sys
from pathlib import Path

# Server configuration
BASE_URL = "http://localhost:8001"

def test_health_check():
    """Test the health check endpoint."""
    print("🏥 Testing health check...")
    try:
        response = requests.get(f"{BASE_URL}/health")
        if response.status_code == 200:
            print("✅ Server is healthy!")
            print(f"   Response: {response.json()}")
            return True
        else:
            print(f"❌ Health check failed: {response.status_code}")
            return False
    except requests.exceptions.ConnectionError:
        print("❌ Cannot connect to server. Is it running?")
        print(f"   Make sure to start: python start_fastapi.py")
        return False

def test_video_upload(video_path: str):
    """Test video upload and processing."""
    print(f"\n📤 Testing video upload...")
    print(f"   Video: {video_path}")
    
    if not Path(video_path).exists():
        print(f"❌ Video file not found: {video_path}")
        return None
    
    try:
        # Upload video
        with open(video_path, 'rb') as f:
            files = {'file': (Path(video_path).name, f, 'video/mp4')}
            data = {'upload_to_s3_flag': 'false'}  # Disable S3 for testing
            
            print("   Uploading...")
            response = requests.post(
                f"{BASE_URL}/process-video",
                files=files,
                data=data
            )
        
        if response.status_code == 202:
            result = response.json()
            print("✅ Upload accepted!")
            print(f"   Video ID: {result['video_id']}")
            print(f"   Status: {result['status']}")
            print(f"   Output: {result['output_file']}")
            return result['video_id']
        else:
            print(f"❌ Upload failed: {response.status_code}")
            print(f"   Response: {response.text}")
            return None
            
    except Exception as e:
        print(f"❌ Upload error: {e}")
        return None

def test_status_check(video_id: str):
    """Test status check endpoint."""
    print(f"\n🔍 Checking status for video ID: {video_id}")
    
    try:
        response = requests.get(f"{BASE_URL}/status/{video_id}")
        
        if response.status_code == 200:
            result = response.json()
            print(f"✅ Status: {result['status']}")
            print(f"   Input: {result.get('input_file', 'N/A')}")
            print(f"   Output: {result.get('output_file', 'N/A')}")
            return result['status']
        else:
            print(f"❌ Status check failed: {response.status_code}")
            return None
            
    except Exception as e:
        print(f"❌ Status check error: {e}")
        return None

def main():
    print("=" * 70)
    print("🧪 FastAPI Video Processing Server - Test Suite")
    print("=" * 70)
    
    # Test 1: Health check
    if not test_health_check():
        print("\n❌ Server is not running. Start it with: python start_fastapi.py")
        sys.exit(1)
    
    # Test 2: Video upload (if video path provided)
    if len(sys.argv) > 1:
        video_path = sys.argv[1]
        video_id = test_video_upload(video_path)
        
        if video_id:
            # Wait a bit for processing
            print("\n⏳ Waiting 5 seconds for processing to start...")
            time.sleep(5)
            
            # Test 3: Status check
            status = test_status_check(video_id)
            
            if status == "processing":
                print("\n💡 Video is still processing. Check again in 30-60 seconds.")
                print(f"   Command: curl http://localhost:8001/status/{video_id}")
            elif status == "completed":
                print("\n🎉 Video processing completed!")
    else:
        print("\n💡 To test video upload, run:")
        print(f"   python {sys.argv[0]} /path/to/video.mov")
    
    print("\n" + "=" * 70)
    print("✅ Test suite completed!")
    print("\n📚 Interactive docs: http://localhost:8001/docs")
    print("=" * 70)

if __name__ == "__main__":
    main()
