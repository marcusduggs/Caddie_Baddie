#!/bin/bash

echo "========================================================"
echo "🏌️  Reel Caddie Daddy - Public Access Setup"
echo "========================================================"
echo ""

# Check if ngrok is installed
if ! command -v ngrok &> /dev/null; then
    echo "❌ ngrok is not installed!"
    echo ""
    echo "📥 Install ngrok:"
    echo "   brew install ngrok/ngrok/ngrok"
    echo ""
    echo "🔑 Then get your authtoken:"
    echo "   1. Sign up: https://dashboard.ngrok.com/signup"
    echo "   2. Get token: https://dashboard.ngrok.com/get-started/your-authtoken"
    echo "   3. Run: ngrok config add-authtoken YOUR_TOKEN"
    echo ""
    exit 1
fi

echo "✅ ngrok is installed!"
echo ""
echo "🚀 Starting Django server..."
echo ""

# Start Django server in background
python3 manage.py runserver 0.0.0.0:8000 &
DJANGO_PID=$!

# Wait for Django to start
sleep 3

echo ""
echo "✅ Django is running on port 8000"
echo ""
echo "🌍 Creating public URL with ngrok..."
echo ""
echo "========================================================"
echo "📱 SHARE THIS URL WITH ANYONE:"
echo "========================================================"
echo ""

# Start ngrok (this will keep running)
ngrok http 8000

# Cleanup when ngrok stops
kill $DJANGO_PID 2>/dev/null
echo ""
echo "👋 Servers stopped!"
