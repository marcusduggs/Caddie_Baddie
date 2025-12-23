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
    path('shots/<int:pk>/toggle-favorite/', views.toggle_favorite, name='toggle_favorite'),
    # Golf Course API proxy
    path('api/golf-course/', api.golf_course_search, name='api_golf_course'),
    path('api/course-suggestions/', api.course_suggestions, name='api_course_suggestions'),
    # Course / hole grouping pages
    path('courses/', views.courses_list, name='courses_list'),
    path('courses/<slug:course_slug>/', views.course_holes, name='course_holes'),
    path('courses/<slug:course_slug>/hole/<int:hole>/', views.hole_shots, name='hole_shots'),
]
