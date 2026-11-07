# accounts/urls.py
from django.urls import path
from . import views
from . import fanid_views
from . import submission_views
from . import program_views
from . import program_pricing
from . import support_views
from . import notification_views
from . import artcard_views
from . import checkin_views

app_name = 'accounts'

urlpatterns = [
    path('art-card/', artcard_views.art_card, name='art_card'),
    path('notifications/', notification_views.inbox, name='notifications'),
    path('notifications/read-all/', notification_views.mark_all_read, name='notifications_read_all'),
    path('notifications/<int:notification_id>/open/', notification_views.open_notification, name='notification_open'),
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
    path('support/', support_views.support_list, name='support_list'),
    path('support/new/', support_views.support_create, name='support_create'),
    path('support/<int:ticket_id>/', support_views.support_detail, name='support_detail'),
    path('profile/', views.profile_view, name='profile'),
    path('edit-profile/', views.edit_profile_view, name='edit_profile'),
    path('programs/', program_views.program_list, name='program_list'),
    path('programs/<uuid:submission_id>/', program_views.program_detail, name='program_detail'),
    path('programs/<uuid:submission_id>/pricing/', program_pricing.program_pricing, name='program_pricing'),
    path('programs/<uuid:submission_id>/sessions/<int:session_id>/pricing/', program_pricing.program_pricing, name='program_session_pricing'),
    path('programs/<uuid:submission_id>/sessions/<int:session_id>/', program_views.program_detail, name='program_session'),
    path('programs/<uuid:submission_id>/sessions/<int:session_id>/check-in/', checkin_views.program_checkin, name='program_checkin'),
    path('programs/<uuid:submission_id>/sessions/<int:session_id>/check-in/verify/', checkin_views.program_checkin_action, name='program_checkin_action'),
    path('create-event/', views.event_submission_start, name='event_submission_start'),
    path('schedule-options/', submission_views.schedule_options, name='schedule_options'),
    path('venue-presets/<int:venue_id>/', submission_views.venue_preset, name='venue_preset'),
    path('create-event/<uuid:submission_id>/<int:step>/', submission_views.wizard, name='event_submission_step'),
    path('create-event/<uuid:submission_id>/asset/<str:kind>/', submission_views.asset, name='event_submission_asset'),
    path('create-event/<uuid:submission_id>/photo/<int:photo_id>/', submission_views.asset, {'kind': 'photo'}, name='event_submission_photo'),
    path('choose-login/', views.phone_login, name='choose_login'),  # ← اضافه کنید
    # ← اضافه کنید

    # ===== پنل ادمین: مدیریت کاربران عادی =====
    path('admin/users/', views.admin_user_list, name='admin_user_list'),
    path('admin/users/<int:user_id>/', views.admin_user_detail, name='admin_user_detail'),

    # ===== پنل ادمین: تنظیمات اضطراری =====
    path('admin/emergency-settings/', views.admin_emergency_settings, name='admin_emergency_settings'),
    path('admin/site-settings/', views.admin_site_settings, name='admin_site_settings'),

]
