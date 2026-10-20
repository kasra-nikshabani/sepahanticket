from django.urls import path
from . import views

app_name = 'payments'

urlpatterns = [
    path('request/', views.payment_request, name='payment_request'),
    path('start/<str:track_id>/', views.payment_start, name='payment_start'),
    path('verify/', views.payment_verify, name='payment_verify'),
]