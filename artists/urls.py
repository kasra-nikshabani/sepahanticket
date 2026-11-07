from django.urls import path
from . import views
from . import collaboration_views as collaboration

app_name = 'artists'
urlpatterns = [
    path('', views.directory, name='directory'),
    path('my-profile/', views.edit_profile, name='edit'),
    path('following/', views.following, name='following'),
    path('opportunities/', collaboration.opportunity_list, name='opportunities'),
    path('opportunities/mine/', collaboration.my_opportunities, name='my_opportunities'),
    path('opportunities/new/', collaboration.opportunity_edit, name='opportunity_create'),
    path('opportunities/<uuid:opportunity_id>/', collaboration.opportunity_detail, name='opportunity_detail'),
    path('opportunities/<uuid:opportunity_id>/edit/', collaboration.opportunity_edit, name='opportunity_edit'),
    path('opportunities/<uuid:opportunity_id>/manage/', collaboration.opportunity_manage, name='opportunity_manage'),
    path('opportunities/<uuid:opportunity_id>/apply/', collaboration.opportunity_apply, name='opportunity_apply'),
    path('opportunities/<uuid:opportunity_id>/report/', collaboration.opportunity_report, name='opportunity_report'),
    path('applications/', collaboration.my_applications, name='my_applications'),
    path('applications/<uuid:application_id>/', collaboration.application_detail, name='application_detail'),
    path('applications/<uuid:application_id>/status/', collaboration.application_status, name='application_status'),
    path('credits/<int:credit_id>/confirm/', views.confirm_credit, name='confirm_credit'),
    path('<uuid:artist_id>/', views.detail, name='detail'),
    path('<uuid:artist_id>/follow/', views.follow_action, name='follow'),
]
