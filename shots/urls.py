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
    path('analysis/<int:pk>/overlay-status/', views.overlay_status, name='overlay_status'),
    path('upload-shot/', views.upload_shot, name='upload_shot'),
    path('shots/<int:pk>/delete/', views.delete_shot, name='delete_shot'),
    path('shots/<int:pk>/toggle-favorite/', views.toggle_favorite, name='toggle_favorite'),
    # Golf Course API proxy
    path('api/golf-course/', api.golf_course_search, name='api_golf_course'),
    # Backwards-compatible alias (some templates may reference this name)
    path('api/golf-course/search/', api.golf_course_search, name='golf_course_search'),
    path('api/course-suggestions/', api.course_suggestions, name='api_course_suggestions'),
    # Course / hole grouping pages
    path('courses/', views.courses_list, name='courses_list'),
    path('courses/add/', views.add_course, name='add_course'),
    path('courses/<int:pk>/', views.course_detail, name='course_detail'),
    path('courses/<int:pk>/refresh-tees/', views.refresh_course_tees, name='refresh_course_tees'),
    path('courses/<int:pk>/add-round/', views.add_round, name='add_round'),
    path('courses/<slug:course_slug>/', views.course_holes, name='course_holes'),
    path('courses/<slug:course_slug>/hole/<int:hole>/', views.hole_shots, name='hole_shots'),
    # Map view for shots on a hole (visualization)
    path('holes/<int:hole>/shots/map/', views.hole_shot_map, name='hole_shot_map'),
    # API: accept landing for the last shot on a hole (AJAX)
    path('api/holes/<int:hole_id>/last-shot/landing/', views.last_shot_landing, name='api_last_shot_landing'),
    path('api/holes/<int:hole_id>/save-pin/', views.save_hole_pin, name='api_save_hole_pin'),
    path('api/holes/<int:hole_id>/pin/', views.api_get_hole_pin, name='api_get_hole_pin'),
    # Rounds grouping
    path('rounds/', views.rounds_list, name='rounds_list'),
    path('rounds/<slug:course_slug>/', views.rounds_list, name='rounds_list_for_course'),
    path('round/<int:round_pk>/holes/', views.round_holes, name='round_holes'),
    path('round/<int:round_pk>/hole/<int:hole>/shots/', views.round_hole_shots, name='round_hole_shots'),
    path('round/<int:round_pk>/hole/<int:hole>/delete/', views.delete_round_hole, name='delete_round_hole'),
    path('round/<int:round_pk>/delete/', views.delete_round, name='delete_round'),
    path('courses/<int:pk>/delete/', views.delete_course, name='delete_course'),
]
