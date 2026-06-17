# Golf Caddie (Django)

⛳ A Django app for logging golf shots and analyzing swing videos with GPS-based map overlays.

## ✨ Features

- 📹 Upload golf swing videos directly from your iPhone
- 🗺️ Automatic GPS extraction and Mapbox map overlay
- 📱 Mobile-responsive interface optimized for iOS Safari
- 🎯 Shot tracking with club and distance information
- 🌐 Access from any device on your local network

## 🚀 Quick Start

### 1. Create and activate a virtualenv (optional but recommended)

```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 2. Install requirements

```bash
pip install -r requirements.txt
```

### 3. Run migrations

```bash
python manage.py migrate
```

### 4. Start the server

**Option A: Simple start (computer only)**
```bash
python manage.py runserver
```
Then open http://127.0.0.1:8000/

**Option B: Mobile access (iPhone/iPad)** ⭐ Recommended
```bash
python start_mobile.py
```
This will display your local network URL, for example:
```
📱 Access from your iPhone/iPad:
   ➜  http://192.168.1.100:8000/
```

**Option C: Manual start with mobile access**
```bash
python manage.py runserver 0.0.0.0:8000
```

## 📱 Accessing from Your iPhone

### Prerequisites
- Your iPhone and Mac must be on the **same Wi-Fi network**
- Note the IP address displayed when you run `python start_mobile.py`

### Steps
1. **Start the server** on your Mac:
   ```bash
   python start_mobile.py
   ```

2. **Note the Local Network URL** (e.g., `http://192.168.1.100:8000/`)

3. **Open Safari** on your iPhone

4. **Enter the URL** in the address bar

5. **Upload videos** directly from your iPhone camera roll! 📸

### Troubleshooting Mobile Access

**Can't connect from iPhone?**
- ✓ Check that both devices are on the same Wi-Fi network
- ✓ Make sure your Mac's firewall allows incoming connections
- ✓ Try turning off VPN if you're using one
- ✓ Verify the IP address hasn't changed (run the script again)

**To find your Mac's IP manually:**
```bash
# macOS
ifconfig | grep "inet " | grep -v 127.0.0.1

# Or check System Settings > Network
```

## 🔐 Secure Mobile Access (Optional)

For accessing from outside your local network or for HTTPS:

### Option 1: ngrok (Easy)
```bash
# Install ngrok
brew install ngrok

# Run the Django server
python manage.py runserver

# In another terminal, create a tunnel
ngrok http 8000
```
ngrok will provide a public HTTPS URL you can access from anywhere.

### Option 2: Cloudflare Tunnel
```bash
# Install cloudflared
brew install cloudflare/cloudflare/cloudflared

# Run the server
python manage.py runserver

# Create tunnel
cloudflared tunnel --url http://localhost:8000
```

## 🎥 Video Processing Features

The app automatically:
1. **Extracts GPS coordinates** from video metadata (Apple QuickTime format)
2. **Fetches a custom map** from Mapbox API showing the shot location
3. **Overlays the map** on the bottom-right corner of the video
4. **Falls back** to a static map if GPS data isn't available

### Supported Video Formats
- ✅ MOV (iPhone default)
- ✅ MP4
- ✅ Any format supported by ffmpeg

### GPS Coordinate Support
The app can extract GPS from:
- Apple QuickTime ISO6709 tags (`com.apple.quicktime.location.ISO6709`)
- Generic location tags
- Direct GPS latitude/longitude metadata

## 🛠️ Configuration

### Mapbox API Token
The Mapbox token is configured in `golf_caddie/settings.py`:
```python
MAPBOX_TOKEN = 'your-token-here'
```

You can also set it as an environment variable:
```bash
export MAPBOX_TOKEN='your-token-here'
```

### Map Overlay Size
Edit `utils/overlay.py` to adjust the overlay size:
```python
# Line ~295
overlay_w = max(64, int(vwidth * 0.30))  # 30% of video width
```

Change `0.30` to:
- `0.20` for smaller overlay (20%)
- `0.40` for larger overlay (40%)
- `0.50` for very large overlay (50%)

## 📊 Database

The app uses SQLite by default (`db.sqlite3`). To reset the database:
```bash
rm db.sqlite3
python manage.py migrate
```

## 🔑 Admin Access

Create a superuser to access the Django admin panel at `/admin/`:
```bash
python manage.py createsuperuser
```

## 📝 Notes

- The project uses `ffmpeg` and `ffprobe` for video processing
- GPS extraction requires videos with embedded location metadata
- Processed videos are saved to `media/output/`
- Original uploads are saved to `media/input/`
- Video processing logs are saved to `media/logs/`

## 🖥️ System Requirements (macOS)

To analyze videos with GPS-based map overlays, the app uses `ffmpeg` and `ffprobe`.

1) Install Homebrew (package manager)

```zsh
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
```

2) Add Homebrew to PATH

- Apple Silicon:

```zsh
echo 'eval "$(/opt/homebrew/bin/brew shellenv)"' >> ~/.zprofile
eval "$(/opt/homebrew/bin/brew shellenv)"
```

- Intel:

```zsh
echo 'eval "$(/usr/local/bin/brew shellenv)"' >> ~/.zprofile
eval "$(/usr/local/bin/brew shellenv)"
```

3) Install ffmpeg (includes ffprobe)

```zsh
brew install ffmpeg
```

4) Verify installation

```zsh
which ffprobe
which ffmpeg
ffprobe -version
ffmpeg -version
```

If you prefer not to use Homebrew, download prebuilt ffmpeg/ffprobe binaries and place them in `~/bin`, then add `~/bin` to your PATH:

```zsh
echo 'export PATH="$HOME/bin:$PATH"' >> ~/.zshrc
source ~/.zshrc
```

## 🧪 Troubleshooting

- "Processing Failed" on Analyze page:
   - Ensure `ffmpeg` and `ffprobe` are installed and visible in your shell (`which ffprobe`).
   - Inspect the most recent log under `media/logs/overlay_*.log` for the exact ffmpeg command and error.
   - If GPS metadata is missing, the app falls back to a static map (`test_map.png`).


## 🤝 Development

### File Structure
```
Golf_Caddie/
├── golf_caddie/         # Django project settings
├── shots/               # Main app
├── utils/               # Video processing utilities
│   └── overlay.py       # GPS extraction & map overlay
├── media/
│   ├── input/          # Uploaded videos
│   ├── output/         # Processed videos with map overlay
│   └── logs/           # Processing logs
├── templates/           # HTML templates
├── static/             # Static files (CSS, JS)
├── start_mobile.py     # Mobile access startup script
└── manage.py           # Django management script
```

### Key Technologies
- Django 4.2+
- ffmpeg/ffprobe (video processing)
- Mapbox Static Images API (map generation)
- Tailwind CSS (styling)
- SQLite (database)

## 📄 License

This project is for personal use.

## 🐛 Issues?

Check the logs in `media/logs/` for debugging video processing issues.

---

**Happy golfing! ⛳🏌️‍♂️**
