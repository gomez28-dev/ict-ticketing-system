from django.contrib import admin
from django.urls import path
from tickets import views

urlpatterns = [
    path('admin/', admin.site.urls),

    # Public Helpdesk Submission Form
    path('', views.public_submit, name='public_submit'),

    # Auth Links
    path('login/', views.custom_login, name='login'),
    path('logout/', views.custom_logout, name='logout'),
    path('school-login/', views.school_login, name='school_login'),

    # Dashboard Links
    path('admin-dashboard/', views.dashboard, name='dashboard'),
    path('admin-dashboard/analytics/', views.analytics_dashboard, name='analytics'),
    path('admin-dashboard/requests/', views.requests_view, name='requests'),
    path('admin-dashboard/backlog/', views.backlog_view, name='backlog'),
    path('admin-dashboard/create/', views.admin_create_ticket, name='admin_create_ticket'),
    path('admin-dashboard/teams/', views.teams_view, name='teams'),
    path('admin-dashboard/add-employee/', views.add_employee, name='add_employee'),

    # Employee Specific Links
    path('admin-dashboard/my-tickets/', views.my_tickets, name='my_tickets'),
    path('admin-dashboard/my-tickets/review/<int:ticket_id>/', views.employee_ticket_review,
         name='employee_ticket_review'),
    path('admin-dashboard/my-tickets/accept/<int:ticket_id>/', views.accept_assignment, name='accept_assignment'),
    path('admin-dashboard/my-tickets/decline/<int:ticket_id>/', views.decline_assignment, name='decline_assignment'),
    path('admin-dashboard/my-tickets/resolve/<int:ticket_id>/', views.resolve_assignment, name='resolve_assignment'),
    path('admin-dashboard/my-tickets/unresolve/<int:ticket_id>/', views.unresolve_assignment,
         name='unresolve_assignment'),

    # Form Actions & Triage
    path('admin-dashboard/requests/approve/<int:ticket_id>/', views.approve_request, name='approve_request'),
    path('admin-dashboard/requests/delete/<int:ticket_id>/', views.delete_request, name='delete_request'),
    path('admin-dashboard/backlog/move/<int:ticket_id>/', views.move_from_backlog, name='move_from_backlog'),
    path('admin-dashboard/ticket/update/<int:ticket_id>/', views.update_ticket_ajax, name='update_ticket_ajax'),
    path('admin-dashboard/search/', views.search_tickets, name='search_tickets'),
    path('admin-dashboard/settings/', views.settings_view, name='settings'),
    path('admin-dashboard/request/<int:ticket_id>/', views.ticket_triage_view, name='ticket_triage'),
]