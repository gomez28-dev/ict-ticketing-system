from django.contrib import admin
from django.urls import path
from tickets import views

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', views.public_submit, name='public_submit'),

    # Dashboard Links
    path('admin-dashboard/', views.dashboard, name='dashboard'),
    path('admin-dashboard/analytics/', views.analytics_dashboard, name='analytics'),
    path('admin-dashboard/requests/', views.requests_view, name='requests'),
    path('admin-dashboard/backlog/', views.backlog_view, name='backlog'),  # <-- New Backlog Page
    path('admin-dashboard/create/', views.admin_create_ticket, name='admin_create_ticket'),

    # Form Actions
    path('admin-dashboard/requests/approve/<int:ticket_id>/', views.approve_request, name='approve_request'),
    path('admin-dashboard/requests/delete/<int:ticket_id>/', views.delete_request, name='delete_request'),
    path('admin-dashboard/backlog/move/<int:ticket_id>/', views.move_from_backlog, name='move_from_backlog'),
    path('admin-dashboard/ticket/update/<int:ticket_id>/', views.update_ticket_ajax, name='update_ticket_ajax'),
    path('admin-dashboard/search/', views.search_tickets, name='search_tickets'),
    path('admin-dashboard/settings/', views.settings_view, name='settings'),
    path('admin-dashboard/request/<int:ticket_id>/triage/', views.ticket_triage_view, name='ticket_triage'),
    path('admin-dashboard/teams/', views.teams_view, name='teams'),
]