#!/bin/bash

# Script to make Golf Caddie accessible from anywhere using ngrok

echo "======================================================================="
echo "🌍  Reel Caddie Daddy - Public Access Setup"
echo "======================================================================="
echo ""

# Check if ngrok is installed
if ! command -v ngrok &> /dev/null; then
    echo "❌ ngrok not found. Installing..."
    brew install ngrok
    
    echo ""
    echo "✅ ngrok installed!"
    echo ""
    echo "📝 Next steps:"
    echo "   1. Sign up at: https://ngrok.com/signup"
    echo "   2. Get your auth token from: https://dashboard.ngrok.com/auth"
    echo "   3. Run: ngrok config add-authtoken YOUR_TOKEN"
    echo "   4. Run this script again"
    echo ""
    exit 1
fi

echo "✅ ngrok is installed"
echo ""

# Check if Django is running
if lsof -Pi :8000 -sTCP:LISTEN -t >/dev/null ; then
    echo "✅ Django server is running on port 8000"
else
    echo "⚠️  Django server not running. Starting it..."
    echo ""
    
    # Start Django in background
    cd /Users/marcusduggs/Golf_Caddie
    python start_mobile.py > django.log 2>&1 &
    DJANGO_PID=$!
    
    echo "   Waiting for Django to start..."
    sleep 5
    
    if lsof -Pi :8000 -sTCP:LISTEN -t >/dev/null ; then
        echo "✅ Django started successfully (PID: $DJANGO_PID)"
    else
        echo "❌ Failed to start Django. Check django.log"
        exit 1
    fi
fi

echo ""
echo "======================================================================="
echo "🚀 Creating public tunnel with ngrok..."
echo "======================================================================="
echo ""
echo "Your app will be accessible from ANYWHERE with the URL below:"
echo ""

# Start ngrok
ngrok http 8000 --log=stdout

# This line only runs if ngrok is stopped (Ctrl+C)
echo ""
echo "======================================================================="
echo "👋 Tunnel closed. Your app is now only accessible locally."
echo "======================================================================="
