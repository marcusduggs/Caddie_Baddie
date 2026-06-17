# GPS-Based Dynamic Map Overlay - Implementation Summary

## 📍 Overview
The Golf Caddie app now automatically extracts GPS coordinates from uploaded golf videos and overlays a custom map showing the exact location where the shot was taken.

## 🎯 Key Features Implemented

### 1. **GPS Coordinate Extraction** (`_extract_coords_with_ffprobe`)
   - **Location**: `/Users/marcusduggs/Golf_Caddie/utils/overlay.py`
   - **What it does**: 
     - Extracts GPS coordinates from video metadata using ffprobe
     - Supports multiple metadata formats:
       - ✅ Apple QuickTime ISO6709 format: `com.apple.quicktime.location.ISO6709` (e.g., "+21.9173-159.5286+000.000/")
       - ✅ Generic location tags: `location`
       - ✅ Direct GPS tags: `GPSLatitude` / `GPSLongitude`
   - **Output**: Returns `(longitude, latitude)` tuple or `None` if no coordinates found
   - **Debugging**: Prints extracted coordinates to console with `[GPS]` prefix

### 2. **Dynamic Map Fetching** (`_fetch_mapbox_static_image`)
   - **Location**: `/Users/marcusduggs/Golf_Caddie/utils/overlay.py`
   - **What it does**:
     - Calls the Mapbox Static Images API
     - Generates a custom map centered on the extracted GPS coordinates
     - Adds a red pin marker at the shot location
     - Downloads the map image to a temporary file
   - **API Details**:
     - Endpoint: `https://api.mapbox.com/styles/v1/mapbox/streets-v11/static/...`
     - Map style: `streets-v11`
     - Marker: Small red pin (`pin-s+ff0000`)
     - Default size: 400x300 pixels
     - Default zoom: 14
     - Token: Uses `MAPBOX_TOKEN` from `settings.py` or environment variable
   - **Debugging**: Prints API status with `[Mapbox]` prefix

### 3. **Video Processing** (`process_video_with_overlay`)
   - **Location**: `/Users/marcusduggs/Golf_Caddie/utils/overlay.py`
   - **Workflow**:
     1. Extract GPS coordinates from input video
     2. If coordinates found → Fetch custom map from Mapbox API
     3. If coordinates not found → Use static fallback map (`test_map.png`)
     4. Overlay map on bottom-right corner of video (10px margin, 20% of video width)
     5. Process video using ffmpeg
     6. Save processed video to `MEDIA_ROOT/output/`
     7. Clean up temporary files
   - **Error Handling**:
     - Gracefully falls back to static map if GPS extraction fails
     - Falls back to static map if Mapbox API call fails
     - Logs all errors for debugging
   - **Output**: Returns path to processed video

## 📊 Example Test Results

### Test Video: Marcus.mov
```
============================================================
Starting GPS-based map overlay process
============================================================
[GPS] Extracted coordinates from video: latitude=21.9173, longitude=-159.5286
[Mapbox] Fetching map image for coordinates: (-159.5286, 21.9173)
[Mapbox] Map image downloaded successfully: 18121 bytes
[Success] Using dynamic map based on video GPS coordinates
[FFmpeg] Processing video with overlay...
[Cleanup] Removed temporary map file
[Success] Processed video saved to: /Users/marcusduggs/Golf_Caddie/media/output/Marcus_dynamic_map_test.mp4
============================================================
```

**Location**: Kauai, Hawaii 🏝️
- **Latitude**: 21.9173° N
- **Longitude**: -159.5286° W
- **Output Size**: 2,639,818 bytes (2.5 MB)

## 🔧 Configuration

### Mapbox API Token
The Mapbox token is configured in `/Users/marcusduggs/Golf_Caddie/golf_caddie/settings.py`:

```python
MAPBOX_TOKEN = 'pk.eyJ1IjoibGR1Z2dzIiwiYSI6ImNtZ3d2bzVybjBsNGkya3ByaGY5MXA1MGIifQ.OVODkq1EaazsvaXtyeFE4A'
```

You can also override this with the `MAPBOX_TOKEN` environment variable.

### FFmpeg Paths
The code uses full paths to avoid PATH issues:
- **ffmpeg**: `/usr/local/bin/ffmpeg`
- **ffprobe**: `/usr/local/bin/ffprobe`

## 🎨 Customization Options

### Map Appearance
You can customize the map by modifying parameters in `_fetch_mapbox_static_image()`:

```python
def _fetch_mapbox_static_image(lon, lat, output_path, 
                                width=400,      # Map width in pixels
                                height=300,     # Map height in pixels  
                                zoom=14):       # Zoom level (1-20)
```

### Map Styles
Change the map style by modifying the URL in `_fetch_mapbox_static_image()`:
- Current: `streets-v11` (street map)
- Options: `satellite-v9`, `outdoors-v11`, `dark-v10`, `light-v10`

### Marker Style
Modify the marker appearance:
```python
overlay = f"pin-s+ff0000({lon},{lat})"  # Small red pin
```
- Size: `pin-s` (small), `pin-m` (medium), `pin-l` (large)
- Color: `+ff0000` (red) - change to any hex color

## 🚀 How It Works in the Django App

### User Workflow:
1. User uploads a golf video via `/analyze/`
2. Video is saved to `MEDIA_ROOT/input/`
3. `process_video_with_overlay()` is called automatically
4. GPS coordinates are extracted (if present)
5. Custom map is fetched from Mapbox API
6. Map is overlaid on video
7. Processed video is saved to `MEDIA_ROOT/output/`
8. User is redirected to detail page showing both videos

### Django View Integration:
The view (`analyze_upload` in `/shots/views.py`) calls:
```python
from utils.overlay import process_video_with_overlay

process_video_with_overlay(input_path, output_path)
```

## 📝 Debugging

### Enable Verbose Logging
The code includes extensive logging:
- **Console output**: Real-time progress with `[GPS]`, `[Mapbox]`, and `[FFmpeg]` prefixes
- **Log files**: Detailed ffmpeg output saved to `MEDIA_ROOT/logs/overlay_*.log`

### Common Issues & Solutions

#### No GPS coordinates found
```
[GPS] No GPS coordinates found in video metadata - using default location
[Fallback] Using static map: /Users/marcusduggs/Golf_Caddie/test_map.png
```
**Solution**: This is normal for videos without GPS metadata. The system falls back to the static map.

#### Mapbox API failure
```
[Mapbox] ERROR: Failed to fetch map: HTTP Error 401: Unauthorized
```
**Solution**: Check that `MAPBOX_TOKEN` is valid in `settings.py`.

#### FFmpeg errors
Check the log file mentioned in the error message:
```
ffmpeg failed (log: /Users/marcusduggs/Golf_Caddie/media/logs/overlay_abc123.log)
```

## 🎯 Testing

### Test a video manually:
```python
python -c "
import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'golf_caddie.settings')
import django
django.setup()
from utils.overlay import process_video_with_overlay

process_video_with_overlay(
    '/path/to/input.mov',
    '/path/to/output.mp4'
)
"
```

### Test GPS extraction only:
```python
from utils.overlay import _extract_coords_with_ffprobe

coords = _extract_coords_with_ffprobe('/path/to/video.mov')
print(f"Coordinates: {coords}")
```

## 📦 Dependencies

All required Python modules are standard library or already installed:
- `subprocess` - Running ffmpeg/ffprobe
- `json` - Parsing ffprobe output
- `re` - Regex for coordinate parsing
- `urllib.request` - Downloading maps from Mapbox API
- `tempfile` - Temporary file storage
- `logging` - Debug logging

## ✨ Future Enhancements

Potential improvements:
1. **Adaptive zoom**: Calculate zoom level based on video duration or shot type
2. **Multiple map styles**: Let users choose satellite vs. street view
3. **Course detection**: Identify golf course names using reverse geocoding
4. **Wind/weather overlay**: Add real-time weather data to the map
5. **Shot trajectory**: Draw the ball's flight path on the map
6. **Batch processing**: Process multiple videos with GPS-based maps

## 📄 Files Modified

1. **`/Users/marcusduggs/Golf_Caddie/utils/overlay.py`** (NEW)
   - GPS coordinate extraction
   - Mapbox API integration
   - Video overlay processing

2. **`/Users/marcusduggs/Golf_Caddie/shots/views.py`**
   - Calls `process_video_with_overlay()`
   - Error handling and user feedback

3. **`/Users/marcusduggs/Golf_Caddie/shots/models.py`**
   - Updated `ShotAnalysis` model structure

4. **`/Users/marcusduggs/Golf_Caddie/templates/shots/analysis_detail.html`**
   - Displays both input and processed videos

---

**Created**: November 10, 2025
**Status**: ✅ Fully Functional
**Tested**: Yes - Marcus.mov (Kauai, HI)
