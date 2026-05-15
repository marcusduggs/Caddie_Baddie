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
    # Pose-wireframe overlay output (kept separate so both variants are available)
    overlayed_video = models.FileField(upload_to='overlayed/', null=True, blank=True)
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
    # Whether the user requested a pose-wireframe overlay for this analysis
    overlay_requested = models.BooleanField(default=False)
    # Whether the user opted in to include the course map overlay (API)
    include_map = models.BooleanField(default=False)
    # Whether the user opted in to burn course/hole text into the processed video
    include_course_text = models.BooleanField(default=False)
    OVERLAY_STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('overlaying', 'Overlaying'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
    ]
    overlay_status = models.CharField(max_length=20, choices=OVERLAY_STATUS_CHOICES, default='pending')
    overlay_error_message = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    # Assigned stroke order based on video capture time (1 = oldest)
    stroke_number = models.IntegerField(blank=True, null=True)
    # Server-side ffprobe-extracted creation time (UTC naive)
    probe_creation_time = models.DateTimeField(blank=True, null=True)
    # Client-side timestamp captured when the user selected the file in the browser
    client_added_time = models.DateTimeField(blank=True, null=True)
    # Optional reference to a playing session/round so multiple uploads on different days can be grouped
    round = models.ForeignKey('ShotRound', on_delete=models.SET_NULL, null=True, blank=True, related_name='analyses')
    # Mark this shot as a favorite (shared to the public/favorites page)
    is_favorite = models.BooleanField(default=False)
    # Quick Upload mode: bypasses Course → Round → Hole workflow
    is_quick_upload = models.BooleanField(default=False)
    # Public demo — viewable without login (set via Django admin)
    is_public = models.BooleanField(default=False)

    # AI Swing Coach fields — populated asynchronously during background processing
    ai_main_fault = models.TextField(blank=True, null=True)
    ai_strength = models.TextField(blank=True, null=True)
    ai_drill = models.TextField(blank=True, null=True)
    ai_swing_thought = models.TextField(blank=True, null=True)
    # Raw JSON snapshot of extracted swing metrics (stored for debugging / re-analysis)
    ai_metrics_json = models.TextField(blank=True, null=True)

    # Swing scores (0-100) computed by scoring_engine
    ai_overall_score = models.IntegerField(blank=True, null=True)
    ai_tempo_score = models.IntegerField(blank=True, null=True)
    ai_balance_score = models.IntegerField(blank=True, null=True)
    ai_rotation_score = models.IntegerField(blank=True, null=True)
    ai_posture_score = models.IntegerField(blank=True, null=True)
    ai_sequencing_score = models.IntegerField(blank=True, null=True)
    ai_consistency_score = models.IntegerField(blank=True, null=True)

    # Shot shape estimate from biomechanical indicators
    ai_shot_shape = models.CharField(max_length=20, blank=True, null=True)

    # Tour pro comparison narrative
    ai_pro_comparison = models.TextField(blank=True, null=True)

    # Cross-session trend summary from swing memory
    ai_trend_summary = models.TextField(blank=True, null=True)

    # JSON dict mapping position -> MEDIA_ROOT-relative path for swing snapshots
    ai_snapshots_json = models.TextField(blank=True, null=True)

    def __str__(self):
        return f"Analysis {self.id} — {self.input_video.name if self.input_video else 'no-video'}"


class CourseMetadata(models.Model):
    """Cache for golf course metadata fetched from external API."""
    course_slug = models.SlugField(max_length=255, unique=True)
    name = models.CharField(max_length=255)
    address = models.TextField(blank=True, null=True)
    hole_count = models.IntegerField(blank=True, null=True)
    par_total = models.IntegerField(blank=True, null=True)
    fetched_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.name} ({self.course_slug})"


class Course(models.Model):
    """User-owned course record for simple course management in UI."""
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    name = models.CharField(max_length=255)
    slug = models.SlugField(max_length=255, unique=True)
    # JSON-encoded list of tee names returned from external golf course API.
    # Stored as text to avoid DB-specific JSON field requirements.
    tee_names_json = models.TextField(blank=True, null=True, help_text='JSON list of tee names from API')
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


class ShotRound(models.Model):
    """Represents a played round/session so shots can be grouped by date/name."""
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    name = models.CharField(max_length=200, blank=True, null=True)
    course_name = models.CharField(max_length=200, blank=True, null=True)
    hole_number = models.IntegerField(blank=True, null=True)
    played_at = models.DateTimeField(blank=True, null=True)
    # Tee selected for this round (e.g., Blue, White). Used to prefill uploads attached to this round.
    selected_tee = models.CharField(max_length=64, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        label = self.name or (self.course_name or 'Round')
        if self.played_at:
            return f"{label} — {self.played_at.date()}"
        return label


class ShotDistance(models.Model):
    """Stores GPS-derived shot locations and computed distances."""
    shot = models.ForeignKey('ShotAnalysis', on_delete=models.CASCADE, related_name='distances')
    hole_number = models.IntegerField(blank=True, null=True)
    origin_lat = models.FloatField(null=True, blank=True)
    origin_lng = models.FloatField(null=True, blank=True)
    landing_lat = models.FloatField(null=True, blank=True)
    landing_lng = models.FloatField(null=True, blank=True)
    previous_shot = models.ForeignKey('self', on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"ShotDistance {self.pk} for shot {self.shot_id}"


class SwingTendency(models.Model):
    """Persistent record of a recurring swing fault or pattern for a user.

    Updated each time a new swing analysis detects the same tendency, so the
    AI coach can reference multi-session trends and celebrate improvements.
    """
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="swing_tendencies",
    )
    tendency_type = models.CharField(max_length=50)
    label = models.CharField(max_length=100)
    occurrence_count = models.IntegerField(default=1)
    last_seen_analysis = models.ForeignKey(
        "ShotAnalysis",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    first_seen_at = models.DateTimeField(auto_now_add=True)
    last_seen_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [["user", "tendency_type"]]

    def __str__(self):
        return f"{self.user_id} — {self.tendency_type} ×{self.occurrence_count}"


class HolePin(models.Model):
    """Additive model to persist a saved hole pin location.

    This keeps hole-level pin storage additive and separate from ShotDistance.
    We store the creating user so pins are scoped per-user and the latest
    pin for a hole can be used to lock the UI.
    """
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    hole_number = models.IntegerField()
    lat = models.FloatField()
    lng = models.FloatField()
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"HolePin hole={self.hole_number} user={self.user_id} ({self.lat},{self.lng})"

