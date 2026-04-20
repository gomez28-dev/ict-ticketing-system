from django.db import models
from django.contrib.auth.models import AbstractUser
from django.utils import timezone


class Team(models.Model):
    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


class User(AbstractUser):
    ROLE_CHOICES = (
        ('ADMIN', 'Admin'),
        ('MEMBER', 'Employee'),
    )
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default='MEMBER')
    team = models.ForeignKey(Team, on_delete=models.SET_NULL, null=True, blank=True, related_name='members')
    expertise = models.CharField(
        max_length=255,
        blank=True,
        help_text="Comma-separated skills (e.g., CCTV, NETWORK, PC_MAINTENANCE)"
    )

    def __str__(self):
        return f"{self.username} ({self.get_role_display()})"


class Project(models.Model):
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name='projects')
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


class School(models.Model):
    name = models.CharField(max_length=255, unique=True)
    school_id = models.CharField(max_length=50, unique=True)
    district = models.CharField(max_length=100, blank=True, null=True)
    password = models.CharField(max_length=128, default='pbkdf2_sha256$1200000$yxVstmeDa4jgFPKbARyyYt$TYZVP2LaT6q3jtk6FzUV75dzoGUi4DD+7LfmWAAsrlE=') # Default: DepEd123!

    def set_password(self, raw_password):
        from django.contrib.auth.hashers import make_password
        self.password = make_password(raw_password)

    def check_password(self, raw_password):
        from django.contrib.auth.hashers import check_password
        return check_password(raw_password, self.password)

    def __str__(self):
        return f"{self.name} ({self.school_id})"


class Ticket(models.Model):
    STATUS_CHOICES = (
        ('PENDING', 'Pending Review'),
        ('PENDING_ACCEPTANCE', 'Pending Acceptance'),
        ('SCHEDULED', 'Scheduled'),
        ('IN_PROGRESS', 'In Progress'),
        ('UNRESOLVED', 'Unresolved'),
        ('RESOLVED', 'Resolved'),
        ('COMPLETED', 'Completed'),
    )

    PRIORITY_CHOICES = (
        ('LOW', 'Low'),
        ('MEDIUM', 'Medium'),
        ('HIGH', 'High'),
        ('URGENT', 'Urgent'),
    )

    SUPPORT_CHOICES = (
        ('CCTV', 'CCTV Maintenance/Check-Up or Repair Request'),
        ('PC_MAINTENANCE', 'Computer Maintenance/Check-Up or Repair Request'),
        ('NETWORK_MAINTENANCE', 'Computer Network Maintenance/Check-Up or Repair Request'),
        ('GOOGLE_ACCOUNT', 'Creation of Google Account'),
        ('MS_ACCOUNT', 'Creation of Microsoft Account'),
        ('PASSWORD_RESET', 'Password Reset for Microsoft or Google Account'),
        ('OTHER', 'Other Support'),
    )

    WORK_TYPE_CHOICES = (
        ('REMOTE WORK', 'REMOTE WORK (Can be done online or from home)'),
        ('FIELD WORK', 'FIELD WORK (Outside job/on-site task)'),
    )

    # --- Core Ticket Data ---
    ticket_number = models.CharField(max_length=20, unique=True, blank=True)
    title = models.CharField(max_length=255, blank=True)
    description = models.TextField(help_text="Request Details")
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='tickets', null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PENDING')
    priority = models.CharField(max_length=20, choices=PRIORITY_CHOICES, default='MEDIUM')

    # --- Work Type Field ---
    work_type = models.CharField(max_length=20, choices=WORK_TYPE_CHOICES, null=True, blank=True,
                                 help_text="Category of task assignment")

    # --- Public Form Fields ---
    school_district = models.CharField(max_length=100, null=True, blank=True)
    school_name = models.CharField(max_length=255, null=True, blank=True)
    support_type = models.CharField(max_length=100, choices=SUPPORT_CHOICES, null=True, blank=True)

    # --- Requester Details ---
    first_name = models.CharField(max_length=100, null=True, blank=True)
    last_name = models.CharField(max_length=100, null=True, blank=True)
    middle_name = models.CharField(max_length=100, blank=True, null=True)
    contact_number = models.CharField(max_length=20, null=True, blank=True)
    email = models.EmailField(null=True, blank=True)
    admin_notes = models.TextField(blank=True, null=True, help_text="Internal notes for ICT Unit")
    predicted_hours = models.IntegerField(blank=True, null=True, help_text="AI estimated resolution time in hours")

    # --- Assignments ---
    reporter = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True,
                                 related_name='reported_tickets')
    assignee = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True,
                                 related_name='assigned_tickets')

    # --- AI-Ready Data Fields ---
    complexity = models.IntegerField(default=1, help_text="Story points or complexity scale (e.g., 1-10)")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # --- SCHEDULED DATE & TIME FIELDS ---
    scheduled_date = models.DateField(null=True, blank=True, help_text="Date the ticket is scheduled for")
    scheduled_time = models.TimeField(null=True, blank=True, help_text="Time the ticket is scheduled for")

    due_date = models.DateTimeField(null=True, blank=True)
    actual_completion_date = models.DateTimeField(null=True, blank=True)

    def save(self, *args, **kwargs):
        if not self.ticket_number:
            current_year = timezone.now().year
            last_ticket = Ticket.objects.filter(ticket_number__startswith=f'TKT-{current_year}').order_by(
                'ticket_number').last()
            if last_ticket:
                last_number = int(last_ticket.ticket_number.split('-')[2])
                new_number = last_number + 1
            else:
                new_number = 1
            self.ticket_number = f'TKT-{current_year}-{new_number:04d}'

        if not self.title and self.support_type and self.school_name:
            self.title = f"{self.get_support_type_display()} - {self.school_name}"

        # Capture completion date if resolved OR completed
        if self.status in ['RESOLVED', 'COMPLETED'] and not self.actual_completion_date:
            self.actual_completion_date = timezone.now()
        elif self.status not in ['RESOLVED', 'COMPLETED'] and self.actual_completion_date:
            self.actual_completion_date = None

        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.ticket_number} - {self.title}"

    @property
    def get_assignee_initials(self):
        if self.admin_notes and 'Assigned to:' in self.admin_notes:
            try:
                assign_line = next((line for line in self.admin_notes.split('\n') if 'Assigned to:' in line), None)
                if assign_line:
                    names_string = assign_line.replace('Assigned to:', '').strip()
                    if names_string and names_string != 'Unassigned':
                        names = [name.strip() for name in names_string.split(',')]
                        return [name[0].upper() for name in names if name]
            except Exception:
                pass
        return []


class UserSettings(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='settings')
    dark_mode_enabled = models.BooleanField(default=False)
    email_notifications = models.BooleanField(default=True)

    def __str__(self):
        return f"Settings for {self.user.username}"


class TicketAuditLog(models.Model):
    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name='audit_logs')
    changed_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    action = models.CharField(max_length=255)
    old_value = models.TextField(blank=True, null=True)
    new_value = models.TextField(blank=True, null=True)
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-timestamp']

    def __str__(self):
        return f"{self.ticket.ticket_number} - {self.action} at {self.timestamp}"