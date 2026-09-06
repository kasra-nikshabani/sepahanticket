from django.urls import path
from . import views

app_name = 'wallet'

urlpatterns = [
    path('dashboard/', views.wallet_dashboard, name='dashboard'),
    path('charge/', views.wallet_charge, name='charge'),
    path('withdraw/', views.wallet_withdraw, name='withdraw'),

    # ===== پنل مدیریت =====
    path('admin/withdrawals/', views.admin_withdrawal_list, name='admin_withdrawal_list'),
    path('admin/withdrawals/<int:request_id>/action/', views.admin_withdrawal_action,
         name='admin_withdrawal_action'),
]
