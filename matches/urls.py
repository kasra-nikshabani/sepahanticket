from django.urls import path
from django.views.generic import TemplateView
from . import views

app_name = 'matches'

urlpatterns = [
    # ===== صفحات عمومی =====
    path('', views.home, name='home'),
    path('match/<int:match_id>/', views.match_detail, name='match_detail'),
    path('match/<int:match_id>/select-row/', views.select_row, name='select_row'),
    path('match/<int:match_id>/block-map/', views.show_block_map, name='block_map'),
    path('get-seats-status/<int:match_id>/', views.get_seats_status, name='get_seats_status'),

    # ===== مدیریت قدیمی (قبل از بازنویسی) =====
    path('manage-rows/', views.manage_rows, name='manage_rows'),
    path('manage-seats/<int:row_id>/', views.manage_seats, name='manage_seats'),
    path('manage-blocks/', views.manage_blocks, name='manage_blocks'),

    # ===== مدیریت ادمین (سایت) =====
    path('admin-matches/', views.admin_match_list, name='admin_match_list'),
    path('admin-matches/<int:match_id>/', views.admin_match_detail, name='admin_match_detail'),

    # ===== آموزش =====
    path('tutorial/', TemplateView.as_view(template_name='pages/tutorial.html'), name='tutorial'),

    # ===== فرآیند خرید (انتخاب طبقه و بلوک) =====
    path('select-floor/<int:match_id>/', views.select_floor, name='select_floor'),
    path('select-block/<int:match_id>/', views.select_block, name='select_block'),

    # ===== مدیریت بلوک‌ها (فقط ادمین) =====
    path('admin/blocks/', views.admin_block_list, name='admin_block_list'),
    path('admin/blocks/edit/<int:block_id>/', views.admin_block_edit, name='admin_block_edit'),
    path('admin/blocks/edit/', views.admin_block_edit, name='admin_block_edit'),
    path('admin/blocks/delete/<int:block_id>/', views.admin_block_delete, name='admin_block_delete'),
    path('admin/blocks/toggle/<int:block_id>/', views.toggle_block_status, name='toggle_block_status'),
    path('admin/blocks/bulk-toggle-floor/<int:stadium_id>/<str:floor>/', views.admin_bulk_toggle_floor, name='admin_bulk_toggle_floor'),
    path('admin/blocks/manage-seats/<int:block_id>/', views.manage_block_seats, name='manage_block_seats'),

    # ===== مدیریت مسابقات (فقط ادمین) =====
    path('admin/match/create/', views.admin_match_create, name='admin_match_create'),
    path('admin/match/edit/<int:match_id>/', views.admin_match_edit, name='admin_match_edit'),
    path('admin/match/delete/<int:match_id>/', views.admin_match_delete, name='admin_match_delete'),
    path('admin/match/cancel/<int:match_id>/', views.admin_match_cancel, name='admin_match_cancel'),

    # ===== مدیریت ورزشگاه‌ها (فقط ادمین) =====
    path('admin/stadiums/', views.admin_stadium_list, name='admin_stadium_list'),
    path('admin/stadiums/create/', views.admin_stadium_create, name='admin_stadium_create'),
    path('admin/stadiums/edit/<int:stadium_id>/', views.admin_stadium_edit, name='admin_stadium_edit'),
    path('admin/stadiums/delete/<int:stadium_id>/', views.admin_stadium_delete, name='admin_stadium_delete'),
    path('admin/stadiums/configure/', views.admin_stadium_configure, name='admin_stadium_configure'),
    path('admin/stadiums/configure/<int:stadium_id>/', views.admin_stadium_configure, name='admin_stadium_configure'),

    # ===== مدیریت صندلی‌ها (فقط ادمین) =====
    path('admin/seats/toggle/<int:seat_id>/', views.toggle_seat_status, name='toggle_seat_status'),
    path('admin/blocks/manage-seats/', views.manage_block_seats, name='manage_block_seats'),
    path('admin/blocks/manage-seats/<int:block_id>/', views.manage_block_seats, name='manage_block_seats'),
    path('splash/', views.splash, name='splash'),
    path('api/set-splash-seen/', views.set_splash_seen, name='set_splash_seen'),

    # گزارش مالی
    path('financial-report/<int:match_id>/', views.match_financial_report, name='financial_report'),
    path('add-cost/<int:match_id>/', views.add_match_cost, name='add_match_cost'),
    path('add-revenue/<int:match_id>/', views.add_match_revenue, name='add_match_revenue'),
    path('delete-cost/<int:cost_id>/', views.delete_match_cost, name='delete_match_cost'),
    path('delete-revenue/<int:revenue_id>/', views.delete_match_revenue, name='delete_match_revenue'),
    path('financial-report-list/', views.match_financial_list, name='match_financial_list'),
    path('export-financial-report/<int:match_id>/', views.export_financial_report_pdf,
         name='export_financial_report_pdf'),
    path('edit-cost/<int:cost_id>/', views.edit_match_cost, name='edit_match_cost'),
    path('edit-revenue/<int:revenue_id>/', views.edit_match_revenue, name='edit_match_revenue'), ]
