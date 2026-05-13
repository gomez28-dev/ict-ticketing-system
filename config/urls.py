from django.contrib import admin
from django.urls import path
from tickets import views
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path('admin/', admin.site.urls),

    # Auth Links
    path('login/', views.custom_login, name='login'),
    path('logout/', views.custom_logout, name='logout'),
    path('school-login/', views.school_login, name='school_login'),
    path('school-logout/', views.school_logout, name='school_logout'),
    path('forgot-password/', views.forgot_password, name='forgot_password'),
    path('forgot-password/verify/', views.verify_otp, name='verify_otp'),
    path('forgot-password/reset/', views.reset_password_confirm, name='reset_password_confirm'),
    path('request-access/', views.request_access, name='request_access'),
    path('school-dashboard/', views.school_dashboard, name='school_dashboard'),
    path('school-dashboard/ticket/<int:ticket_id>/', views.school_ticket_detail, name='school_ticket_detail'),
    path('school-dashboard/ticket/<int:ticket_id>/print/', views.school_print_ticket, name='school_print_ticket'),

    # Dashboard Links
    path('admin-dashboard/', views.dashboard, name='dashboard'),
    path('admin-dashboard/analytics/', views.analytics_dashboard, name='analytics'),
    path('admin-dashboard/requests/', views.requests_view, name='requests'),
    path('admin-dashboard/requests/reviewed/<int:ticket_id>/', views.reviewed_ticket_readonly, name='reviewed_ticket_readonly'),

    # --- DOCUMENTS ACTIONS ---
    path('admin-dashboard/documents/', views.documents_view, name='documents'),
    path('admin-dashboard/documents/complete/<int:ticket_id>/', views.complete_ticket_ajax,
         name='complete_ticket_ajax'),

    path('admin-dashboard/backlog/', views.backlog_view, name='backlog'),
    path('admin-dashboard/teams/', views.teams_view, name='teams'),
    path('admin-dashboard/schools/', views.schools_management, name='schools_management'),
    path('admin-dashboard/schools/force-reset/<int:school_id>/', views.admin_force_reset_password, name='admin_force_reset_password'),
    path('admin-dashboard/schools/delete/<int:school_id>/', views.admin_delete_school, name='admin_delete_school'),
    path('admin-dashboard/schools/account/approve/<int:request_id>/', views.approve_account_request, name='approve_account_request'),
    path('admin-dashboard/schools/account/reject/<int:request_id>/', views.reject_account_request, name='reject_account_request'),
    path('admin-dashboard/add-employee/', views.add_employee, name='add_employee'),
    path('admin-dashboard/settings/delete-account/', views.delete_user_account, name='delete_user_account'),

    # Employee Specific Links
    path('admin-dashboard/my-tickets/', views.my_tickets, name='my_tickets'),
    path('admin-dashboard/my-tickets/review/<int:ticket_id>/', views.employee_ticket_review,
         name='employee_ticket_review'),
    path('admin-dashboard/my-tickets/accept/<int:ticket_id>/', views.accept_assignment, name='accept_assignment'),
    path('admin-dashboard/my-tickets/decline/<int:ticket_id>/', views.decline_assignment, name='decline_assignment'),
    path('admin-dashboard/my-tickets/resolve/<int:ticket_id>/', views.resolve_assignment, name='resolve_assignment'),
    path('admin-dashboard/my-tickets/unresolve/<int:ticket_id>/', views.unresolve_assignment, name='unresolve_assignment'),
    path('admin-dashboard/my-tickets/submit-review/<int:ticket_id>/', views.submit_for_review, name='submit_for_review'),

    # Employee Receipt Path
    path('admin-dashboard/my-tickets/receipt/<int:ticket_id>/', views.employee_receipt_view, name='employee_receipt'),

    # Form Actions & Triage
    path('admin-dashboard/requests/approve/<int:ticket_id>/', views.approve_request, name='approve_request'),
    path('admin-dashboard/requests/decline/<int:ticket_id>/', views.decline_request, name='decline_request'),
    path('admin-dashboard/requests/delete/<int:ticket_id>/', views.delete_request, name='delete_request'),
    path('admin-dashboard/backlog/move/<int:ticket_id>/', views.move_from_backlog, name='move_from_backlog'),
    path('admin-dashboard/ticket/update/<int:ticket_id>/', views.update_ticket_ajax, name='update_ticket_ajax'),
    path('admin-dashboard/search/', views.search_tickets, name='search_tickets'),
    path('admin-dashboard/settings/', views.settings_view, name='settings'),
    path('admin-dashboard/request/<int:ticket_id>/', views.ticket_triage_view, name='ticket_triage'),
    path('admin-dashboard/request/reject-unresolved/<int:ticket_id>/', views.reject_unresolved, name='reject_unresolved'),
    path('school-dashboard/delete-account/', views.delete_school_account, name='delete_school_account'),

    # Performance Review (Phase 4)
    path('admin-dashboard/documents/review/<int:ticket_id>/', views.submit_performance_review, name='submit_performance_review'),

    # Employee Profile (Phase 5)
    path('admin-dashboard/employee/<int:user_id>/profile/', views.employee_profile, name='employee_profile'),
    path('admin-dashboard/employee/<int:user_id>/edit/', views.edit_employee_profile, name='edit_employee_profile'),

    # OMR Scanner (Phase 6)
    path('admin-dashboard/scanner/', views.mobile_scanner, name='mobile_scanner'),
    path('admin-dashboard/api/process-scan/', views.api_process_scan, name='api_process_scan'),
    path('admin-dashboard/api/save-review/', views.api_save_review, name='api_save_review'),

    # Password Change (Phase 7)
    path('admin-dashboard/change-password/', views.change_password, name='change_password'),
    path('admin-dashboard/dismiss-password-change/', views.dismiss_password_change, name='dismiss_password_change'),
]

# Always register media routes so uploaded attachments are accessible.
# In high-traffic production, serve media via nginx/CDN instead.
urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
