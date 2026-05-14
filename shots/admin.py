from django.contrib import admin, messages
from .models import Shot

from .models import ShotAnalysis


@admin.register(Shot)
class ShotAdmin(admin.ModelAdmin):
    list_display = ('id', 'club', 'distance', 'accuracy', 'longitude', 'latitude', 'created_at')
    list_filter = ('club', 'created_at')
    search_fields = ('club', 'notes')


def requeue_for_processing(modeladmin, request, queryset):
    from django_q.tasks import async_task
    count = 0
    for sa in queryset:
        sa.status = 'pending'
        sa.error_message = ''
        sa.overlay_status = ''
        sa.overlay_error_message = ''
        sa.save(update_fields=['status', 'error_message', 'overlay_status', 'overlay_error_message', 'updated_at'])
        async_task('shots.tasks.process_video_background', sa.pk)
        count += 1
    modeladmin.message_user(request, f'Requeued {count} analysis/analyses for processing.', messages.SUCCESS)

requeue_for_processing.short_description = 'Requeue selected analyses for processing'


@admin.register(ShotAnalysis)
class ShotAnalysisAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'status', 'overlay_status', 'club', 'distance', 'created_at')
    list_filter = ('status', 'overlay_status', 'club')
    search_fields = ('id', 'user__username')
    readonly_fields = ('created_at',)
    actions = [requeue_for_processing]

