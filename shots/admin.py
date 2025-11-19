from django.contrib import admin
from .models import Shot

from .models import ShotAnalysis


@admin.register(Shot)
class ShotAdmin(admin.ModelAdmin):
    list_display = ('id', 'club', 'distance', 'accuracy', 'longitude', 'latitude', 'created_at')
    list_filter = ('club', 'created_at')
    search_fields = ('club', 'notes')


@admin.register(ShotAnalysis)
class ShotAnalysisAdmin(admin.ModelAdmin):
    list_display = ('id', 'input_video', 'club', 'distance', 'created_at')
    readonly_fields = ('created_at',)

