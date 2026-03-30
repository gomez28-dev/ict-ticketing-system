from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import User, Team, Project, Ticket

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