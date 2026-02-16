Production deployment notes for Caddie_Baddie

This file documents minimal steps and settings to run the Django app in production on an Ubuntu EC2 instance. It's intentionally conservative and uses environment variables for secrets.

1) Environment variables (recommended)
- DJANGO_SECRET_KEY: strong secret key
- DJANGO_DEBUG: set to '0' or 'False'
- ALLOWED_HOSTS: comma-separated hosts (example.com,ec2-1-2-3-4.compute-1.amazonaws.com)
- DATABASE_URL: (optional) postgres://... If not set, SQLite will be used (not recommended for prod)
- MAPBOX_TOKEN: your Mapbox token
- USE_S3: set to '1' to enable S3 storage (requires django-storages and boto3)

2) Install system packages (example on Ubuntu)
- sudo apt update && sudo apt install -y python3-venv python3-pip nginx git ffmpeg

3) Create a virtualenv and install python deps
- python3 -m venv .venv
- source .venv/bin/activate
- pip install -r requirements.txt

4) Static files
- Ensure STATIC_ROOT is writable by the deploy user (default: ./staticfiles)
- Run: python manage.py collectstatic --noinput
- The project is configured to use WhiteNoise by default for static serving. For
  heavier traffic, serve static files from S3 or directly from nginx.

5) Database migrations
- python manage.py migrate

6) Run with Gunicorn (example systemd service)
- gunicorn golf_caddie.wsgi:application --bind 0.0.0.0:8000 --workers 3

Example systemd unit (/etc/systemd/system/gunicorn.service):

[Unit]
Description=gunicorn daemon for Caddie_Baddie
After=network.target

[Service]
User=www-data
Group=www-data
WorkingDirectory=/home/ubuntu/Caddie_Baddie
ExecStart=/home/ubuntu/Caddie_Baddie/.venv/bin/gunicorn \
  --access-logfile - \
  --workers 3 \
  --bind unix:/run/gunicorn.sock \
  golf_caddie.wsgi:application

[Install]
WantedBy=multi-user.target

7) Nginx reverse proxy snippet (example)

server {
    listen 80;
    server_name example.com;

    location = /favicon.ico { access_log off; log_not_found off; }
    location /static/ {
        root /home/ubuntu/Caddie_Baddie;
    }

    location / {
        include proxy_params;
        proxy_pass http://unix:/run/gunicorn.sock;
    }
}

8) Security
- Use HTTPS (Let's Encrypt) and set SECURE_SSL_REDIRECT=1
- Set SESSION_COOKIE_SECURE=1 and CSRF_COOKIE_SECURE=1
- Keep secrets out of the repository and set them as environment variables

9) Optional: S3 media
- If USE_S3=1, install django-storages[boto3] and configure STORAGES with S3Boto3Storage
- Use the provided IAM policy template in scripts/aws/iam_policy_template.json

10) Troubleshooting
- Check journalctl -u gunicorn for Gunicorn logs
- Check nginx error/access logs in /var/log/nginx/

That's it — minimal deploy notes. Adjust to your infra and security needs.
