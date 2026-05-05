from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import User, Team, Project, Ticket, PerformanceReview

# Registers user, team, and project models
admin.site.register(User, UserAdmin)
admin.site.register(Team)
admin.site.register(Project)

# Enhanced admin view for Tickets
@admin.register(Ticket)
class TicketAdmin(admin.ModelAdmin):
    list_display = ('ticket_number', 'title', 'status', 'work_type', 'priority', 'school_name', 'created_at')
    list_filter = ('status', 'work_type', 'priority', 'support_type', 'school_district')
    search_fields = ('ticket_number', 'title', 'school_name', 'first_name', 'last_name')
    readonly_fields = ('ticket_number', 'created_at', 'updated_at')

@admin.register(PerformanceReview)
class PerformanceReviewAdmin(admin.ModelAdmin):
    list_display = ('ticket', 'employee', 'reviewed_by', 'quality', 'efficiency', 'timeliness', 'overall', 'created_at')
    list_filter = ('quality', 'efficiency', 'timeliness')
    search_fields = ('employee__first_name', 'employee__last_name', 'ticket__ticket_number')