from django.urls import path
from django.views.generic import TemplateView

from . import views

app_name = 'matches'

urlpatterns = [
    path('', views.home, name='home'),
    path('match/<int:match_id>/', views.match_detail, name='match_detail'),
    path('match/<int:match_id>/select-block/', views.select_block, name='select_block'),
    path('match/<int:match_id>/select-row/', views.select_row, name='select_row'),
    path('match/<int:match_id>/block-map/', views.show_block_map, name='block_map'),
    path('get-seats-status/<int:match_id>/', views.get_seats_status, name='get_seats_status'),
    path('manage-rows/', views.manage_rows, name='manage_rows'),
    path('manage-seats/<int:row_id>/', views.manage_seats, name='manage_seats'),
    path('manage-blocks/', views.manage_blocks, name='manage_blocks'),
    path('manage-block-seats/<int:block_id>/', views.manage_block_seats, name='manage_block_seats'),
    # ✅ فقط یک بار تعریف شود
    path('admin-matches/', views.admin_match_list, name='admin_match_list'),
    path('admin-matches/<int:match_id>/', views.admin_match_detail, name='admin_match_detail'),
    path('tutorial/', TemplateView.as_view(template_name='pages/tutorial.html'), name='tutorial'),
    path('select-floor/<int:match_id>/', views.select_floor, name='select_floor'),
    path('select-block/<int:match_id>/', views.select_block, name='select_block'),
    path('admin/blocks/', views.admin_block_list, name='admin_block_list'),
    path('admin/blocks/edit/<int:block_id>/', views.admin_block_edit, name='admin_block_edit'),
    path('admin/blocks/edit/', views.admin_block_edit, name='admin_block_edit'),
    path('admin/blocks/delete/<int:block_id>/', views.admin_block_delete, name='admin_block_delete'),
    path('admin/match/create/', views.admin_match_create, name='admin_match_create'),
    path('admin/match/edit/<int:match_id>/', views.admin_match_edit, name='admin_match_edit'),
    path('admin/match/delete/<int:match_id>/', views.admin_match_delete, name='admin_match_delete'),
    path('admin/stadiums/', views.admin_stadium_list, name='admin_stadium_list'),
    path('admin/stadiums/create/', views.admin_stadium_create, name='admin_stadium_create'),
    path('admin/stadiums/edit/<int:stadium_id>/', views.admin_stadium_edit, name='admin_stadium_edit'),
    path('admin/stadiums/delete/<int:stadium_id>/', views.admin_stadium_delete, name='admin_stadium_delete'),
    path('admin/stadiums/configure/', views.admin_stadium_configure, name='admin_stadium_configure'),  # ← جدید
    path('admin/stadiums/configure/<int:stadium_id>/', views.admin_stadium_configure, name='admin_stadium_configure'),

]
