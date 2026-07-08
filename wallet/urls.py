from django.urls import path
from . import views

app_name = 'wallet'

urlpatterns = [
    path('dashboard/', views.wallet_dashboard, name='dashboard'),
    path('charge/', views.wallet_charge, name='charge'),
]