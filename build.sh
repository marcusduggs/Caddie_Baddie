#!/usr/bin/env bash
# Build script for Render.com

set -o errexit  # Exit on error

echo "🔧 Installing Python dependencies..."
pip install -r requirements.txt

echo "🗄️  Running database migrations..."
python manage.py migrate --noinput

echo "📦 Collecting static files..."
python manage.py collectstatic --noinput --clear

echo "✅ Build complete!"
