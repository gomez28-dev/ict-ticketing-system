from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import User, Team, Project, Ticket

# This registers your models so you can edit them in the backend
admin.site.register(User, UserAdmin)
admin.site.register(Team)
admin.site.register(Project)
admin.site.register(Ticket)