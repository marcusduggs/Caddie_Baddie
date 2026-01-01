from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from shots import api as shots_api

urlpatterns = [
    path('admin/', admin.site.urls),
    path('accounts/', include('accounts.urls')),
    path('accounts/', include('django.contrib.auth.urls')),
    path('', include('shots.urls')),
    # Backwards-compatible global alias for templates that reverse 'golf_course_search' without namespace
    path('api/golf-course/search/', shots_api.golf_course_search, name='golf_course_search'),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
