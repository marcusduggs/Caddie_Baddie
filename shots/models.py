from django.db import models


from django.conf import settings

class Shot(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    club = models.CharField(max_length=64, blank=True, default='Unknown')
    distance = models.FloatField(help_text='Distance in yards')
    accuracy = models.FloatField(help_text='Accuracy score (0-100)')
    longitude = models.FloatField(null=True, blank=True)
    latitude = models.FloatField(null=True, blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Shot {self.id} — {self.distance}yd ({self.club})"


class ShotAnalysis(models.Model):
    """Stores results from analyzing an uploaded swing video."""
    STATUS_CHOICES = [
        ('uploading', 'Uploading'),
        ('processing', 'Processing'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
    ]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    club = models.CharField(max_length=50)
    distance = models.FloatField()
    input_video = models.FileField(upload_to='input/')
    processed_video = models.FileField(upload_to='output/', null=True, blank=True)
    # Allow null for safety when external scripts create records without setting status
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='uploading', null=True, blank=True)
    error_message = models.TextField(blank=True, null=True)
    # Store optional selected golf course and hole info
    course_name = models.CharField(max_length=200, blank=True, null=True)
    hole_number = models.IntegerField(blank=True, null=True)
    hole_yardage = models.IntegerField(blank=True, null=True)
    # Optional: par for the hole (persisted so overlays and reprocesses can access it)
    hole_par = models.IntegerField(blank=True, null=True)
    # Optional thumbnail image extracted from the uploaded video (single-frame preview)
    thumbnail = models.FileField(upload_to='thumbnails/', blank=True, null=True)
    # Optional: user-selected tee (e.g. 'Blue', 'White', 'Gold') and the tee actually used
    selected_tee = models.CharField(max_length=64, blank=True, null=True)
    used_tee = models.CharField(max_length=128, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Analysis {self.id} — {self.input_video.name if self.input_video else 'no-video'}"

