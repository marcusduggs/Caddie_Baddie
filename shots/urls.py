from django.urls import path
from . import views

app_name = 'shots'

urlpatterns = [
    # Home page
    path('', views.home, name='home'),
    path('shots/', views.shot_list, name='shot_list'),
    path('shot/<int:pk>/delete/', views.delete_shot, name='delete_shot'),
    path('shots/new/', views.create_shot, name='create_shot'),
    path('analyze/', views.analyze_upload, name='analyze_upload'),
    path('analyze/<int:pk>/', views.analysis_detail, name='analysis_detail'),
]
