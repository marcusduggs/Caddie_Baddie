from django.db import models


class Shot(models.Model):
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
    club = models.CharField(max_length=50)
    distance = models.FloatField()
    input_video = models.FileField(upload_to='input/')
    processed_video = models.FileField(upload_to='output/', null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Analysis {self.id} — {self.input_video.name if self.input_video else 'no-video'}"

