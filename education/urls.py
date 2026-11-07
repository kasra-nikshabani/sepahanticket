from django.urls import path
from . import playback, views

app_name = 'education'
urlpatterns = [
    path('', views.catalogue, name='catalogue'),
    path('my-learning/', views.my_learning, name='my_learning'),
    path('teaching/', views.my_teaching, name='my_teaching'),
    path('teaching/new/', views.course_edit, name='create'),
    path('teaching/<uuid:course_id>/', views.manage, name='manage'),
    path('teaching/<uuid:course_id>/edit/', views.course_edit, name='edit'),
    path('teaching/<uuid:course_id>/lessons/new/', views.lesson_edit, name='lesson_create'),
    path('teaching/<uuid:course_id>/lessons/<uuid:lesson_id>/', views.lesson_edit, name='lesson_edit'),
    path('lessons/<uuid:lesson_id>/', views.watch, name='watch'),
    path('lessons/<uuid:lesson_id>/authorize/', playback.authorize, name='authorize'),
    path('lessons/<uuid:lesson_id>/progress/', views.progress, name='progress'),
    path('lessons/<uuid:lesson_id>/retry/', views.retry_video, name='retry'),
    path('stream/<uuid:lesson_id>/<uuid:revision>/<str:asset>', playback.stream, name='stream'),
    path('<uuid:course_id>/', views.detail, name='detail'),
    path('<uuid:course_id>/checkout/', views.checkout, name='checkout'),
]
