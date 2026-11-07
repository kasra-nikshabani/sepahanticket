from django.urls import path
from . import management_views as views
from . import support_views
from artists import panel_views as artist_management
from artists import collaboration_panel
from education import panel as education_panel
from studios import panel as studio_panel

app_name = 'management'
urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    path('studios/', studio_panel.studios, name='studios'),
    path('studios/<uuid:studio_id>/', studio_panel.review, name='studio_detail'),
    path('art-cards/', views.art_card_requests, name='artcards'),
    path('education/', education_panel.courses, name='education'),
    path('education/<uuid:course_id>/', education_panel.course_review, name='education_detail'),
    path('artists/', artist_management.artists, name='artists'),
    path('opportunities/', collaboration_panel.opportunities, name='opportunities'),
    path('opportunities/<uuid:opportunity_id>/', collaboration_panel.opportunity_review, name='opportunity_detail'),
    path('artists/<uuid:artist_id>/', artist_management.artist_detail, name='artist_detail'),
    path('artist-credits/<int:credit_id>/remove/', artist_management.remove_credit, name='artist_credit_remove'),
    path('support/', support_views.management_list, name='support'),
    path('support/<int:ticket_id>/', support_views.management_detail, name='support_detail'),
    path('banners/', views.banners, name='banners'),
    path('banners/import-defaults/', views.banner_import_defaults, name='banner_import_defaults'),
    path('banners/new/', views.banner_edit, name='banner_create'),
    path('banners/<int:banner_id>/edit/', views.banner_edit, name='banner_edit'),
    path('banners/<int:banner_id>/status/', views.banner_toggle, name='banner_toggle'),
    path('events/', views.events, name='events'),
    path('events/new/', views.event_edit, name='event_create'),
    path('events/<int:event_id>/edit/', views.event_edit, name='event_edit'),
    path('events/<int:event_id>/report/', views.event_report, name='event_report'),
    path('sessions/', views.sessions, name='sessions'),
    path('sessions/new/', views.session_edit, name='session_create'),
    path('sessions/<int:session_id>/edit/', views.session_edit, name='session_edit'),
    path('sessions/<int:session_id>/sales/', views.session_sales, name='session_sales'),
    path('sessions/<int:session_id>/pricing/', views.session_pricing, name='session_pricing'),
    path('sessions/<int:session_id>/export/', views.sales_export, name='session_export'),
    path('requests/', views.requests_list, name='requests'),
    path('requests/<uuid:submission_id>/', views.request_detail, name='request_detail'),
    path('venues/', views.venues, name='venues'),
    path('venues/new/', views.venue_edit, name='venue_create'),
    path('venues/<int:venue_id>/edit/', views.venue_edit, name='venue_edit'),
    path('users/', views.users, name='users'),
    path('users/<int:user_id>/', views.user_detail, name='user_detail'),
    path('sales/', views.sales, name='sales'),
    path('sales/export/', views.sales_export, name='sales_export'),
    path('activity/', views.activity, name='activity'),
    path('settings/', views.site_settings, name='settings'),
]
