from django.urls import path
from . import views
from . import api

app_name = 'shots'

urlpatterns = [
    # Home page
    path('', views.home, name='home'),
    path('shots/', views.shot_list, name='shot_list'),
    path('shots/new/', views.create_shot, name='create_shot'),
    path('analyze/', views.analyze_upload, name='analyze_upload'),
    path('analyze/<int:pk>/', views.analysis_detail, name='analysis_detail'),
    path('upload-shot/', views.upload_shot, name='upload_shot'),
    path('shots/<int:pk>/delete/', views.delete_shot, name='delete_shot'),
    # Golf Course API proxy
    path('api/golf-course/', api.golf_course_search, name='api_golf_course'),
    path('api/course-suggestions/', api.course_suggestions, name='api_course_suggestions'),
]
