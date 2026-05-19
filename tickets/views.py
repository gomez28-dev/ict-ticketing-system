from .ml_service import predict_ticket_duration, recommend_staff, predict_risk, get_mapped_support_type, calculate_overall_rating
from .staff_data import STAFF_LIST
from django.utils import timezone
from .models import Ticket, School, TicketAuditLog, SchoolAccountRequest, PasswordResetOTP, PerformanceReview
import math
from datetime import date, timedelta
from .forms import PublicTicketForm, SubmitForReviewForm, validate_ph_mobile
from django.core.paginator import Paginator
from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse
from django.urls import reverse
from django.db.models import Q, Count
from django.db.models.functions import TruncDate
import json
from django.contrib.auth import authenticate, login, logout, update_session_auth_hash
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import user_passes_test, login_required
from django.contrib import messages
from .email_utils import send_new_account_email, DEFAULT_PASSWORD

User = get_user_model()

# ==========================================
# ROLE-BASED ACCESS CONTROL (RBAC) TESTS
# ==========================================

def is_superadmin(user):
    return user.is_superuser

def is_admin_or_superuser(user):
    if not user.is_authenticated:
        return False
    return user.is_superuser or user.role == 'ADMIN'


def is_employee(user):
    return user.is_authenticated and not user.is_superuser and getattr(user, 'role', '') == 'MEMBER'


ASSIGNED_REVIEW_STATUSES = ['PENDING_ACCEPTANCE', 'SCHEDULED', 'IN_PROGRESS', 'UNDER_REVIEW']
ADMIN_KANBAN_STATUSES = {'SCHEDULED', 'IN_PROGRESS', 'UNDER_REVIEW', 'UNRESOLVED', 'RESOLVED'}
EMPLOYEE_KANBAN_STATUSES = {'SCHEDULED', 'IN_PROGRESS', 'UNDER_REVIEW', 'UNRESOLVED'}


def is_employee_available(employee_name, start_date, end_date):
    """
    Checks if an employee is available for the proposed date range.
    Returns True if the employee is free, False if there is a conflict.
    Two date ranges overlap if: existing_start <= proposed_end AND existing_end >= proposed_start
    """
    if not start_date or not end_date:
        return True

    conflicting_tickets = Ticket.objects.filter(
        admin_notes__icontains=employee_name,
        start_date__isnull=False,
        end_date__isnull=False,
        start_date__lte=end_date,
        end_date__gte=start_date,
    ).exclude(status='RESOLVED').exclude(status='COMPLETED').exclude(status='DECLINED')

    return not conflicting_tickets.exists()


def is_email_already_associated(email, exclude_school_id=None, exclude_account_request_id=None):
    normalized_email = (email or '').strip().lower()
    if not normalized_email:
        return False

    if User.objects.filter(email__iexact=normalized_email).exists():
        return True

    school_query = School.objects.filter(ict_email__iexact=normalized_email)
    if exclude_school_id:
        school_query = school_query.exclude(id=exclude_school_id)
    if school_query.exists():
        return True

    request_query = SchoolAccountRequest.objects.filter(email__iexact=normalized_email)
    if exclude_account_request_id:
        request_query = request_query.exclude(id=exclude_account_request_id)
    return request_query.exists()


def resolve_assignee_from_names(assigned_staff_names):
    normalized_staff_names = [name.strip().lower() for name in assigned_staff_names if name and name.strip()]
    if not normalized_staff_names:
        return None

    for staff_name in normalized_staff_names:
        for user in User.objects.all():
            full_name = f"{user.first_name} {user.last_name}".strip().lower()
            if staff_name == full_name:
                return user
            if staff_name == (user.username or '').strip().lower():
                return user
            if staff_name == (user.email or '').strip().lower():
                return user
    return None


def extract_latest_unresolved_reason(admin_notes):
    if not admin_notes:
        return ''

    unresolved_lines = [
        line.strip() for line in admin_notes.split('\n')
        if 'marked as Unresolved:' in line
    ]
    return unresolved_lines[-1] if unresolved_lines else ''

@user_passes_test(is_superadmin, login_url='dashboard')
def add_employee(request):
    error = None
    if request.method == 'POST':
        first_name = request.POST.get('first_name')
        last_name = request.POST.get('last_name')
        email = request.POST.get('email')
        role = request.POST.get('role', 'MEMBER')
        expertise = request.POST.get('expertise', '')

        username = email.split('@')[0] if email else f"{first_name.lower()}.{last_name.lower()}"

        if is_email_already_associated(email):
            error = "This email is already associated with an account"
        elif User.objects.filter(username=username).exists() or User.objects.filter(email=email).exists():
            error = "An employee with this email or username already exists."
        else:
            new_user = User.objects.create_user(
                username=username, email=email, password=DEFAULT_PASSWORD,
                first_name=first_name, last_name=last_name, role=role, expertise=expertise
            )
            new_user.has_changed_password = False
            if role == 'ADMIN':
                new_user.is_staff = True
            new_user.save()

            # Send welcome email with default credentials
            try:
                login_url = request.build_absolute_uri(reverse('login'))
                send_new_account_email(email, first_name, login_url)
            except Exception as e:
                import logging
                logging.getLogger(__name__).error(f"Failed to send welcome email: {e}")

            return redirect('teams')

    return render(request, 'tickets/employee_form.html', {'error': error})

# ==========================================
# AUTHENTICATION VIEWS
# ==========================================

def custom_login(request):
    if request.user.is_authenticated:
        return redirect('dashboard')

    if request.method == 'POST':
        email_input = request.POST.get('email', '').strip()
        password_input = request.POST.get('password', '')

        if not email_input or not password_input:
            return render(request, 'tickets/login.html', {'error': 'Please provide both email and password.'})

        # HARDCODED ACCOUNTS FOR TESTING ONLY
        test_accounts = {
            'superadmin@test.com': {'pass': 'super123', 'role': 'SUPERADMIN'},
            'admin@test.com': {'pass': 'admin123', 'role': 'ADMIN'},
            'employee@test.com': {'pass': 'emp123', 'role': 'MEMBER'}
        }

        if email_input in test_accounts and password_input == test_accounts[email_input]['pass']:
            role = test_accounts[email_input]['role']
            if role == 'MEMBER':
                first_name_value = "Juan"
                last_name_value = "Pedro"
            elif role == 'ADMIN':
                first_name_value = "Alice"
                last_name_value = "Tan"
            else:  # SUPERADMIN
                first_name_value = "Ramon"
                last_name_value = "Sy"
            
            user, created = User.objects.get_or_create(email=email_input, defaults={
                'username': email_input.split('@')[0],
                'first_name': first_name_value,
                'last_name': last_name_value,
                'role': role if role != 'SUPERADMIN' else 'ADMIN',
                'is_staff': True if role in ['ADMIN', 'SUPERADMIN'] else False,
                'is_superuser': True if role == 'SUPERADMIN' else False
            })
            
            # Ensure name matches if it was created incorrectly previously
            if not created and (user.first_name != first_name_value or user.last_name != last_name_value):
                user.first_name = first_name_value
                user.last_name = last_name_value
                user.save()
                
            if created:
                user.set_password(password_input)
                user.save()
            login(request, user)
            return redirect('dashboard')

        user = User.objects.filter(email__iexact=email_input).first()
        if user and user.check_password(password_input):
            login(request, user)
            return redirect('dashboard')
        else:
            return render(request, 'tickets/login.html', {'error': 'Invalid email or password.'})

    return render(request, 'tickets/login.html')

def custom_logout(request):
    logout(request)
    return redirect('login')

def school_login(request):
    if request.method == 'POST':
        school_id = request.POST.get('school_id')
        password = request.POST.get('password')
        try:
            school = School.objects.get(school_id=school_id)
            if school.check_password(password):
                request.session['school_name'] = school.name
                request.session['is_school_authenticated'] = True
                return redirect('school_dashboard')
            else:
                messages.error(request, 'Invalid Password. Please try again.')
        except School.DoesNotExist:
            messages.error(request, 'Invalid School ID. Please try again.')

    return render(request, 'tickets/school_login.html')

def school_logout(request):
    request.session.flush()
    return redirect('school_login')

def school_dashboard(request):
    if not request.session.get('is_school_authenticated'):
        return redirect('school_login')

    school_name = request.session.get('school_name')
    try:
        school = School.objects.get(name=school_name)
    except School.DoesNotExist:
        return redirect('school_login')

    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'update_profile':
            new_ict_email = request.POST.get('ict_email', '').strip()
            
            normalized_email = new_ict_email.lower()
            allowed_emails = ['admin@test.com', 'employee@test.com']
            if not normalized_email.endswith('@deped.gov.ph') and normalized_email not in allowed_emails:
                messages.error(request, "Only official @deped.gov.ph email addresses are permitted.")
                return redirect('school_dashboard')

            if is_email_already_associated(new_ict_email, exclude_school_id=school.id):
                messages.error(request, "This email is already associated with an account")
                return redirect('school_dashboard')

            school.ict_first_name = request.POST.get('ict_first_name')
            school.ict_last_name = request.POST.get('ict_last_name')
            ict_contact = request.POST.get('ict_contact_number', '').strip()
            try:
                ict_contact = validate_ph_mobile(ict_contact)
            except Exception:
                messages.error(request, "Please enter a valid 11-digit Philippine mobile number starting with 09 (e.g., 09123456789).")
                return redirect('school_dashboard')
            school.ict_contact_number = ict_contact
            school.ict_email = new_ict_email
            school.save()
            messages.success(request, 'Profile updated successfully.')
        elif action == 'create_ticket':
            try:
                ticket = Ticket.objects.create(
                    first_name=school.ict_first_name or '',
                    last_name=school.ict_last_name or '',
                    contact_number=school.ict_contact_number or '',
                    email=school.ict_email or '',
                    school_name=school.name or 'Not Specified',
                    support_type=request.POST.get('support_type', 'OTHER'),
                    description=request.POST.get('description', ''),
                    status='PENDING',
                    priority='MEDIUM',
                    attachment=request.FILES.get('attachment')
                )
                ticket.predicted_hours = predict_ticket_duration(ticket.support_type, ticket.priority)['predicted_hours']
                ticket.predicted_days = predict_ticket_duration(ticket.support_type, ticket.priority)['predicted_days']
                ticket.save()
                return redirect(f"{reverse('school_dashboard')}?submitted=true&ticket_id={ticket.id}")
            except Exception as e:
                print(f"Submission Error: {e}")
                messages.error(request, "Failed to create ticket. Please try again.")
        
        return redirect('school_dashboard')

    tickets = Ticket.objects.filter(school_name=school.name).order_by('-created_at')
    
    # Notifications: get audit logs for these tickets
    ticket_ids = tickets.values_list('id', flat=True)
    notifications = TicketAuditLog.objects.filter(ticket_id__in=ticket_ids).order_by('-timestamp')[:20]

    submitted_ticket = None
    if request.GET.get('submitted') == 'true':
        submitted_ticket_id = request.GET.get('ticket_id')
        if submitted_ticket_id:
            try:
                submitted_ticket = Ticket.objects.get(id=submitted_ticket_id, school_name=school.name)
            except Ticket.DoesNotExist:
                pass

    context = {
        'school': school,
        'tickets': tickets,
        'notifications': notifications,
        'submitted_ticket': submitted_ticket,
    }
    return render(request, 'tickets/school_dashboard.html', context)

def school_ticket_detail(request, ticket_id):
    if not request.session.get('is_school_authenticated'):
        return redirect('school_login')

    school_name = request.session.get('school_name')
    ticket = get_object_or_404(Ticket, id=ticket_id, school_name=school_name)
    school = School.objects.get(name=school_name)

    assigned_employees = "None"
    general_notes = ""
    
    if ticket.admin_notes:
        lines = ticket.admin_notes.split('\n')
        notes_lines = []
        for line in lines:
            if line.startswith('Assigned to:'):
                assigned_employees = line.replace('Assigned to:', '').strip()
            else:
                if line.strip():
                    notes_lines.append(line.strip())
        general_notes = '\n'.join(notes_lines)

    context = {
        'ticket': ticket,
        'school': school,
        'assigned_employees': assigned_employees,
        'general_notes': general_notes,
    }
    return render(request, 'tickets/school_ticket_detail.html', context)


# ==========================================
# MAIN KANBAN & DASHBOARD VIEWS
# ==========================================

def dashboard(request):
    all_tickets = Ticket.objects.all().order_by('-created_at')

    # Real chart data for last 7 days
    chart_data = get_activity_chart_data()

    context = {
        'tickets': all_tickets,
        'total_tickets': all_tickets.count(),
        'resolved_tickets': all_tickets.filter(status='RESOLVED').count(),
        'staff_data': get_staff_data(),
        'graph_data': chart_data,
    }
    return render(request, 'tickets/dashboard.html', context)

@user_passes_test(is_admin_or_superuser, login_url='dashboard')
def requests_view(request):
    pending_requests = Ticket.objects.filter(status='PENDING').order_by('-created_at')
    reviewed_requests = Ticket.objects.filter(
        status__in=ASSIGNED_REVIEW_STATUSES,
        assignee__isnull=False
    ).order_by('-updated_at')
    unresolved_requests = Ticket.objects.filter(status='UNRESOLVED').order_by('-updated_at')
    return render(request, 'tickets/ticket_requests.html', {
        'pending_requests': pending_requests,
        'reviewed_requests': reviewed_requests,
        'unresolved_requests': unresolved_requests,
    })


@user_passes_test(is_admin_or_superuser, login_url='dashboard')
def reviewed_ticket_readonly(request, ticket_id):
    ticket = get_object_or_404(
        Ticket.objects.select_related('assignee'),
        id=ticket_id,
        status__in=ASSIGNED_REVIEW_STATUSES + ['UNRESOLVED']
    )
    context = {
        'ticket': ticket,
        'employee_unresolved_reason': extract_latest_unresolved_reason(ticket.admin_notes),
    }
    return render(request, 'tickets/reviewed_ticket_readonly.html', context)

@user_passes_test(is_admin_or_superuser, login_url='dashboard')
def delete_request(request, ticket_id):
    if request.method == 'POST':
        ticket = get_object_or_404(Ticket, id=ticket_id)
        ticket.delete()
    return redirect('requests')

@user_passes_test(is_admin_or_superuser, login_url='dashboard')
def decline_request(request, ticket_id):
    if request.method == 'POST':
        ticket = get_object_or_404(Ticket, id=ticket_id)
        reason = request.POST.get('decline_reason', '').strip()
        ticket.status = 'DECLINED'
        ticket.decline_reason = reason
        ticket._current_user = request.user
        ticket.save()
    return redirect('requests')

@user_passes_test(is_admin_or_superuser, login_url='dashboard')
def reject_unresolved(request, ticket_id):
    if request.method == 'POST':
        ticket = get_object_or_404(Ticket, id=ticket_id)
        reject_note = request.POST.get('reject_note', '').strip()
        
        if reject_note:
            note_entry = f"\n[Admin Rejected Unresolved Status]: {reject_note}"
            if ticket.admin_notes:
                ticket.admin_notes += note_entry
            else:
                ticket.admin_notes = note_entry
                
        ticket.status = 'IN_PROGRESS'
        ticket._current_user = request.user
        ticket.save()
        
    return redirect('requests')

@user_passes_test(is_admin_or_superuser, login_url='dashboard')
def documents_view(request):
    under_review_tickets = Ticket.objects.filter(status='UNDER_REVIEW').order_by('-updated_at')
    resolved_tickets = Ticket.objects.filter(status='RESOLVED').order_by('-updated_at')
    completed_tickets = Ticket.objects.filter(status='COMPLETED').order_by('-updated_at')
    context = {
        'under_review_tickets': under_review_tickets,
        'resolved_tickets': resolved_tickets,
        'completed_tickets': completed_tickets
    }
    return render(request, 'tickets/documents.html', context)

@user_passes_test(is_admin_or_superuser, login_url='dashboard')
def complete_ticket_ajax(request, ticket_id):
    if request.method == 'POST':
        ticket = get_object_or_404(Ticket, id=ticket_id)
        if ticket.status != 'RESOLVED':
            return JsonResponse({'success': False, 'message': 'Only resolved tickets can be completed.'}, status=400)
        ticket.status = 'COMPLETED'
        ticket._current_user = request.user
        ticket.save()
        return JsonResponse({'success': True, 'message': 'Ticket moved to Completed Documents.'})
    return JsonResponse({'success': False, 'message': 'Invalid request method.'}, status=405)

# ==========================================
# AI TRIAGE WORKFLOW
# ==========================================

@user_passes_test(is_admin_or_superuser, login_url='dashboard')
def ticket_triage_view(request, ticket_id):
    ticket = get_object_or_404(Ticket, id=ticket_id)
    duration = predict_ticket_duration(ticket.support_type, ticket.priority)
    predicted_hours = duration['predicted_hours']
    predicted_days = duration['predicted_days']
    staff_rec = recommend_staff(ticket.school_name, ticket.support_type)
    risk_assessment = predict_risk(ticket.support_type, ticket.priority)
    mapped_type = get_mapped_support_type(ticket.support_type)

    recent_school_tickets = Ticket.objects.filter(
        school_name=ticket.school_name
    ).exclude(id=ticket.id).order_by('-created_at')[:5]
    all_staff = get_staff_data()
    filtered_staff = []

    for staff in all_staff:
        # Normalize expertise (e.g., 'PC MAINTENANCE' -> 'PC_MAINTENANCE') to match the mapped type
        normalized_expertise = [str(exp).replace(' ', '_') for exp in staff['expertise']]
        if mapped_type in normalized_expertise or 'ALL' in normalized_expertise or staff['name'].strip().lower() == 'juan pedro':
            filtered_staff.append(staff)

    # Fallback if no matching staff
    if not filtered_staff:
        filtered_staff = all_staff

    # Extract feedback lines (exclude internal "Assigned to:" line)
    existing_feedback = ""
    if ticket.admin_notes:
        feedback_lines = [line for line in ticket.admin_notes.split('\n') if not line.startswith('Assigned to:')]
        existing_feedback = '\n'.join(feedback_lines).strip()

    context = {
        'ticket': ticket,
        'predicted_hours': predicted_hours,
        'predicted_days': predicted_days,
        'staff_rec': staff_rec,
        'risk_assessment': risk_assessment,
        'staff_data': filtered_staff,
        'recent_school_tickets': recent_school_tickets,
        'existing_feedback': existing_feedback,
    }
    return render(request, 'tickets/ticket_creation.html', context)

@user_passes_test(is_admin_or_superuser, login_url='dashboard')
def approve_request(request, ticket_id):
    ticket = get_object_or_404(Ticket, id=ticket_id)
    if request.method == 'POST':
        ticket.priority = request.POST.get('priority', ticket.priority)
        ticket.work_type = request.POST.get('work_type', ticket.work_type)

        scheduled_date_str = request.POST.get('scheduled_date')
        if scheduled_date_str:
            ticket.scheduled_date = scheduled_date_str

        scheduled_start_time_str = request.POST.get('scheduled_start_time')
        if scheduled_start_time_str:
            ticket.scheduled_start_time = scheduled_start_time_str

        scheduled_end_time_str = request.POST.get('scheduled_end_time')
        if scheduled_end_time_str:
            # Backend Validation
            if scheduled_start_time_str and scheduled_end_time_str <= scheduled_start_time_str:
                messages.error(request, "Scheduled End Time must be strictly after Start Time.")
                return redirect('ticket_triage', ticket_id=ticket.id)
            ticket.scheduled_end_time = scheduled_end_time_str

        # Handle start_date and end_date for duration tracking
        start_date_str = request.POST.get('start_date')
        end_date_str = request.POST.get('end_date')
        if start_date_str:
            ticket.start_date = start_date_str
        if end_date_str:
            ticket.end_date = end_date_str

        # Store predicted_days from form or compute
        predicted_days_str = request.POST.get('predicted_days')
        if predicted_days_str:
            ticket.predicted_days = int(predicted_days_str)

        assigned_staff_list = request.POST.getlist('assigned_staff')
        if not assigned_staff_list:
            assigned_staff_str = 'Unassigned'
            ticket.assignee = None
            ticket.status = 'PENDING'
        else:
            unique_staff = list(set(assigned_staff_list))

            # Scheduling conflict check
            if ticket.start_date and ticket.end_date:
                unavailable_staff = []
                for staff_name in unique_staff:
                    if not is_employee_available(staff_name, ticket.start_date, ticket.end_date):
                        unavailable_staff.append(staff_name)

                if unavailable_staff:
                    # Find available alternatives from the same expertise group
                    mapped_type = get_mapped_support_type(ticket.support_type)
                    all_staff = get_staff_data()
                    alternatives = []
                    for s in all_staff:
                        normalized_expertise = [str(exp).replace(' ', '_') for exp in s['expertise']]
                        if mapped_type in normalized_expertise or 'ALL' in normalized_expertise:
                            if s['name'] not in unique_staff and is_employee_available(s['name'], ticket.start_date, ticket.end_date):
                                alternatives.append(s['name'])

                    alt_msg = f" Available alternatives: {', '.join(alternatives[:5])}" if alternatives else " No alternatives found in the same expertise group."
                    messages.error(request, f"Scheduling conflict! The following staff are unavailable for the selected dates: {', '.join(unavailable_staff)}.{alt_msg}")
                    return redirect('ticket_triage', ticket_id=ticket.id)

            assigned_staff_str = ", ".join(unique_staff)
            ticket.assignee = resolve_assignee_from_names(unique_staff) or request.user
            ticket.status = 'PENDING_ACCEPTANCE'

        feedback = request.POST.get('admin_feedback', '').strip()
        
        # Structure admin_notes with specific headers to facilitate parsing
        ticket.admin_notes = f"Assigned to: {assigned_staff_str}"
        if feedback:
            ticket.admin_notes += f"\n{feedback}"
            
        ticket._current_user = request.user
        ticket.save()
    return redirect('dashboard')

# ==========================================
# ANALYTICS & TEAMS
# ==========================================

def get_staff_data():
    # Pre-fetch users from DB to map user_ids
    users_qs = User.objects.all()
    user_map = {}
    for u in users_qs:
        full_name = f"{u.first_name} {u.last_name}".strip()
        user_map[full_name.lower()] = u.id

    # Optimize N+1 query by fetching all active notes once
    active_notes = list(Ticket.objects.exclude(status='RESOLVED').exclude(status='COMPLETED').values_list('admin_notes', flat=True))

    staff_list_copy = [dict(s) for s in STAFF_LIST]

    for staff in staff_list_copy:
        # Count active tickets in python to avoid N+1 queries
        name_lower = staff['name'].lower()
        active_count = sum(1 for note in active_notes if note and name_lower in note.lower())
        staff['active_tickets'] = active_count

        # Map to DB user_id if it exists
        staff['user_id'] = user_map.get(name_lower, None)

    return sorted(staff_list_copy, key=lambda x: x['active_tickets'], reverse=True)

def get_activity_chart_data():
    """
    Returns real ticket activity data for the last 7 calendar days.
    Generates a strict zero-filled timeline so the X-axis always renders all 7 days.
    - Received: tickets created (by created_at date).
    - Resolved: tickets resolved or completed (by updated_at date).
    """
    today = timezone.now().date()
    seven_days_ago = today - timedelta(days=6)  # inclusive of today = 7 days

    # 1. Build a strict list of the last 7 calendar dates
    date_range = [seven_days_ago + timedelta(days=i) for i in range(7)]
    labels = [d.strftime('%b %d') for d in date_range]  # e.g. "May 10", "May 11"

    # 2a. Tickets RECEIVED per day (all tickets created in the window)
    received_qs = (
        Ticket.objects.filter(created_at__date__gte=seven_days_ago)
        .annotate(day=TruncDate('created_at'))
        .values('day')
        .annotate(count=Count('id'))
        .order_by('day')
    )
    received_map = {entry['day']: entry['count'] for entry in received_qs}

    # 2b. Tickets RESOLVED/COMPLETED per day (by updated_at for broader coverage)
    resolved_qs = (
        Ticket.objects.filter(
            updated_at__date__gte=seven_days_ago,
            status__in=['RESOLVED', 'COMPLETED']
        )
        .annotate(day=TruncDate('updated_at'))
        .values('day')
        .annotate(count=Count('id'))
        .order_by('day')
    )
    resolved_map = {entry['day']: entry['count'] for entry in resolved_qs}

    # 3. Zero-fill: iterate through every day in the range
    received_data = [received_map.get(d, 0) for d in date_range]
    resolved_data = [resolved_map.get(d, 0) for d in date_range]

    return {'labels': labels, 'received': received_data, 'resolved': resolved_data}

def analytics_dashboard(request):
    return render(request, 'tickets/analytics.html')

def employee_directory(request):
    employees = User.objects.filter(role='MEMBER').order_by('first_name', 'last_name')

    category_map = {
        'MANAGEMENT': 'Management / Officers',
        'SYSTEM ADMIN': 'Management / Officers',
        'CCTV': 'CCTV Operations',
        'WEBSITE': 'Application Development',
        'SYSTEM DEV': 'Application Development',
        'NETWORK': 'Network Infrastructure',
        'INTERNET': 'Network Infrastructure',
        'ACCOUNT': 'Information Security & User Support',
        'SOFTWARE': 'Information Security & User Support',
        'SECURITY': 'Information Security & User Support',
        'GRAPHICS': 'Graphic Design & Multimedia',
        'MULTIMEDIA': 'Graphic Design & Multimedia',
        'PC MAINTENANCE': 'Computer Maintenance',
        'PRINTER': 'Computer Maintenance',
        'HARDWARE': 'Computer Maintenance',
        'SYSTEM TESTING': 'System Testing',
    }

    grouped_employees = {}
    for emp in employees:
        skills = [s.strip().upper() for s in emp.expertise.split(',') if s.strip()] if emp.expertise else []
        emp.expertise_list = skills
        primary = skills[0] if skills else 'OTHER'
        category = category_map.get(primary, 'Other / General')

        if category not in grouped_employees:
            grouped_employees[category] = []
        grouped_employees[category].append(emp)

    return render(request, 'tickets/employee_directory.html', {
        'grouped_employees': grouped_employees,
        'employees': employees,
    })

# ==========================================
# UTILITY VIEWS
# ==========================================

def backlog_view(request):
    audit_logs = TicketAuditLog.objects.all().order_by('-timestamp')
    context = {
        'audit_logs': audit_logs,
    }
    return render(request, 'tickets/audit_trail.html', context)

def move_from_backlog(request, ticket_id):
    if request.method == 'POST':
        ticket = get_object_or_404(Ticket, id=ticket_id)
        ticket.status = 'SCHEDULED'
        ticket._current_user = request.user
        ticket.save()
    return redirect('backlog')

def terms(request):
    from_source = request.GET.get('from', 'admin')
    return render(request, 'tickets/terms.html', {'from_source': from_source})

def privacy(request):
    from_source = request.GET.get('from', 'admin')
    return render(request, 'tickets/privacy.html', {'from_source': from_source})

def search_tickets(request):
    query = request.GET.get('q', '')
    results = []
    if query:
        results = Ticket.objects.filter(
            Q(ticket_number__icontains=query) | Q(title__icontains=query) | Q(first_name__icontains=query) | Q(
                last_name__icontains=query) | Q(school_name__icontains=query)).order_by('-created_at')

    return render(request, 'tickets/search_results.html', {'query': query, 'results': results})

@login_required
def update_ticket_ajax(request, ticket_id):
    if request.method == 'POST':
        try:
            ticket = get_object_or_404(Ticket, id=ticket_id)
            data = json.loads(request.body or '{}')
            is_admin_user = is_admin_or_superuser(request.user)
            has_changes = False

            new_status = data.get('status')
            if new_status:
                allowed_statuses = ADMIN_KANBAN_STATUSES if is_admin_user else EMPLOYEE_KANBAN_STATUSES
                if new_status not in allowed_statuses:
                    return JsonResponse({'success': False, 'message': 'That status is not available for your role.'}, status=403)

                if not is_admin_user and new_status == 'UNDER_REVIEW':
                    return JsonResponse({
                        'success': False,
                        'message': 'Employees must submit resolution notes and an attachment before a ticket can move to Under Review.'
                    }, status=400)

                if new_status == 'RESOLVED':
                    if not is_admin_user:
                        return JsonResponse({'success': False, 'message': 'Only admins can resolve tickets.'}, status=403)
                    if ticket.status != 'UNDER_REVIEW':
                        return JsonResponse({
                            'success': False,
                            'message': 'Only tickets currently under review can be marked as resolved.'
                        }, status=400)

                if new_status == 'COMPLETED':
                    return JsonResponse({
                        'success': False,
                        'message': 'Completed status is only available from the Documents tab.'
                    }, status=400)

                if ticket.status != new_status:
                    ticket.status = new_status
                    has_changes = True

            new_priority = data.get('priority')
            if new_priority is not None:
                if not is_admin_user:
                    return JsonResponse({'success': False, 'message': 'Only admins can change ticket priority.'}, status=403)
                valid_priorities = {choice[0] for choice in Ticket.PRIORITY_CHOICES}
                if new_priority not in valid_priorities:
                    return JsonResponse({'success': False, 'message': 'Invalid priority value.'}, status=400)
                if ticket.priority != new_priority:
                    ticket.priority = new_priority
                    has_changes = True

            if data.get('admin_notes') is not None:
                if not is_admin_user:
                    return JsonResponse({'success': False, 'message': 'Only admins can update admin notes.'}, status=403)
                new_admin_notes = data.get('admin_notes')
                if ticket.admin_notes != new_admin_notes:
                    ticket.admin_notes = new_admin_notes
                    has_changes = True

            if has_changes:
                ticket._current_user = request.user
                ticket.save()
            return JsonResponse({'success': True, 'message': 'Ticket updated successfully.'})
        except json.JSONDecodeError:
            return JsonResponse({'success': False, 'message': 'Invalid request payload.'}, status=400)
        except Exception as e:
            return JsonResponse({'success': False, 'message': str(e)}, status=400)
    return JsonResponse({'success': False, 'message': 'Invalid request method.'}, status=405)




@login_required
def my_tickets(request):
    user_name = f"{request.user.first_name} {request.user.last_name}".strip()

    pending_acceptance_tickets = Ticket.objects.filter(
        admin_notes__icontains=user_name,
        status='PENDING_ACCEPTANCE'
    ).order_by('-created_at')

    assigned_tickets = Ticket.objects.filter(
        admin_notes__icontains=user_name
    ).exclude(status__in=['RESOLVED', 'PENDING_ACCEPTANCE', 'COMPLETED']).order_by('-created_at')

    resolved_tickets = Ticket.objects.filter(
        admin_notes__icontains=user_name,
        status__in=['RESOLVED', 'COMPLETED']
    ).order_by('-actual_completion_date', '-updated_at')

    context = {
        'pending_acceptance_tickets': pending_acceptance_tickets,
        'assigned_tickets': assigned_tickets,
        'resolved_tickets': resolved_tickets
    }
    return render(request, 'tickets/my_tickets.html', context)

def employee_receipt_view(request, ticket_id):
    is_employee = request.user.is_authenticated and getattr(request.user, 'role', '') == 'MEMBER' and not request.user.is_superuser
    is_admin = request.user.is_authenticated and (getattr(request.user, 'role', '') == 'ADMIN' or request.user.is_superuser)
    is_school = request.session.get('is_school_authenticated', False)
    
    if not (is_employee or is_school or is_admin):
        from django.contrib import messages
        messages.error(request, 'You do not have permission to access this document.')
        return redirect('dashboard' if request.user.is_authenticated else 'school_dashboard')
        
    ticket = get_object_or_404(Ticket, id=ticket_id)
    
    if is_school and ticket.school_name != request.session.get('school_name'):
        from django.contrib import messages
        messages.error(request, 'You do not have permission to access this document.')
        return redirect('school_dashboard')

    return render(request, 'tickets/print_jrf.html', {'ticket': ticket})

def school_print_ticket(request, ticket_id):
    if not request.session.get('is_school_authenticated'):
        return redirect('school_login')
    
    school_name = request.session.get('school_name')
    ticket = get_object_or_404(Ticket, id=ticket_id, school_name=school_name)

    return render(request, 'tickets/print_receipt.html', {
        'ticket': ticket,
    })

@login_required
def employee_ticket_review(request, ticket_id):
    ticket = get_object_or_404(Ticket, id=ticket_id)
    return render(request, 'tickets/employee_ticket_review.html', {'ticket': ticket})

@login_required
def accept_assignment(request, ticket_id):
    if request.method == 'POST':
        ticket = get_object_or_404(Ticket, id=ticket_id)
        ticket.status = 'SCHEDULED'
        ticket._current_user = request.user
        ticket.save()

        is_ajax = request.headers.get(
            'X-Requested-With') == 'XMLHttpRequest' or 'application/json' in request.headers.get('Accept', '')
        if is_ajax:
            return JsonResponse({'success': True, 'message': 'Ticket accepted successfully.'})

    return redirect('my_tickets')

@login_required
def decline_assignment(request, ticket_id):
    if request.method == 'POST':
        ticket = get_object_or_404(Ticket, id=ticket_id)
        user_name = f"{request.user.first_name} {request.user.last_name}".strip()

        if ticket.admin_notes and 'Assigned to:' in ticket.admin_notes:
            lines = ticket.admin_notes.split('\n')
            new_lines = []
            for line in lines:
                if 'Assigned to:' in line:
                    names_str = line.replace('Assigned to:', '').strip()
                    names = [n.strip() for n in names_str.split(',') if n.strip()]
                    if user_name in names:
                        names.remove(user_name)
                    if not names:
                        new_lines.append("Assigned to: Unassigned")
                    else:
                        new_lines.append(f"Assigned to: {', '.join(names)}")
                else:
                    new_lines.append(line)
            ticket.admin_notes = '\n'.join(new_lines)

        reason = request.POST.get('decline_reason', '').strip()
        if reason:
            decline_note = f"\n[Declined by {user_name}] Reason: {reason}"
            if ticket.admin_notes:
                ticket.admin_notes += decline_note
            else:
                ticket.admin_notes = decline_note

        ticket.status = 'PENDING'
        ticket._current_user = request.user
        ticket.save()

        is_ajax = request.headers.get(
            'X-Requested-With') == 'XMLHttpRequest' or 'application/json' in request.headers.get('Accept', '')
        if is_ajax:
            return JsonResponse({'success': True, 'message': 'Ticket declined and returned to Admin queue.'})

    return redirect('my_tickets')

@user_passes_test(is_admin_or_superuser, login_url='dashboard')
def resolve_assignment(request, ticket_id):
    if request.method == 'POST':
        ticket = get_object_or_404(Ticket, id=ticket_id)
        if ticket.status != 'UNDER_REVIEW':
            messages.error(request, 'Only tickets under review can be resolved.')
            return redirect('documents')

        feedback = request.POST.get('admin_feedback', '').strip()
        if feedback:
            # Preserve the assignment line if it exists
            assigned_line = ""
            if ticket.admin_notes:
                for line in ticket.admin_notes.split('\n'):
                    if line.startswith('Assigned to:'):
                        assigned_line = line
                        break
            
            if assigned_line:
                ticket.admin_notes = f"{assigned_line}\n{feedback}"
            else:
                ticket.admin_notes = feedback

        ticket.status = 'RESOLVED'
        ticket._current_user = request.user
        ticket.save()
    return redirect('documents')

@login_required
def unresolve_assignment(request, ticket_id):
    if request.method == 'POST':
        ticket = get_object_or_404(Ticket, id=ticket_id)
        reason = request.POST.get('reason', '').strip()
        unresolved_attachment = request.FILES.get('unresolved_attachment')

        if reason:
            timestamp = timezone.now().strftime("%Y-%m-%d %H:%M:%S")
            employee_label = request.user.username or f"{request.user.first_name} {request.user.last_name}".strip() or 'unknown'
            reason_text = f"[{timestamp}] Employee {employee_label} marked as Unresolved: {reason}"
            if ticket.admin_notes:
                ticket.admin_notes += f"\n{reason_text}"
            else:
                ticket.admin_notes = reason_text

        if unresolved_attachment:
            ticket.resolution_attachment = unresolved_attachment

        ticket.status = 'UNRESOLVED'
        ticket._current_user = request.user
        ticket.save()
    return redirect('my_tickets')

@login_required
def submit_for_review(request, ticket_id):
    if request.method == 'POST':
        ticket = get_object_or_404(Ticket, id=ticket_id)
        if is_admin_or_superuser(request.user):
            message = 'Only employees can submit tickets for review.'
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({'success': False, 'message': message}, status=403)
            messages.error(request, message)
            return redirect('employee_ticket_review', ticket_id=ticket.id)

        if ticket.status not in ['SCHEDULED', 'IN_PROGRESS', 'UNRESOLVED']:
            message = 'Only scheduled, in-progress, or unresolved tickets can be submitted for review.'
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({'success': False, 'message': message}, status=400)
            messages.error(request, message)
            return redirect('employee_ticket_review', ticket_id=ticket.id)

        form = SubmitForReviewForm(request.POST, request.FILES)
        if not form.is_valid():
            message = 'Resolution notes and an attachment are required before submitting for review.'
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({'success': False, 'message': message, 'errors': form.errors}, status=400)
            messages.error(request, message)
            return redirect('employee_ticket_review', ticket_id=ticket.id)

        ticket.resolution_notes = form.cleaned_data['resolution_notes']
        ticket.resolution_attachment = form.cleaned_data['resolution_attachment']

        # Capture client signature (Base64 from canvas pad)
        client_sig = request.POST.get('client_signature', '').strip()
        if client_sig:
            ticket.client_signature = client_sig

        ticket.status = 'UNDER_REVIEW'
        ticket._current_user = request.user
        ticket.save()

        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({
                'success': True,
                'message': f'Ticket {ticket.ticket_number} submitted for QA review.',
                'ticket': {
                    'id': ticket.id,
                    'status': ticket.status,
                    'resolution_notes': ticket.resolution_notes,
                    'resolution_attachment_url': ticket.resolution_attachment.url if ticket.resolution_attachment else '',
                }
            })

        messages.success(request, f'Ticket {ticket.ticket_number} submitted for QA review.')
        return redirect('my_tickets')
    return redirect('employee_ticket_review', ticket_id=ticket_id)

# ==========================================
# SCHOOLS MANAGEMENT & DIRECTORY
# ==========================================

@user_passes_test(is_admin_or_superuser, login_url='dashboard')
def schools_management(request):
    schools = School.objects.all().order_by('name')
    account_requests = SchoolAccountRequest.objects.filter(status='PENDING').order_by('-request_date')

    context = {
        'schools': schools,
        'account_requests': account_requests,
    }
    return render(request, 'tickets/schools_directory.html', context)


@user_passes_test(is_admin_or_superuser, login_url='dashboard')
def admin_force_reset_password(request, school_id):
    """Emergency fallback — Admin manually resets a school's password without OTP."""
    if request.method == 'POST':
        school = get_object_or_404(School, id=school_id)
        new_password = request.POST.get('new_password', '').strip()

        if not new_password or len(new_password) < 8:
            messages.error(request, "Password must be at least 8 characters long.")
            return redirect('schools_management')

        school.set_password(new_password)
        school.save()

        messages.success(request, f"Password for '{school.name}' has been force-reset successfully.")
    return redirect('schools_management')

def forgot_password(request):
    """Step 1: User submits email → OTP is generated and emailed."""
    from_source = request.session.get('forgot_password_from')
    if request.method == 'GET':
        from_source = request.GET.get('from', 'school')
        request.session['forgot_password_from'] = from_source
    else:
        if not from_source:
            from_source = 'school'

    if request.method == 'POST':
        email = request.POST.get('email', '').strip().lower()

        if not email:
            return render(request, 'tickets/forgot_password.html', {
                'error': 'Please enter your email address.',
                'from_source': from_source,
            })

        # Look up school or user (Admin/Employee)
        school = School.objects.filter(ict_email__iexact=email).first()
        user = User.objects.filter(email__iexact=email).first() if not school else None

        if school or user:
            # Invalidate any previous unused OTPs
            if school:
                PasswordResetOTP.objects.filter(school=school, is_used=False).update(is_used=True)
            else:
                PasswordResetOTP.objects.filter(user=user, is_used=False).update(is_used=True)

            # Generate and save new OTP
            code = PasswordResetOTP.generate_code()
            otp = PasswordResetOTP(school=school, user=user, code=code)
            otp.save()

            # Send email with OTP
            try:
                from django.core.mail import send_mail
                send_mail(
                    subject='ICT Helpdesk — Password Reset Code',
                    message=(
                        f'Your password reset verification code is: {code}\n\n'
                        f'This code will expire in 15 minutes.\n\n'
                        f'If you did not request this, please ignore this email.\n\n'
                        f'— DepEd Division of Valenzuela, ICT Unit'
                    ),
                    from_email=None,  # Uses DEFAULT_FROM_EMAIL from settings
                    recipient_list=[email],
                    fail_silently=False,
                )
            except Exception as e:
                print(f"[OTP Email Error] {e}")
                # Still proceed — in dev/demo the OTP is in the DB for testing

        # Always show the same success message regardless of whether email was found
        # This prevents attackers from enumerating which emails are registered
        request.session['otp_email'] = email
        return render(request, 'tickets/forgot_password.html', {
            'email_sent': True,
            'email': email,
            'from_source': from_source,
        })

    return render(request, 'tickets/forgot_password.html', {
        'from_source': from_source,
    })


def verify_otp(request):
    """Step 2: User enters the 6-digit code from their email."""
    email = request.session.get('otp_email')
    from_source = request.session.get('forgot_password_from', 'school')
    if not email:
        return redirect('forgot_password')

    if request.method == 'POST':
        code = request.POST.get('code', '').strip()

        if not code or len(code) != 6:
            return render(request, 'tickets/verify_otp.html', {
                'error': 'Please enter the 6-digit code.',
                'email': email,
                'from_source': from_source,
            })

        # Find the school or user and matching OTP
        school = School.objects.filter(ict_email__iexact=email).first()
        user = User.objects.filter(email__iexact=email).first() if not school else None

        if school or user:
            if school:
                otp = PasswordResetOTP.objects.filter(
                    school=school, code=code, is_used=False
                ).order_by('-created_at').first()
            else:
                otp = PasswordResetOTP.objects.filter(
                    user=user, code=code, is_used=False
                ).order_by('-created_at').first()

            if otp and otp.is_valid:
                # Mark OTP as used and store verified school/user in session
                otp.is_used = True
                otp.save()
                if school:
                    request.session['otp_verified_school_id'] = school.id
                else:
                    request.session['otp_verified_user_id'] = user.id
                return redirect('reset_password_confirm')
            elif otp and otp.is_expired:
                return render(request, 'tickets/verify_otp.html', {
                    'error': 'This code has expired. Please request a new one.',
                    'email': email,
                    'from_source': from_source,
                })

        # Generic error for invalid code
        return render(request, 'tickets/verify_otp.html', {
            'error': 'Invalid verification code. Please try again.',
            'email': email,
            'from_source': from_source,
        })

    return render(request, 'tickets/verify_otp.html', {
        'email': email,
        'from_source': from_source,
    })


def reset_password_confirm(request):
    """Step 3: User sets a new password after OTP verification."""
    school_id = request.session.get('otp_verified_school_id')
    user_id = request.session.get('otp_verified_user_id')
    from_source = request.session.get('forgot_password_from', 'school')

    if not school_id and not user_id:
        return redirect('forgot_password')

    if school_id:
        obj = get_object_or_404(School, id=school_id)
        display_name = obj.name
    else:
        obj = get_object_or_404(User, id=user_id)
        display_name = obj.get_full_name() or obj.username

    if request.method == 'POST':
        new_password = request.POST.get('new_password', '').strip()
        confirm_password = request.POST.get('confirm_password', '').strip()

        if not new_password or len(new_password) < 8:
            return render(request, 'tickets/reset_password_confirm.html', {
                'error': 'Password must be at least 8 characters long.',
                'school_name': display_name,
                'from_source': from_source,
            })

        if new_password != confirm_password:
            return render(request, 'tickets/reset_password_confirm.html', {
                'error': 'Passwords do not match.',
                'school_name': display_name,
                'from_source': from_source,
            })

        # Set the new password
        obj.set_password(new_password)
        obj.save()

        # Clean up session
        if school_id:
            del request.session['otp_verified_school_id']
        else:
            del request.session['otp_verified_user_id']

        if 'otp_email' in request.session:
            del request.session['otp_email']
        if 'forgot_password_from' in request.session:
            del request.session['forgot_password_from']

        return render(request, 'tickets/reset_password_confirm.html', {
            'success': True,
            'from_source': from_source,
        })

    return render(request, 'tickets/reset_password_confirm.html', {
        'school_name': display_name,
        'from_source': from_source,
    })


# ==========================================
# VETTED ACCOUNT REQUEST SYSTEM
# ==========================================

def request_access(request):
    """Public view — schools can request access to the ticketing system."""
    schools = School.objects.all().order_by('name')

    if request.method == 'POST':
        school_id = request.POST.get('school', '').strip()
        ict_name = request.POST.get('ict_name', '').strip()
        email = request.POST.get('email', '').strip()
        contact_number = request.POST.get('contact_number', '').strip()

        # Validate required fields
        if not all([school_id, ict_name, email, contact_number]):
            return render(request, 'tickets/request_access.html', {
                'error': 'All required fields must be filled out.',
                'schools': schools,
                'form_data': request.POST,
            })

        # Validate PH mobile number format
        import re
        if not re.fullmatch(r'09\d{9}', contact_number):
            return render(request, 'tickets/request_access.html', {
                'error': 'Please enter a valid 11-digit Philippine mobile number starting with 09 (e.g., 09123456789).',
                'schools': schools,
                'form_data': request.POST,
            })

        # Validate selected school exists
        try:
            school = School.objects.get(id=school_id)
        except School.DoesNotExist:
            return render(request, 'tickets/request_access.html', {
                'error': 'Invalid school selection. Please select a valid school.',
                'schools': schools,
                'form_data': request.POST,
            })

        if is_email_already_associated(email):
            return render(request, 'tickets/request_access.html', {
                'error': 'This email is already associated with an account',
                'schools': schools,
                'form_data': request.POST,
            })

        normalized_email = email.lower()
        allowed_emails = ['admin@test.com', 'employee@test.com']
        if not normalized_email.endswith('@deped.gov.ph') and normalized_email not in allowed_emails:
            return render(request, 'tickets/request_access.html', {
                'error': 'Only official @deped.gov.ph email addresses are permitted.',
                'schools': schools,
                'form_data': request.POST,
            })

        # Check for duplicate pending request
        if SchoolAccountRequest.objects.filter(school=school, status='PENDING').exists():
            return render(request, 'tickets/request_access.html', {
                'error': f'An access request for "{school.name}" is already pending review. Please wait for the ICT Admin to process it.',
                'schools': schools,
                'form_data': request.POST,
            })

        # Create the request — domain_verified is auto-set in model.save()
        SchoolAccountRequest.objects.create(
            school=school,
            ict_name=ict_name,
            email=email,
            contact_number=contact_number,
        )

        return render(request, 'tickets/request_access.html', {
            'success': True,
            'school_name': school.name,
            'is_deped_email': email.strip().lower().endswith('@deped.gov.ph'),
        })

    return render(request, 'tickets/request_access.html', {'schools': schools})


@user_passes_test(is_admin_or_superuser, login_url='dashboard')
def approve_account_request(request, request_id):
    """Admin approves — updates the linked School record with ICT details and sets default password."""
    if request.method == 'POST':
        account_request = get_object_or_404(SchoolAccountRequest, id=request_id, status='PENDING')
        school = account_request.school

        if is_email_already_associated(
            account_request.email,
            exclude_school_id=school.id,
            exclude_account_request_id=account_request.id
        ):
            messages.error(request, "This email is already associated with an account")
            return redirect('schools_management')

        # Split ict_name into first/last for the School record
        name_parts = account_request.ict_name.strip().split(' ', 1)
        first_name = name_parts[0]
        last_name = name_parts[1] if len(name_parts) > 1 else ''

        # Update the existing School record with provided ICT details
        school.ict_first_name = first_name
        school.ict_last_name = last_name
        school.ict_contact_number = account_request.contact_number
        school.ict_email = account_request.email
        school.set_password('DepEd123!')
        school.save()

        # Remove the request
        account_request.delete()

        messages.success(request, f"Access approved for '{school.name}'. ICT personnel details updated and password set to: DepEd123!")
    return redirect('schools_management')


@user_passes_test(is_admin_or_superuser, login_url='dashboard')
def reject_account_request(request, request_id):
    """Admin rejects an access request — simply deletes it."""
    if request.method == 'POST':
        account_request = get_object_or_404(SchoolAccountRequest, id=request_id, status='PENDING')
        school_name = account_request.school.name
        account_request.delete()
        messages.success(request, f"Access request for '{school_name}' has been rejected and removed.")
    return redirect('schools_management')


@login_required
def delete_user_account(request):
    if request.method != 'POST':
        return redirect('settings')

    current_user = request.user
    logout(request)
    current_user.delete()
    return redirect('login')


def delete_school_account(request):
    if request.method != 'POST':
        return redirect('school_dashboard')
    if not request.session.get('is_school_authenticated'):
        return redirect('school_login')

    school_name = request.session.get('school_name')
    school = get_object_or_404(School, name=school_name)

    # Clear ICT personnel details — keep the School record intact
    school.ict_first_name = None
    school.ict_last_name = None
    school.ict_contact_number = None
    school.ict_email = None

    # Deactivate login by setting an unusable password hash
    from django.contrib.auth.hashers import make_password
    school.password = make_password(None)
    school.save()

    # Terminate the session
    request.session.flush()

    messages.success(request, "Your ICT personnel account has been successfully removed. You may re-register through the Request Access flow.")
    return redirect('school_login')


@user_passes_test(is_admin_or_superuser, login_url='dashboard')
def admin_delete_school(request, school_id):
    if request.method != 'POST':
        return redirect('schools_management')

    school = get_object_or_404(School, id=school_id)
    school_name = school.name

    # Clear ICT personnel details — keep the School record intact
    school.ict_first_name = None
    school.ict_last_name = None
    school.ict_contact_number = None
    school.ict_email = None

    # Deactivate login by setting an unusable password hash
    from django.contrib.auth.hashers import make_password
    school.password = make_password(None)
    school.save()

    messages.success(request, f"ICT personnel account for '{school_name}' has been removed. The school record remains in the system.")
    return redirect('schools_management')


# ==========================================
# SETTINGS
# ==========================================

def settings_view(request):
    return render(request, 'tickets/settings.html')


# ==========================================
# PERFORMANCE REVIEW SYSTEM (Phase 4)
# ==========================================

@user_passes_test(is_admin_or_superuser, login_url='dashboard')
def submit_performance_review(request, ticket_id):
    """Admin/Super Admin submits a performance review for the employee linked to a ticket."""
    ticket = get_object_or_404(Ticket, id=ticket_id)

    if request.method == 'POST':
        quality = int(request.POST.get('quality', 3))
        efficiency = int(request.POST.get('efficiency', 3))
        timeliness = int(request.POST.get('timeliness', 3))
        notes = request.POST.get('notes', '').strip()

        # Determine employee from admin_notes "Assigned to:" line
        employee = None
        if ticket.admin_notes and 'Assigned to:' in ticket.admin_notes:
            for line in ticket.admin_notes.split('\n'):
                if 'Assigned to:' in line:
                    names_str = line.replace('Assigned to:', '').strip()
                    if names_str and names_str != 'Unassigned':
                        first_name = names_str.split(',')[0].strip()
                        # Try to find the user in the DB
                        for u in User.objects.all():
                            full_name = f"{u.first_name} {u.last_name}".strip()
                            if full_name.lower() == first_name.lower():
                                employee = u
                                break
                    break

        if not employee:
            messages.error(request, "Could not identify the employee for this ticket.")
            return redirect('documents')

        # Calculate new scores using rolling average
        if employee.total_reviews > 0:
            employee.quality_score = (employee.quality_score + quality) / 2
            employee.efficiency_score = (employee.efficiency_score + efficiency) / 2
            employee.timeliness_score = (employee.timeliness_score + timeliness) / 2
        else:
            employee.quality_score = float(quality)
            employee.efficiency_score = float(efficiency)
            employee.timeliness_score = float(timeliness)

        employee.overall_rating = calculate_overall_rating(
            int(round(employee.quality_score)),
            int(round(employee.efficiency_score)),
            int(round(employee.timeliness_score))
        )
        employee.total_reviews += 1
        employee.save()

        # Create the review record
        PerformanceReview.objects.create(
            ticket=ticket,
            reviewed_by=request.user,
            employee=employee,
            quality=quality,
            efficiency=efficiency,
            timeliness=timeliness,
            notes=notes,
        )

        # Mark ticket as COMPLETED
        ticket.status = 'COMPLETED'
        ticket._current_user = request.user
        ticket.save()

        messages.success(request, f"Performance review submitted and ticket marked as Complete for {employee.get_full_name()}.")
        return redirect('documents')

    return redirect('documents')


# ==========================================
# EMPLOYEE PROFILE SYSTEM (Phase 5)
# ==========================================

@login_required
def employee_profile(request, user_id):
    """View an employee's profile — accessible by Admin, Super Admin, and the employee themselves."""
    profile_user = get_object_or_404(User, id=user_id)

    # Access control
    is_self = request.user.id == profile_user.id
    is_admin_user = is_admin_or_superuser(request.user)
    if not (is_self or is_admin_user):
        messages.error(request, "You do not have permission to view this profile.")
        return redirect('dashboard')

    # Get ALL resolved/completed tickets for this employee (full task history)
    user_full_name = f"{profile_user.first_name} {profile_user.last_name}".strip()
    task_history = Ticket.objects.filter(
        admin_notes__icontains=user_full_name,
        status__in=['RESOLVED', 'COMPLETED']
    ).order_by('-actual_completion_date', '-updated_at')

    # Live task count (use stored value, fallback to query count)
    total_tasks = profile_user.total_tasks_done or task_history.count()

    # Get performance reviews
    reviews = PerformanceReview.objects.filter(employee=profile_user).order_by('-created_at')[:10]

    # Radar chart data — scores are 0-5 in DB, convert to 0-100 for chart
    import json
    radar_data = json.dumps({
        'quality': round(profile_user.quality_score * 20, 1),
        'efficiency': round(profile_user.efficiency_score * 20, 1),
        'timeliness': round(profile_user.timeliness_score * 20, 1),
    })

    context = {
        'profile_user': profile_user,
        'task_history': task_history,
        'total_tasks': total_tasks,
        'reviews': reviews,
        'is_admin_user': is_admin_user,
        'radar_data': radar_data,
    }
    return render(request, 'tickets/employee_profile.html', context)


@user_passes_test(is_admin_or_superuser, login_url='dashboard')
def edit_employee_profile(request, user_id):
    """Admin/Super Admin can edit an employee's profile."""
    profile_user = get_object_or_404(User, id=user_id)

    if request.method == 'POST':
        profile_user.first_name = request.POST.get('first_name', profile_user.first_name)
        profile_user.last_name = request.POST.get('last_name', profile_user.last_name)
        profile_user.email = request.POST.get('email', profile_user.email)
        profile_user.role = request.POST.get('role', profile_user.role)
        profile_user.expertise = request.POST.get('expertise', profile_user.expertise)
        profile_user.bio = request.POST.get('bio', '')

        if request.FILES.get('profile_picture'):
            profile_user.profile_picture = request.FILES['profile_picture']

        profile_user.save()
        messages.success(request, f"Profile for {profile_user.get_full_name()} updated successfully.")
        return redirect('employee_profile', user_id=profile_user.id)

    context = {
        'profile_user': profile_user,
    }
    return render(request, 'tickets/edit_employee_profile.html', context)


# ==========================================
# OMR SCANNER SYSTEM (Phase 6)
# ==========================================

@login_required
@user_passes_test(is_admin_or_superuser, login_url='dashboard')
def mobile_scanner(request):
    """Render the mobile OMR scanner page (Admin only)."""
    return render(request, 'tickets/scanner.html')


@login_required
@user_passes_test(is_admin_or_superuser, login_url='dashboard')
def api_process_scan(request):
    """
    API endpoint that receives a camera image, sends it to Gemini API,
    and returns the extracted ticket ID and scores for admin verification.
    """
    if request.method != 'POST':
        return JsonResponse({'error': 'POST required.'}, status=405)

    image_data = request.POST.get('image')
    if not image_data:
        return JsonResponse({'error': 'No image provided.'})

    from .omr_engine import analyze_jrf_image
    extracted_data = analyze_jrf_image(image_data)
    return JsonResponse(extracted_data)


@login_required
@user_passes_test(is_admin_or_superuser, login_url='dashboard')
def api_save_review(request):
    """
    API endpoint that receives final, verified scores and saves them to the DB.
    """
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': 'POST required.'}, status=405)

    ticket_id_raw = request.POST.get('ticket_id', '').strip()
    if not ticket_id_raw:
        return JsonResponse({'success': False, 'message': 'Ticket ID is required.'})

    # Support both numeric IDs and ticket_number formats (e.g. TKT-2026-0001)
    # Normalize: collapse extra spaces Gemini may insert around hyphens
    ticket_id_normalized = ' '.join(ticket_id_raw.split())

    ticket = None
    if ticket_id_normalized.upper().startswith('TKT-'):
        # 1. Try exact ticket_number match (case-insensitive)
        ticket = Ticket.objects.filter(ticket_number__iexact=ticket_id_normalized).first()

        # 2. Fuzzy fallback: match on the trailing sequence number only
        #    (handles AI returning 'TKT-2026-1' vs 'TKT-2026-0001')
        if not ticket:
            suffix = ticket_id_normalized.split('-')[-1].lstrip('0') or '0'
            ticket = Ticket.objects.filter(ticket_number__iendswith=suffix).first()

    if not ticket:
        # 3. Fallback: try parsing as a numeric primary-key ID
        try:
            ticket = Ticket.objects.get(id=int(ticket_id_normalized))
        except (Ticket.DoesNotExist, ValueError):
            pass

    if not ticket:
        return JsonResponse({'success': False, 'message': f'Ticket "{ticket_id_raw}" not found. Please verify the Ticket ID and try again.'})

    if ticket.status == 'COMPLETED':
        return JsonResponse({'success': False, 'message': 'This ticket has already been completed.'})

    quality = int(request.POST.get('quality', 3))
    efficiency = int(request.POST.get('efficiency', 3))
    timeliness = int(request.POST.get('timeliness', 3))

    # Validate score range
    quality = max(1, min(5, quality))
    efficiency = max(1, min(5, efficiency))
    timeliness = max(1, min(5, timeliness))

    # Find the assigned employee
    employee = ticket.assignee
    if not employee and ticket.admin_notes:
        for line in ticket.admin_notes.split('\n'):
            if 'Assigned to:' in line:
                names_str = line.replace('Assigned to:', '').strip()
                if names_str and names_str != 'Unassigned':
                    first_name = names_str.split(',')[0].strip()
                    for u in User.objects.all():
                        full_name = f"{u.first_name} {u.last_name}".strip()
                        if full_name.lower() == first_name.lower():
                            employee = u
                            break
                break

    if not employee:
        return JsonResponse({'success': False, 'message': 'Could not identify the assigned employee for this ticket.'})

    # Update employee scores (rolling average)
    if employee.total_reviews > 0:
        employee.quality_score = (employee.quality_score + quality) / 2
        employee.efficiency_score = (employee.efficiency_score + efficiency) / 2
        employee.timeliness_score = (employee.timeliness_score + timeliness) / 2
    else:
        employee.quality_score = float(quality)
        employee.efficiency_score = float(efficiency)
        employee.timeliness_score = float(timeliness)

    employee.overall_rating = calculate_overall_rating(
        int(round(employee.quality_score)),
        int(round(employee.efficiency_score)),
        int(round(employee.timeliness_score))
    )
    employee.total_reviews += 1
    employee.save()

    # Create the review record
    PerformanceReview.objects.create(
        ticket=ticket,
        reviewed_by=request.user,
        employee=employee,
        quality=quality,
        efficiency=efficiency,
        timeliness=timeliness,
        notes=f"AI-Assisted OMR Scan verified by {request.user.get_full_name()}",
    )

    # Mark ticket as COMPLETED
    ticket.status = 'COMPLETED'
    ticket._current_user = request.user
    ticket.save()

    return JsonResponse({
        'success': True,
        'message': f'Performance review saved and ticket #{ticket.ticket_number} marked as Complete for {employee.get_full_name()}.'
    })


# ==========================================
# PASSWORD CHANGE SYSTEM
# ==========================================

@login_required
def change_password(request):
    """Standard password change form. Sets has_changed_password=True on success."""
    if request.method == 'POST':
        old_password = request.POST.get('old_password', '')
        new_password1 = request.POST.get('new_password1', '')
        new_password2 = request.POST.get('new_password2', '')

        if not request.user.check_password(old_password):
            messages.error(request, 'Your current password is incorrect.')
            return render(request, 'tickets/change_password.html')

        if not new_password1 or len(new_password1) < 8:
            messages.error(request, 'New password must be at least 8 characters long.')
            return render(request, 'tickets/change_password.html')

        if new_password1 != new_password2:
            messages.error(request, 'The two new passwords do not match.')
            return render(request, 'tickets/change_password.html')

        request.user.set_password(new_password1)
        request.user.has_changed_password = True
        request.user.save()

        # Keep the user logged in after password change
        update_session_auth_hash(request, request.user)

        messages.success(request, 'Your password has been updated successfully!')
        return redirect('dashboard')

    return render(request, 'tickets/change_password.html')


@login_required
def dismiss_password_change(request):
    """Lightweight AJAX view that flips has_changed_password to True so the banner goes away."""
    if request.method == 'POST':
        request.user.has_changed_password = True
        request.user.save(update_fields=['has_changed_password'])
        return JsonResponse({'success': True})
    return JsonResponse({'success': False, 'message': 'POST required.'}, status=405)
