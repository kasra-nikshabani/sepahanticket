from django.urls import path
from . import views
app_name='studios'
urlpatterns=[path('',views.catalogue,name='catalogue'),path('mine/',views.my_studios,name='my_studios'),path('bookings/',views.my_bookings,name='my_bookings'),
    path('new/',views.edit,name='create'),path('<uuid:studio_id>/',views.detail,name='detail'),path('<uuid:studio_id>/edit/',views.edit,name='edit'),
    path('<uuid:studio_id>/manage/',views.manage,name='manage'),path('<uuid:studio_id>/submit/',views.submit,name='submit'),
    path('<uuid:studio_id>/checkout/',views.checkout,name='checkout'),path('<uuid:studio_id>/slots/<int:slot_id>/',views.slot_edit,name='slot_edit'),
    path('<uuid:studio_id>/photos/<int:photo_id>/hide/',views.hide_photo,name='hide_photo')]
