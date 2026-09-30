# accounts/urls.py
from django.urls import path
from . import views
from . import fanid_views

app_name = 'accounts'

urlpatterns = [
    # ===== OTP =====
    path('login/', views.phone_login, name='phone_login'),
    path('login/', views.phone_login, name='login'),  # ← alias برای سازگاری

    path('register/', views.phone_register, name='phone_register'),
    path('register/', views.phone_register, name='register'),  # ← alias

    path('verify/', views.otp_verify, name='otp_verify'),
    path('resend-otp/', views.resend_otp, name='resend_otp'),

    # ===== ورود با Fan ID (حساب اپ سپاهان) -- تا FANID_LOGIN_ENABLED روشن نشود ۴۰۴ =====
    path('fanid/login/', fanid_views.fanid_login, name='fanid_login'),
    path('fanid/callback/', fanid_views.fanid_callback, name='fanid_callback'),
    path('fanid/verify/', fanid_views.fanid_verify, name='fanid_verify'),
    path('fanid/resend/', fanid_views.fanid_resend, name='fanid_resend'),

    # ===== ورود با رمز (ادمین و VIP) =====
    path('login-password/', views.login_view, name='login_password'),

    path('logout/', views.logout_view, name='logout'),
    path('profile/', views.profile_view, name='profile'),
    path('edit-profile/', views.edit_profile_view, name='edit_profile'),
    path('choose-login/', views.phone_login, name='choose_login'),  # ← اضافه کنید
    # ← اضافه کنید

    # ===== پنل ادمین: مدیریت کاربران عادی =====
    path('admin/users/', views.admin_user_list, name='admin_user_list'),
    path('admin/users/<int:user_id>/', views.admin_user_detail, name='admin_user_detail'),

    # ===== پنل ادمین: تنظیمات اضطراری =====
    path('admin/emergency-settings/', views.admin_emergency_settings, name='admin_emergency_settings'),
    path('admin/site-settings/', views.admin_site_settings, name='admin_site_settings'),

]
