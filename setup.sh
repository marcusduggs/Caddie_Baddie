#!/bin/bash
# Setup script for Caddie_Baddie Django project

# Exit on error
set -e

# Create virtual environment if it doesn't exist
if [ ! -d "venv" ]; then
  python3 -m venv venv
fi

# Activate virtual environment
source venv/bin/activate

# Upgrade pip
pip install --upgrade pip

# Install required packages
pip install django django-allauth whitenoise django-widget-tweaks

# Install any additional requirements from requirements.txt if it exists
if [ -f requirements.txt ]; then
  pip install -r requirements.txt
fi

echo "Setup complete. Activate your environment with: source venv/bin/activate"