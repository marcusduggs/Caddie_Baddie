#!/usr/bin/env python3
"""
Example: Upload video from iPhone/web browser to FastAPI server
This shows how to integrate async video processing with your mobile app.
"""

from flask import Flask, request, render_template_string, jsonify
import requests

app = Flask(__name__)

# Your Mac Mini FastAPI server URL
FASTAPI_SERVER = "http://10.0.0.20:8001"  # Use your Mac's local IP

# Simple HTML form for iPhone uploads
HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Reel Caddie Daddy - Upload</title>
    <style>
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
            max-width: 500px;
            margin: 50px auto;
            padding: 20px;
        }
        h1 { color: #16a34a; }
        input[type="file"] {
            display: block;
            width: 100%;
            padding: 15px;
            margin: 20px 0;
            font-size: 16px;
            border: 2px solid #16a34a;
            border-radius: 8px;
        }
        button {
            width: 100%;
            padding: 15px;
            font-size: 18px;
            background: #16a34a;
            color: white;
            border: none;
            border-radius: 8px;
            cursor: pointer;
        }
        button:disabled {
            background: #gray;
        }
        #status {
            margin-top: 20px;
            padding: 15px;
            border-radius: 8px;
            display: none;
        }
        .success { background: #d1fae5; color: #065f46; }
        .error { background: #fee2e2; color: #991b1b; }
        .processing { background: #dbeafe; color: #1e40af; }
    </style>
</head>
<body>
    <h1>⛳ Upload Golf Video</h1>
    
    <form id="uploadForm">
        <input type="file" id="videoFile" accept="video/*" required>
        <button type="submit" id="submitBtn">🚀 Process Video</button>
    </form>
    
    <div id="status"></div>
    
    <script>
        const form = document.getElementById('uploadForm');
        const submitBtn = document.getElementById('submitBtn');
        const status = document.getElementById('status');
        
        form.addEventListener('submit', async (e) => {
            e.preventDefault();
            
            const fileInput = document.getElementById('videoFile');
            const file = fileInput.files[0];
            
            if (!file) {
                alert('Please select a video');
                return;
            }
            
            // Disable button during upload
            submitBtn.disabled = true;
            submitBtn.textContent = '⏳ Uploading...';
            
            // Show processing status
            status.style.display = 'block';
            status.className = 'processing';
            status.innerHTML = '📤 Uploading video to Mac Mini...';
            
            try {
                // Upload to our proxy endpoint
                const formData = new FormData();
                formData.append('file', file);
                
                const response = await fetch('/upload', {
                    method: 'POST',
                    body: formData
                });
                
                const result = await response.json();
                
                if (result.status === 'accepted') {
                    status.className = 'success';
                    status.innerHTML = `
                        <strong>✅ Upload Successful!</strong><br>
                        Video ID: ${result.video_id}<br>
                        <br>
                        Your video is processing in the background.<br>
                        This usually takes 30-60 seconds.<br>
                        <br>
                        <button onclick="checkStatus('${result.video_id}')">Check Status</button>
                    `;
                } else {
                    throw new Error(result.message || 'Upload failed');
                }
            } catch (error) {
                status.className = 'error';
                status.innerHTML = `
                    <strong>❌ Upload Failed</strong><br>
                    ${error.message}
                `;
            } finally {
                submitBtn.disabled = false;
                submitBtn.textContent = '🚀 Process Video';
            }
        });
        
        window.checkStatus = async (videoId) => {
            status.className = 'processing';
            status.innerHTML = '🔍 Checking status...';
            
            try {
                const response = await fetch(`/status/${videoId}`);
                const result = await response.json();
                
                if (result.status === 'completed') {
                    status.className = 'success';
                    status.innerHTML = `
                        <strong>🎉 Processing Complete!</strong><br>
                        Video ID: ${videoId}<br>
                        Status: ${result.status}<br>
                        <br>
                        Output file: ${result.output_file}
                    `;
                } else {
                    status.className = 'processing';
                    status.innerHTML = `
                        <strong>⏳ Still Processing...</strong><br>
                        Video ID: ${videoId}<br>
                        Status: ${result.status}<br>
                        <br>
                        <button onclick="checkStatus('${videoId}')">Check Again</button>
                    `;
                }
            } catch (error) {
                status.className = 'error';
                status.innerHTML = `
                    <strong>❌ Status Check Failed</strong><br>
                    ${error.message}
                `;
            }
        };
    </script>
</body>
</html>
"""

@app.route('/')
def index():
    """Show upload form."""
    return render_template_string(HTML_TEMPLATE)

@app.route('/upload', methods=['POST'])
def upload():
    """
    Proxy endpoint that forwards uploads to FastAPI server.
    This runs on your Mac and forwards to the FastAPI processing server.
    """
    try:
        if 'file' not in request.files:
            return jsonify({'status': 'error', 'message': 'No file provided'}), 400
        
        file = request.files['file']
        
        # Forward to FastAPI server
        files = {'file': (file.filename, file.stream, file.content_type)}
        data = {'upload_to_s3_flag': 'false'}  # Disable S3 for now
        
        response = requests.post(
            f"{FASTAPI_SERVER}/process-video",
            files=files,
            data=data
        )
        
        return jsonify(response.json()), response.status_code
        
    except requests.exceptions.ConnectionError:
        return jsonify({
            'status': 'error',
            'message': 'Cannot connect to FastAPI server. Is it running?'
        }), 503
    except Exception as e:
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500

@app.route('/status/<video_id>')
def check_status(video_id):
    """Check processing status."""
    try:
        response = requests.get(f"{FASTAPI_SERVER}/status/{video_id}")
        return jsonify(response.json()), response.status_code
    except Exception as e:
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500

if __name__ == '__main__':
    print("=" * 70)
    print("📱 iPhone Upload Interface for FastAPI Video Processing")
    print("=" * 70)
    print()
    print("🌐 Access from iPhone:")
    print("   http://10.0.0.20:5000/")
    print()
    print("⚠️  Make sure FastAPI server is running on port 8001!")
    print("   python start_fastapi.py")
    print()
    print("=" * 70)
    print()
    
    # Run on all interfaces so iPhone can access
    app.run(host='0.0.0.0', port=5000, debug=True)
