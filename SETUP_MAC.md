Quick macOS setup notes for this project

1) Create and activate a Python venv (recommended name: .venv-py311).

   python3 -m venv .venv-py311
   source .venv-py311/bin/activate

2) Install dependencies

   pip install --upgrade pip
   pip install -r requirements.txt

3) Ensure ffmpeg/ffprobe are installed (Homebrew recommended)

   brew install ffmpeg

  - If you need burned-in text support (drawtext), install a build with freetype/fontconfig.

4) Set Mapbox token (optional but required for map overlays)

   export MAPBOX_TOKEN=your_mapbox_token_here

5) Apply migrations and run the server

   python manage.py migrate
   python manage.py runserver

6) Optional: install mediapipe & OpenCV in the venv to enable pose overlays

   pip install opencv-python
   pip install mediapipe

Files added:
- scripts/setup_mac.sh  # helper script to create venv and show next commands
- scripts/verify_env.py # small script to print environment readiness
- SETUP_MAC.md          # these notes

Notes:
- The overlay code is defensive: it will skip text burn-in if ffmpeg lacks drawtext, and will skip pose overlays if mediapipe/OpenCV are not installed.
- To test environment after pulling code on the Mac mini, run the verifier inside the venv:

  source .venv-py311/bin/activate
  python scripts/verify_env.py

