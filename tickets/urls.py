# tickets/urls.py
from django.urls import path
from . import views
from . import api

app_name = 'tickets'

urlpatterns = [
    path('admin-reports/', views.sales_report, name='admin_reports'),  # ← اضافه کنید

    path('select/<int:match_id>/', views.select_seats, name='select_seats'),
    path('ticket-info/<int:match_id>/', views.ticket_info, name='ticket_info'),
    path('my-tickets/', views.user_tickets, name='user_tickets'),
    path('download/<int:ticket_id>/', views.download_ticket_pdf, name='download_ticket_pdf'),
    path('shared/<uuid:token>/', views.shared_ticket_pdf, name='shared_ticket_pdf'),
    path('pdf-status/', views.tickets_pdf_status, name='tickets_pdf_status'),
    path('vip-tickets/', views.vip_tickets, name='vip_tickets'),
    path('vip-issue-manual/<int:match_id>/', views.vip_issue_manual, name='vip_issue_manual'),
    path('vip-issue-excel/<int:match_id>/', views.vip_issue_excel, name='vip_issue_excel'),
    path('sales-report/', views.sales_report, name='sales_report'),
    path('bulk-issue/', views.bulk_issue_tickets, name='bulk_issue'),
    path('admin/issue-ticket/', views.admin_issue_ticket, name='admin_issue_ticket'),
    path('manage-vip-users/', views.manage_vip_users, name='manage_vip_users'),
    path('manage-user-tickets/<int:user_id>/', views.manage_user_tickets, name='manage_user_tickets'),
    path('row-occupancy/', views.row_occupancy_report, name='row_occupancy'),
    path('bulk-download/', views.bulk_download_tickets, name='bulk_download'),
    path('bulk-download-received/', views.bulk_download_received_tickets, name='bulk_download_received'),
    path('reserve/<int:match_id>/', views.reserve_seats, name='reserve_seats'),
    path('cancel/<int:match_id>/', views.cancel_reservation, name='cancel_reservation'),
    path('release-reservation/', views.release_reservation, name='release_reservation'),
    path('api/gate-login/', api.gate_login, name='gate_login'),
    path('api/scan-ticket/', api.scan_ticket, name='scan_ticket'),
    path('check-discount/', views.check_discount, name='check_discount'),
    path('check-special-code/', views.check_special_code, name='check_special_code'),
    path('vip-dashboard/', views.vip_dashboard, name='vip_dashboard'),
    path('vip-issued-tickets/', views.vip_issued_tickets, name='vip_issued_tickets'),
    path('vip-special-codes/', views.vip_special_codes, name='vip_special_codes'),
    path('vip-special-codes/download/', views.vip_special_codes_download, name='vip_special_codes_download'),
    path('vip-special-codes/<int:code_id>/download/', views.vip_special_code_download_single, name='vip_special_code_download_single'),
    path('admin/vip-quota/', views.admin_vip_quota_list, name='admin_vip_quota_list'),
    path('admin/vip-quota/create/', views.admin_vip_quota_create, name='admin_vip_quota_create'),
    path('admin/vip-quota/edit/<int:quota_id>/', views.admin_vip_quota_edit, name='admin_vip_quota_edit'),
    path('admin/vip-quota/delete/<int:quota_id>/', views.admin_vip_quota_delete, name='admin_vip_quota_delete'),
    path('admin/discounts/', views.admin_discount_list, name='admin_discount_list'),
    path('admin/discounts/create/', views.admin_discount_create, name='admin_discount_create'),
    path('admin/discounts/edit/<int:discount_id>/', views.admin_discount_edit, name='admin_discount_edit'),
    path('admin/discounts/delete/<int:discount_id>/', views.admin_discount_delete, name='admin_discount_delete'),
    path('admin/discounts/toggle/<int:discount_id>/', views.admin_discount_toggle, name='admin_discount_toggle'),
    path('admin/special-codes/toggle/<int:code_id>/', views.admin_special_code_toggle, name='admin_special_code_toggle'),
    path('admin/special-codes/delete/<int:code_id>/', views.admin_special_code_delete, name='admin_special_code_delete'),
    path('api/get-blocks-for-match/', views.get_blocks_for_match, name='get_blocks_for_match'),
    path('export-sales-report/', views.export_sales_report_excel, name='export_sales_report'),
    path('bulk-download-user-tickets/', views.bulk_download_user_tickets, name='bulk_download_user_tickets'),
    path('vip-edit-issued-ticket/<int:ticket_id>/', views.vip_edit_issued_ticket, name='vip_edit_issued_ticket'),
    path('vip-delete-issued-ticket/<int:ticket_id>/', views.vip_delete_issued_ticket, name='vip_delete_issued_ticket'),
    path('inquiry-fan/', views.inquiry_fan, name='inquiry_fan'),
]

# from django.urls import path
# from . import views
#
# app_name = 'tickets'
#
# urlpatterns = [
#     path('select/<int:match_id>/', views.select_seats, name='select_seats'),
#     path('ticket-info/<int:match_id>/', views.ticket_info, name='ticket_info'),
#     path('my-tickets/', views.user_tickets, name='user_tickets'),
#     path('vip-tickets/', views.vip_tickets, name='vip_tickets'),
#     path('bulk-issue/', views.bulk_issue_tickets, name='bulk_issue'),
#     path('manage-vip-users/', views.manage_vip_users, name='manage_vip_users'),
#     path('manage-user-tickets/<int:user_id>/', views.manage_user_tickets, name='manage_user_tickets'),
#     path('sales-report/', views.sales_report, name='sales_report'),
#     path('vip-dashboard/', views.vip_dashboard, name='vip_dashboard'),
#     path('vip-issue-manual/<int:match_id>/', views.vip_issue_manual, name='vip_issue_manual'),
#     path('vip-issue-excel/<int:match_id>/', views.vip_issue_excel, name='vip_issue_excel'),
#     path('row-occupancy/', views.row_occupancy_report, name='row_occupancy'),
#     path('vip-issued-tickets/', views.vip_issued_tickets, name='vip_issued_tickets'),
#     path('bulk-download/', views.bulk_download_tickets, name='bulk_download'),
#     path('vip-tickets/', views.vip_tickets, name='vip_tickets'),
#     path('bulk-download-received/', views.bulk_download_received_tickets, name='bulk_download_received'),
#     path('admin-reports/', views.admin_reports, name='admin_reports'),
#     path('select/<int:match_id>/', views.select_seats, name='select_seats'),
#     path('sales-report/', views.sales_report, name='sales_report'),  # ← نسخه نموداری
#
# ]
