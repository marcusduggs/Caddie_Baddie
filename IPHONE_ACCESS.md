# 📱 iPhone Access - Quick Reference

## 🚀 How to Start Server for iPhone Access

Run this command on your Mac:

```bash
python start_mobile.py
```

Or manually:

```bash
python manage.py runserver 0.0.0.0:8000
```

## 📍 Find Your Local Network URL

The server will display something like:

```
📱 Access from your iPhone/iPad:
   ➜  http://192.168.1.100:8000/
```

**Open this URL in Safari on your iPhone!**

## 🔧 Manual IP Check

If you need to find your Mac's IP manually:

### macOS - Terminal
```bash
ifconfig | grep "inet " | grep -v 127.0.0.1
```

### macOS - GUI
1. Open **System Settings**
2. Go to **Network**
3. Look for **IP Address** (should be something like `192.168.x.x`)

## ✅ Checklist

Before accessing from iPhone:

- [ ] Server is running on Mac (`python start_mobile.py`)
- [ ] iPhone is on the **same Wi-Fi network** as Mac
- [ ] Firewall on Mac allows incoming connections
- [ ] Not using VPN on either device
- [ ] Using Safari browser on iPhone (recommended)

## 🎥 iPhone Video Upload

1. Tap the **📹 Upload Swing Video** button
2. When prompted, choose:
   - **Photo Library** - Select existing video from camera roll
   - **Take Video** - Record a new video
3. Select your club and enter distance
4. Tap **🚀 Analyze Shot**
5. Wait for processing (usually 10-30 seconds)
6. View both original and GPS-mapped videos!

## 🌐 HTTPS Access (Optional)

For secure access or outside your home network:

### Using ngrok (easiest)
```bash
# Install
brew install ngrok

# Start Django
python manage.py runserver

# In another terminal
ngrok http 8000
```

Copy the `https://` URL and use it on your iPhone anywhere!

### Using Cloudflare Tunnel
```bash
# Install
brew install cloudflare/cloudflare/cloudflared

# Start Django
python manage.py runserver

# Create tunnel
cloudflared tunnel --url http://localhost:8000
```

## 🐛 Troubleshooting

### "Can't reach server" on iPhone

**Check #1: Same Wi-Fi?**
- iPhone: Settings > Wi-Fi > Check network name
- Mac: Click Wi-Fi icon in menu bar

**Check #2: IP Address correct?**
- Run `python start_mobile.py` again to see current IP
- IP might change if you reconnect to Wi-Fi

**Check #3: Firewall?**
- Mac: System Settings > Network > Firewall
- Allow Python or Django through firewall

**Check #4: Port 8000 in use?**
Try a different port:
```bash
python manage.py runserver 0.0.0.0:8001
```
Then use `http://YOUR-IP:8001`

### Videos won't play on iPhone

- Make sure you're using **Safari** browser
- Try tapping the video to start playback
- Check if video format is supported (MOV and MP4 work best)

### Upload fails on iPhone

- Check internet connection
- File might be too large (try shorter video)
- Make sure you filled in Club and Distance fields

## 💡 Tips

- **Bookmark the URL** on your iPhone for quick access
- **Add to Home Screen** for app-like experience:
  1. Tap Share button in Safari
  2. Select "Add to Home Screen"
  3. Name it "Golf Caddie"
- **Best results**: Record videos in landscape mode
- **GPS works best**: When location services are enabled for Camera app

## 📞 Quick Help

Common URLs (replace `192.168.1.100` with your actual IP):

- **Home**: `http://192.168.1.100:8000/`
- **Upload**: `http://192.168.1.100:8000/analyze/`
- **All Shots**: `http://192.168.1.100:8000/shots/`

---

**Happy golfing! ⛳🏌️📱**
