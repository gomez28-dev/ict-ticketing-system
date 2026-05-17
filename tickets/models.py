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
    class Role(models.TextChoices):
        ADMIN = 'ADMIN', 'Admin'
        MEMBER = 'MEMBER', 'Employee'

    role = models.CharField(max_length=20, choices=Role.choices, default=Role.MEMBER)
    email = models.EmailField(unique=True, db_index=True)
    team = models.ForeignKey(Team, on_delete=models.SET_NULL, null=True, blank=True, related_name='members')
    expertise = models.CharField(
        max_length=255,
        blank=True,
        help_text="Comma-separated skills (e.g., CCTV, NETWORK, PC_MAINTENANCE)"
    )

    # --- Performance Scores ---
    quality_score = models.FloatField(default=0.0)
    efficiency_score = models.FloatField(default=0.0)
    timeliness_score = models.FloatField(default=0.0)
    overall_rating = models.FloatField(default=0.0)
    total_reviews = models.IntegerField(default=0)
    total_tasks_done = models.IntegerField(default=0)

    # --- Password Change Tracking ---
    has_changed_password = models.BooleanField(
        default=False,
        help_text="Set to True after the user changes or dismisses the default password prompt."
    )

    # --- Profile Fields ---
    profile_picture = models.ImageField(upload_to='profile_pics/', null=True, blank=True)
    bio = models.TextField(blank=True, null=True)

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
    ict_first_name = models.CharField(max_length=100, blank=True, null=True)
    ict_last_name = models.CharField(max_length=100, blank=True, null=True)
    ict_contact_number = models.CharField(max_length=20, blank=True, null=True)
    ict_email = models.EmailField(blank=True, null=True)

    def set_password(self, raw_password):
        from django.contrib.auth.hashers import make_password
        self.password = make_password(raw_password)

    def check_password(self, raw_password):
        from django.contrib.auth.hashers import check_password
        return check_password(raw_password, self.password)

    def __str__(self):
        return f"{self.name} ({self.school_id})"



class PasswordResetOTP(models.Model):
    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name='otp_codes')
    code = models.CharField(max_length=6)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    is_used = models.BooleanField(default=False)

    def save(self, *args, **kwargs):
        if not self.expires_at:
            from datetime import timedelta
            self.expires_at = timezone.now() + timedelta(minutes=15)
        super().save(*args, **kwargs)

    @property
    def is_expired(self):
        return timezone.now() > self.expires_at

    @property
    def is_valid(self):
        return not self.is_used and not self.is_expired

    @staticmethod
    def generate_code():
        import random
        return f"{random.randint(100000, 999999)}"

    def __str__(self):
        status = "Valid" if self.is_valid else ("Used" if self.is_used else "Expired")
        return f"OTP for {self.school.name}: {self.code} [{status}]"


class SchoolAccountRequest(models.Model):
    STATUS_CHOICES = (
        ('PENDING', 'Pending Review'),
        ('APPROVED', 'Approved'),
        ('REJECTED', 'Rejected'),
    )
    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name='account_requests')
    ict_name = models.CharField(max_length=200, help_text="Full name of the ICT Coordinator")
    email = models.EmailField()
    contact_number = models.CharField(max_length=20)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PENDING')
    domain_verified = models.BooleanField(default=False, help_text="Auto-flagged if email ends with @deped.gov.ph")
    request_date = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        # Auto-flag domain verification for official DepEd emails
        if self.email and self.email.strip().lower().endswith('@deped.gov.ph'):
            self.domain_verified = True
        else:
            self.domain_verified = False
        super().save(*args, **kwargs)

    def __str__(self):
        verified = "✓ Verified" if self.domain_verified else "✗ Unverified"
        return f"Access Request: {self.school.name} ({self.status}) [{verified}]"


class Ticket(models.Model):
    class Status(models.TextChoices):
        PENDING = 'PENDING', 'Pending Review'
        PENDING_ACCEPTANCE = 'PENDING_ACCEPTANCE', 'Pending Acceptance'
        SCHEDULED = 'SCHEDULED', 'Scheduled'
        IN_PROGRESS = 'IN_PROGRESS', 'In Progress'
        UNRESOLVED = 'UNRESOLVED', 'Unresolved'
        UNDER_REVIEW = 'UNDER_REVIEW', 'Under Review'
        RESOLVED = 'RESOLVED', 'Resolved'
        COMPLETED = 'COMPLETED', 'Completed'
        DECLINED = 'DECLINED', 'Declined'

    class Priority(models.TextChoices):
        LOW = 'LOW', 'Low'
        MEDIUM = 'MEDIUM', 'Medium'
        HIGH = 'HIGH', 'High'
        URGENT = 'URGENT', 'Urgent'

    class SupportType(models.TextChoices):
        CCTV = 'CCTV', 'CCTV Maintenance/Check-Up or Repair Request'
        PC_MAINTENANCE = 'PC_MAINTENANCE', 'Computer Maintenance/Check-Up or Repair Request'
        NETWORK_MAINTENANCE = 'NETWORK_MAINTENANCE', 'Computer Network Maintenance/Check-Up or Repair Request'
        GOOGLE_ACCOUNT = 'GOOGLE_ACCOUNT', 'Creation of Google Account'
        MS_ACCOUNT = 'MS_ACCOUNT', 'Creation of Microsoft Account'
        PASSWORD_RESET = 'PASSWORD_RESET', 'Password Reset for Microsoft or Google Account'
        OTHER = 'OTHER', 'Other Support'

    class WorkType(models.TextChoices):
        REMOTE_WORK = 'REMOTE WORK', 'REMOTE WORK (Can be done online or from home)'
        FIELD_WORK = 'FIELD WORK', 'FIELD WORK (Outside job/on-site task)'

    # --- Core Ticket Data ---
    ticket_number = models.CharField(max_length=20, unique=True, blank=True)
    title = models.CharField(max_length=255, blank=True)
    description = models.TextField(help_text="Request Details")
    attachment = models.FileField(upload_to='ticket_attachments/', null=True, blank=True)
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='tickets', null=True, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING, db_index=True)
    priority = models.CharField(max_length=20, choices=Priority.choices, default=Priority.LOW)
    decline_reason = models.TextField(blank=True, null=True)

    # --- Work Type Field ---
    work_type = models.CharField(max_length=20, choices=WorkType.choices, null=True, blank=True,
                                 help_text="Category of task assignment")

    # --- Public Form Fields ---
    school_district = models.CharField(max_length=100, null=True, blank=True)
    school_name = models.CharField(max_length=255, null=True, blank=True)
    support_type = models.CharField(max_length=100, choices=SupportType.choices, null=True, blank=True)

    # --- Requester Details ---
    first_name = models.CharField(max_length=100, null=True, blank=True)
    last_name = models.CharField(max_length=100, null=True, blank=True)
    middle_name = models.CharField(max_length=100, blank=True, null=True)
    contact_number = models.CharField(max_length=20, null=True, blank=True)
    email = models.EmailField(null=True, blank=True)
    admin_notes = models.TextField(blank=True, null=True, help_text="Internal notes for ICT Unit")
    predicted_hours = models.IntegerField(blank=True, null=True, help_text="AI estimated resolution time in hours")

    # --- AI Duration Fields ---
    predicted_days = models.IntegerField(blank=True, null=True, help_text="AI estimated duration in days")
    start_date = models.DateField(null=True, blank=True, help_text="Start date for the task")
    end_date = models.DateField(null=True, blank=True, help_text="End date calculated from predicted_days")

    # --- Assignments ---
    reporter = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True,
                                 related_name='reported_tickets')
    assignee = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True,
                                 related_name='assigned_tickets')

    # --- Resolution Details ---
    resolution_notes = models.TextField(blank=True, null=True)
    resolution_attachment = models.FileField(upload_to='resolutions/', null=True, blank=True)
    client_signature = models.TextField(blank=True, null=True, help_text="Base64-encoded client signature image")

    # --- AI-Ready Data Fields ---
    complexity = models.IntegerField(default=1, help_text="Story points or complexity scale (e.g., 1-10)")
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    # --- SCHEDULED DATE & TIME FIELDS ---
    scheduled_date = models.DateField(null=True, blank=True, help_text="Date the ticket is scheduled for")
    scheduled_start_time = models.TimeField(null=True, blank=True, help_text="Start time the ticket is scheduled for")
    scheduled_end_time = models.TimeField(null=True, blank=True, help_text="End time the ticket is scheduled for")

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


class PerformanceReview(models.Model):
    SCORE_CHOICES = (
        (2, '2 - Below Average'),
        (3, '3 - Average'),
        (4, '4 - Good'),
        (5, '5 - Excellent'),
    )

    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name='performance_reviews')
    reviewed_by = models.ForeignKey(User, on_delete=models.CASCADE, related_name='reviews_given')
    employee = models.ForeignKey(User, on_delete=models.CASCADE, related_name='reviews_received')
    quality = models.IntegerField(choices=SCORE_CHOICES)
    efficiency = models.IntegerField(choices=SCORE_CHOICES)
    timeliness = models.IntegerField(choices=SCORE_CHOICES)
    overall = models.FloatField(default=0.0)
    notes = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        # Auto-compute overall score on save
        from .ml_service import calculate_overall_rating
        self.overall = calculate_overall_rating(self.quality, self.efficiency, self.timeliness)
        super().save(*args, **kwargs)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"Review for {self.employee.get_full_name()} on {self.ticket.ticket_number}"


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