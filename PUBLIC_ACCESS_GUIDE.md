# 🌍 Make Your App Accessible to ANYONE

## Quick Start (3 Steps)

### 1️⃣ Install ngrok

```bash
brew install ngrok/ngrok/ngrok
```

**Or download from:** https://ngrok.com/download

---

### 2️⃣ Sign Up & Connect (One Time Setup)

```bash
# Go to: https://dashboard.ngrok.com/signup
# Sign up (FREE)
# Get your token from: https://dashboard.ngrok.com/get-started/your-authtoken

# Connect your account:
ngrok config add-authtoken YOUR_TOKEN_HERE
```

---

### 3️⃣ Start & Share!

```bash
cd /Users/marcusduggs/Golf_Caddie
./start_public_ngrok.sh
```

**You'll get a URL like:**
```
https://abc123-def456.ngrok-free.app
```

**📱 SHARE THAT URL - Anyone can access your app!**

---

## 🎯 Manual Method (If You Prefer)

**Terminal 1 - Start Django:**
```bash
cd /Users/marcusduggs/Golf_Caddie
python3 manage.py runserver 0.0.0.0:8000
```

**Terminal 2 - Start ngrok:**
```bash
ngrok http 8000
```

Copy the **Forwarding** URL and share it!

---

## ✨ What People Can Do:

- 📱 **Upload golf videos** from their phone
- 🎥 **View processed videos** with GPS overlays
- 🗺️ **See Mapbox** location overlays
- ⛳ **Browse all shots** in the gallery
- 🌍 **Access from ANYWHERE** - no WiFi restrictions!

---

## 🔒 Security Note

- Free ngrok URLs are **temporary** (change when you restart)
- URLs are **random** and hard to guess
- Only people with the URL can access
- For production, consider **paid ngrok** ($10/month) for:
  - Custom domains
  - Password protection
  - Static URLs

---

## 💡 Alternative Options

### Option A: ngrok (Recommended)
- ✅ Easiest setup
- ✅ Works everywhere
- ✅ Free tier available
- ⚠️ URL changes on restart (free tier)

### Option B: Cloudflare Tunnel
```bash
brew install cloudflared
cloudflared tunnel --url http://localhost:8000
```
- ✅ Unlimited bandwidth
- ✅ Free
- ⚠️ URL changes each time

### Option C: Render.com (24/7 Hosting)
- ✅ Always online
- ✅ Permanent URL
- ✅ Free tier
- ⚠️ 10 min setup
- ⚠️ Cold starts on free tier

---

## 🚀 Quick Reference

```bash
# ONE COMMAND TO RULE THEM ALL:
cd /Users/marcusduggs/Golf_Caddie && ./start_public_ngrok.sh

# Or manual method:
# Terminal 1:
python3 manage.py runserver 0.0.0.0:8000

# Terminal 2:
ngrok http 8000
```

---

## 🎉 Success Checklist

- [ ] ngrok installed
- [ ] Account created & connected
- [ ] Django server running
- [ ] ngrok tunnel created
- [ ] URL shared with friends
- [ ] People can access your app! 🏌️

---

## 📞 Troubleshooting

**Problem:** "ngrok not found"
- **Solution:** Install with `brew install ngrok/ngrok/ngrok`

**Problem:** "Account required"
- **Solution:** Sign up at https://dashboard.ngrok.com/signup and add authtoken

**Problem:** "Connection refused"
- **Solution:** Make sure Django is running first on port 8000

**Problem:** URL not working
- **Solution:** Check that both Django AND ngrok are running simultaneously

---

## 🎓 How It Works

```
User's Phone/Computer
       ↓
https://abc123.ngrok-free.app (Public Internet)
       ↓
ngrok tunnel
       ↓
Your Mac (localhost:8000)
       ↓
Django App (Golf Caddie)
```

ngrok creates a **secure tunnel** from the internet to your local computer!

---

**Need help? Just run the script and follow the instructions!**

```bash
./start_public_ngrok.sh
```
