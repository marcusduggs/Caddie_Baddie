# 🌍 Deploy Reel Caddie Daddy to Render.com

## Make Your App Accessible From Anywhere in the World!

This guide will help you deploy your Golf Caddie app to Render.com so anyone can access it from any phone or computer.

---

## 📋 Prerequisites

1. ✅ GitHub account
2. ✅ Render.com account (sign up at https://render.com - it's free!)
3. ✅ Your code committed to GitHub

---

## 🚀 Step-by-Step Deployment

### Step 1: Push Code to GitHub

```bash
cd /Users/marcusduggs/Golf_Caddie

# Add all files
git add .

# Commit changes
git commit -m "Prepare for Render.com deployment"

# Push to GitHub
git push origin v2
```

### Step 2: Sign Up for Render.com

1. Go to https://render.com
2. Click **"Get Started"**
3. Sign up with your GitHub account (easiest option)
4. Authorize Render to access your GitHub repos

### Step 3: Create a New Web Service

1. From Render Dashboard, click **"New +"** → **"Web Service"**

2. **Connect your repository:**
   - Search for: `Caddie_Baddie`
   - Click **"Connect"**

3. **Configure the service:**

   | Setting | Value |
   |---------|-------|
   | **Name** | `reel-caddie-daddy` (or any name you like) |
   | **Region** | Choose closest to you (e.g., Oregon USA) |
   | **Branch** | `v2` |
   | **Runtime** | `Python 3` |
   | **Build Command** | `./build.sh` |
   | **Start Command** | `gunicorn golf_caddie.wsgi:application --bind 0.0.0.0:$PORT` |
   | **Instance Type** | `Free` (perfect for testing!) |

4. Click **"Advanced"** and add **Environment Variables:**

   | Key | Value |
   |-----|-------|
   | `PYTHON_VERSION` | `3.8.18` |
   | `SECRET_KEY` | (generate random string - see below) |
   | `DEBUG` | `False` |
   | `ALLOWED_HOSTS` | `reel-caddie-daddy.onrender.com` |
   | `MAPBOX_TOKEN` | `pk.eyJ1IjoibGR1Z2dzIiwiYSI6ImNtZ3d2bzVybjBsNGkya3ByaGY5MXA1MGIifQ.OVODkq1EaazsvaXtyeFE4A` |

   **To generate a SECRET_KEY:**
   ```python
   python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
   ```

5. Click **"Create Web Service"**

### Step 4: Add a PostgreSQL Database (Free)

1. From Render Dashboard, click **"New +"** → **"PostgreSQL"**

2. **Configure:**
   | Setting | Value |
   |---------|-------|
   | **Name** | `reel-caddie-db` |
   | **Database** | `golf_caddie` |
   | **User** | `golf_caddie_user` |
   | **Region** | Same as your web service |
   | **Instance Type** | `Free` |

3. Click **"Create Database"**

4. **Connect database to web service:**
   - Go back to your web service settings
   - Click **"Environment"**
   - Add new variable:
     - Key: `DATABASE_URL`
     - Value: Click "Add from Database" → Select your database → Select "Internal Database URL"

5. Click **"Save Changes"**

### Step 5: Deploy!

Render will automatically:
1. ✅ Clone your code from GitHub
2. ✅ Install dependencies
3. ✅ Run migrations
4. ✅ Collect static files
5. ✅ Start your app

Watch the logs in real-time on the Render dashboard!

---

## 🎉 You're Live!

Your app will be accessible at:
**https://reel-caddie-daddy.onrender.com**

(Replace with your actual service name)

### Access from anywhere:
- 📱 **iPhone/Android**: Open the URL in Safari/Chrome
- 💻 **Computer**: Open the URL in any browser
- 🌍 **Share**: Send the URL to anyone!

---

## 🔧 Post-Deployment Setup

### Update ALLOWED_HOSTS

Once deployed, update the environment variable to your actual URL:

1. Go to your web service on Render
2. Click **"Environment"**
3. Update `ALLOWED_HOSTS` to: `reel-caddie-daddy.onrender.com`
4. Click **"Save Changes"**

### Create Superuser (Admin Account)

Access your app's shell on Render:

1. Go to your web service
2. Click **"Shell"** tab
3. Run:
   ```bash
   python manage.py createsuperuser
   ```
4. Follow prompts to create admin account

Now you can access admin at: `https://your-app.onrender.com/admin/`

---

## 📁 File Upload Limitations

⚠️ **Important**: Render's free tier has **ephemeral storage** - uploaded files are deleted when the service restarts.

### Solutions:

#### Option 1: Use Amazon S3 (Recommended)

Add to your environment variables:
```
AWS_ACCESS_KEY_ID=your_key
AWS_SECRET_ACCESS_KEY=your_secret
AWS_STORAGE_BUCKET_NAME=your_bucket_name
```

Then update Django settings to use S3 for media files.

#### Option 2: Use Cloudinary (Easier)

1. Sign up at https://cloudinary.com (free tier)
2. Install: Add `django-cloudinary-storage` to requirements.txt
3. Configure in settings.py

#### Option 3: Upgrade Render Plan

Render's paid plans ($7/month) include persistent disk storage.

---

## 🔄 Auto-Deploy on Git Push

Render automatically deploys when you push to GitHub!

```bash
# Make changes
git add .
git commit -m "Add new feature"
git push origin v2

# Render automatically deploys! 🚀
```

---

## 📊 Monitoring

### View Logs:
1. Go to your service on Render
2. Click **"Logs"** tab
3. See real-time logs of your app

### Check Status:
- Green = Healthy ✅
- Yellow = Deploying 🔄
- Red = Error ❌

---

## 💰 Pricing

### Free Tier Includes:
- ✅ 750 hours/month (enough for one always-on service)
- ✅ HTTPS included
- ✅ Auto-deploy from GitHub
- ✅ PostgreSQL database (90 days, then expires)
- ✅ Custom domain support

### Limitations:
- ⚠️ Spins down after 15 min of inactivity (30s startup time)
- ⚠️ No persistent storage for uploads
- ⚠️ 512 MB RAM

### Paid Plans:
- **Starter**: $7/month - No spin-down, persistent disk
- **Standard**: $25/month - More resources, better performance

---

## 🐛 Troubleshooting

### Build Failed

**Check the logs:**
1. Go to your service
2. Click **"Logs"**
3. Look for error messages

**Common issues:**
- Missing dependencies in requirements.txt
- Python version mismatch
- Environment variables not set

### App Won't Start

**Check:**
1. `DEBUG=False` is set
2. `ALLOWED_HOSTS` includes your Render URL
3. `SECRET_KEY` is set
4. Database is connected

### Static Files Not Loading

**Run manually:**
```bash
# In Render Shell
python manage.py collectstatic --noinput
```

### Database Connection Error

**Verify:**
1. DATABASE_URL environment variable is set
2. Database is in same region as web service
3. Internal Database URL is used (not external)

---

## 🎯 Next Steps

### Custom Domain

1. Buy domain (e.g., from Namecheap, Google Domains)
2. In Render: Settings → Custom Domain → Add your domain
3. Update DNS records as instructed
4. Wait for SSL certificate (automatic!)

### Performance Optimization

1. **Enable caching:**
   ```python
   # Add to settings.py
   CACHES = {
       'default': {
           'BACKEND': 'django.core.cache.backends.db.DatabaseCache',
           'LOCATION': 'my_cache_table',
       }
   }
   ```

2. **Optimize static files:**
   - Already using WhiteNoise ✅
   - Consider CDN for large files

3. **Database optimization:**
   - Add indexes to frequently queried fields
   - Use select_related() and prefetch_related()

### Security Enhancements

1. **HTTPS only:**
   ```python
   SECURE_SSL_REDIRECT = True
   SESSION_COOKIE_SECURE = True
   CSRF_COOKIE_SECURE = True
   ```

2. **Security headers:**
   ```python
   SECURE_HSTS_SECONDS = 31536000
   SECURE_HSTS_INCLUDE_SUBDOMAINS = True
   SECURE_HSTS_PRELOAD = True
   ```

---

## 📞 Support

- **Render Docs**: https://render.com/docs
- **Django Docs**: https://docs.djangoproject.com
- **Community**: https://community.render.com

---

## ✅ Deployment Checklist

- [ ] Code pushed to GitHub
- [ ] Render account created
- [ ] Web service created
- [ ] PostgreSQL database created
- [ ] Environment variables set
- [ ] Build successful
- [ ] App accessible via URL
- [ ] Admin account created
- [ ] Custom domain added (optional)
- [ ] File storage configured (S3/Cloudinary)

---

## 🎉 Congratulations!

Your Reel Caddie Daddy app is now live and accessible from anywhere in the world!

**Your URL**: https://reel-caddie-daddy.onrender.com

Share it with friends, use it from any device, anywhere! ⛳🏌️📱

---

**Need help?** The Render dashboard has excellent documentation and support!
