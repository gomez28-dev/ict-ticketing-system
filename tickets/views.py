from .ml_service import predict_ticket_duration, recommend_staff, predict_risk, get_mapped_support_type
from django.utils import timezone
from .models import Ticket, School, TicketAuditLog, SchoolAccountRequest, PasswordResetOTP
from .forms import PublicTicketForm, SubmitForReviewForm
from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse
from django.urls import reverse
from django.db.models import Q
import json
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import user_passes_test, login_required
from django.contrib import messages

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
        password = request.POST.get('password')
        expertise = request.POST.get('expertise', '')

        username = email.split('@')[0] if email else f"{first_name.lower()}.{last_name.lower()}"

        if is_email_already_associated(email):
            error = "This email is already associated with an account"
        elif User.objects.filter(username=username).exists() or User.objects.filter(email=email).exists():
            error = "An employee with this email or username already exists."
        else:
            new_user = User.objects.create_user(
                username=username, email=email, password=password,
                first_name=first_name, last_name=last_name, role=role, expertise=expertise
            )
            if role == 'ADMIN':
                new_user.is_staff = True
                new_user.save()
            return redirect('teams')

    return render(request, 'tickets/add_employee.html', {'error': error})

# ==========================================
# AUTHENTICATION VIEWS
# ==========================================

def custom_login(request):
    if request.user.is_authenticated:
        return redirect('dashboard')

    if request.method == 'POST':
        email_input = request.POST.get('email', '').strip()

        if email_input == 'admin@test.com':
            user, created = User.objects.get_or_create(
                username='testadmin',
                defaults={'email': 'admin@test.com', 'first_name': 'Test', 'last_name': 'Admin', 'role': 'ADMIN',
                          'is_staff': True, 'is_superuser': False}
            )
            if created:
                user.set_password('AdminPass123!')
                user.save()

        elif email_input == 'employee@test.com':
            user, created = User.objects.get_or_create(
                username='testemployee',
                defaults={'email': 'employee@test.com', 'first_name': 'Test', 'last_name': 'Employee', 'role': 'MEMBER',
                          'is_staff': False, 'is_superuser': False}
            )
            if created:
                user.set_password('EmployeePass123!')
                user.save()
        else:
            user = User.objects.filter(is_superuser=True).first()
            if not user:
                user = User.objects.first()

        if user:
            login(request, user)
        return redirect('dashboard')

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
            if is_email_already_associated(new_ict_email, exclude_school_id=school.id):
                messages.error(request, "This email is already associated with an account")
                return redirect('school_dashboard')

            school.ict_first_name = request.POST.get('ict_first_name')
            school.ict_last_name = request.POST.get('ict_last_name')
            school.ict_contact_number = request.POST.get('ict_contact_number')
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
                ticket.predicted_hours = predict_ticket_duration(ticket.support_type, ticket.priority)
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
    tickets = Ticket.objects.all()
    context = {
        'tickets': tickets,
        'total_tickets': tickets.count(),
        'resolved_tickets': tickets.filter(status='RESOLVED').count(),
        'staff_data': get_staff_data(),
        'chart_labels': get_mock_chart_data()['labels'],
        'chart_received': get_mock_chart_data()['received'],
        'chart_resolved': get_mock_chart_data()['resolved'],
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
    return render(request, 'tickets/requests.html', {
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
    predicted_hours = predict_ticket_duration(ticket.support_type, ticket.priority)
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
        if mapped_type in normalized_expertise or 'ALL' in normalized_expertise or staff['name'].strip().lower() == 'test employee':
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
                from django.contrib import messages
                messages.error(request, "Scheduled End Time must be strictly after Start Time.")
                return redirect('ticket_triage', ticket_id=ticket.id)
            ticket.scheduled_end_time = scheduled_end_time_str

        assigned_staff_list = request.POST.getlist('assigned_staff')
        if not assigned_staff_list:
            assigned_staff_str = 'Unassigned'
            ticket.assignee = None
            ticket.status = 'PENDING'
        else:
            unique_staff = list(set(assigned_staff_list))
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
    staff_list = [
        {'id': 1, 'name': 'Noel E. Reyes', 'expertise': ['MANAGEMENT', 'SYSTEM ADMIN']},
        {'id': 2, 'name': 'Marvin M. Cruz', 'expertise': ['CCTV']},
        {'id': 3, 'name': 'Ariel C. Samosino', 'expertise': ['CCTV']},
        {'id': 4, 'name': 'Elison D. Carredo', 'expertise': ['CCTV']},
        {'id': 5, 'name': 'Rolando O. De Castro Jr.', 'expertise': ['CCTV']},
        {'id': 6, 'name': 'Edgar Manalansan', 'expertise': ['CCTV']},
        {'id': 7, 'name': 'Ariel Cariaga', 'expertise': ['CCTV']},
        {'id': 8, 'name': 'Ike Joseph P. Lumaad', 'expertise': ['WEBSITE', 'SYSTEM DEV']},
        {'id': 9, 'name': 'Niel Ian I. Pariñas', 'expertise': ['WEBSITE', 'SYSTEM DEV']},
        {'id': 10, 'name': 'Zandro S. Ocampo', 'expertise': ['NETWORK', 'INTERNET']},
        {'id': 11, 'name': 'Reagan James H. Tayag', 'expertise': ['NETWORK', 'INTERNET']},
        {'id': 12, 'name': 'Erickson J. Galvez', 'expertise': ['NETWORK', 'INTERNET']},
        {'id': 13, 'name': 'Edelfonso D. Orig I', 'expertise': ['NETWORK', 'INTERNET']},
        {'id': 14, 'name': 'Marbie A. Sumbe', 'expertise': ['NETWORK', 'INTERNET']},
        {'id': 15, 'name': 'Karenshene SD. Malvar', 'expertise': ['ACCOUNT', 'SOFTWARE', 'SECURITY']},
        {'id': 16, 'name': 'Allenn Raphael F. Gutierrez', 'expertise': ['ACCOUNT', 'SOFTWARE', 'SECURITY']},
        {'id': 17, 'name': 'Jona A. Siarot', 'expertise': ['GRAPHICS', 'MULTIMEDIA']},
        {'id': 18, 'name': 'Jerus L. De Jesus', 'expertise': ['GRAPHICS', 'MULTIMEDIA']},
        {'id': 19, 'name': 'Julian G. Uy', 'expertise': ['PC MAINTENANCE', 'PRINTER', 'HARDWARE']},
        {'id': 20, 'name': 'Mark Joseph C. Sotto', 'expertise': ['PC MAINTENANCE', 'PRINTER', 'HARDWARE']},
        {'id': 21, 'name': 'Sergio Paulo B. Leoncio', 'expertise': ['PC MAINTENANCE', 'PRINTER', 'HARDWARE']},
        {'id': 22, 'name': 'Aquilles S. Capili', 'expertise': ['PC MAINTENANCE', 'PRINTER', 'HARDWARE']},
        {'id': 23, 'name': 'Mark Anthony G. De Guzman', 'expertise': ['PC MAINTENANCE', 'PRINTER', 'HARDWARE']},
        {'id': 24, 'name': 'Raffy R. Del Rosario', 'expertise': ['PC MAINTENANCE', 'PRINTER', 'HARDWARE']},
        {'id': 25, 'name': 'Roel D. Tilo', 'expertise': ['PC MAINTENANCE', 'PRINTER', 'HARDWARE']},
        {'id': 26, 'name': 'Bernie L. De Jesus', 'expertise': ['PC MAINTENANCE', 'PRINTER', 'HARDWARE']},
        {'id': 27, 'name': 'Genesis De Leon Flores', 'expertise': ['PC MAINTENANCE', 'PRINTER', 'HARDWARE']},
        {'id': 28, 'name': 'Christian Angelo A. Navera', 'expertise': ['PC MAINTENANCE', 'PRINTER', 'HARDWARE']},
        {'id': 29, 'name': 'Alvin John Villaseñor', 'expertise': ['PC MAINTENANCE', 'PRINTER', 'HARDWARE']},
        {'id': 30, 'name': 'Test Employee', 'expertise': ['SYSTEM TESTING']},
    ]
    for staff in staff_list:
        active_count = Ticket.objects.filter(
            admin_notes__icontains=staff['name']
        ).exclude(status='RESOLVED').count()
        staff['active_tickets'] = active_count
    return sorted(staff_list, key=lambda x: x['active_tickets'], reverse=True)

def get_mock_chart_data():
    return {'labels': ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'],
            'received': [8, 12, 15, 9, 14, 5, 3], 'resolved': [6, 10, 18, 12, 11, 8, 4]}

def analytics_dashboard(request):
    return render(request, 'tickets/analytics.html')

def teams_view(request):
    staff_list = get_staff_data()
    
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
    
    grouped_staff = {}
    for staff in staff_list:
        primary_expertise = staff['expertise'][0] if staff['expertise'] else 'OTHER'
        category = category_map.get(primary_expertise, 'Other / General')
        
        if category not in grouped_staff:
            grouped_staff[category] = []
        grouped_staff[category].append(staff)
        
    return render(request, 'tickets/teams.html', {'grouped_staff': grouped_staff})

# ==========================================
# UTILITY VIEWS
# ==========================================

def backlog_view(request):
    audit_logs = TicketAuditLog.objects.all().order_by('-timestamp')
    context = {
        'audit_logs': audit_logs,
    }
    return render(request, 'tickets/backlog.html', context)

def move_from_backlog(request, ticket_id):
    if request.method == 'POST':
        ticket = get_object_or_404(Ticket, id=ticket_id)
        ticket.status = 'SCHEDULED'
        ticket._current_user = request.user
        ticket.save()
    return redirect('backlog')

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

def settings_view(request):
    return render(request, 'tickets/settings.html')

# ==========================================
# EMPLOYEE SPECIFIC VIEWS
# ==========================================

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
        status='RESOLVED'
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

    return render(request, 'tickets/employee_receipt.html', {'ticket': ticket})

def school_print_ticket(request, ticket_id):
    if not request.session.get('is_school_authenticated'):
        return redirect('school_login')
    
    school_name = request.session.get('school_name')
    ticket = get_object_or_404(Ticket, id=ticket_id, school_name=school_name)
    return render(request, 'tickets/school_print_ticket.html', {'ticket': ticket})

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
    return render(request, 'tickets/schools_management.html', context)


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
    if request.method == 'POST':
        email = request.POST.get('email', '').strip().lower()

        if not email:
            return render(request, 'tickets/forgot_password.html', {
                'error': 'Please enter your email address.',
            })

        # Look up school by ICT email — use generic message to prevent info disclosure
        school = School.objects.filter(ict_email__iexact=email).first()

        if school:
            # Invalidate any previous unused OTPs for this school
            PasswordResetOTP.objects.filter(school=school, is_used=False).update(is_used=True)

            # Generate and save new OTP
            code = PasswordResetOTP.generate_code()
            otp = PasswordResetOTP(school=school, code=code)
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
        })

    return render(request, 'tickets/forgot_password.html')


def verify_otp(request):
    """Step 2: User enters the 6-digit code from their email."""
    email = request.session.get('otp_email')
    if not email:
        return redirect('forgot_password')

    if request.method == 'POST':
        code = request.POST.get('code', '').strip()

        if not code or len(code) != 6:
            return render(request, 'tickets/verify_otp.html', {
                'error': 'Please enter the 6-digit code.',
                'email': email,
            })

        # Find the school and matching OTP
        school = School.objects.filter(ict_email__iexact=email).first()
        if school:
            otp = PasswordResetOTP.objects.filter(
                school=school, code=code, is_used=False
            ).order_by('-created_at').first()

            if otp and otp.is_valid:
                # Mark OTP as used and store verified school in session
                otp.is_used = True
                otp.save()
                request.session['otp_verified_school_id'] = school.id
                return redirect('reset_password_confirm')
            elif otp and otp.is_expired:
                return render(request, 'tickets/verify_otp.html', {
                    'error': 'This code has expired. Please request a new one.',
                    'email': email,
                })

        # Generic error for invalid code
        return render(request, 'tickets/verify_otp.html', {
            'error': 'Invalid verification code. Please try again.',
            'email': email,
        })

    return render(request, 'tickets/verify_otp.html', {'email': email})


def reset_password_confirm(request):
    """Step 3: User sets a new password after OTP verification."""
    school_id = request.session.get('otp_verified_school_id')
    if not school_id:
        return redirect('forgot_password')

    school = get_object_or_404(School, id=school_id)

    if request.method == 'POST':
        new_password = request.POST.get('new_password', '').strip()
        confirm_password = request.POST.get('confirm_password', '').strip()

        if not new_password or len(new_password) < 8:
            return render(request, 'tickets/reset_password_confirm.html', {
                'error': 'Password must be at least 8 characters long.',
                'school_name': school.name,
            })

        if new_password != confirm_password:
            return render(request, 'tickets/reset_password_confirm.html', {
                'error': 'Passwords do not match.',
                'school_name': school.name,
            })

        # Set the new password
        school.set_password(new_password)
        school.save()

        # Clean up session
        del request.session['otp_verified_school_id']
        if 'otp_email' in request.session:
            del request.session['otp_email']

        return render(request, 'tickets/reset_password_confirm.html', {
            'success': True,
        })

    return render(request, 'tickets/reset_password_confirm.html', {
        'school_name': school.name,
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
    request.session.flush()
    school.delete()
    return redirect('school_login')


@user_passes_test(is_admin_or_superuser, login_url='dashboard')
def admin_delete_school(request, school_id):
    if request.method != 'POST':
        return redirect('schools_management')

    school = get_object_or_404(School, id=school_id)
    school_name = school.name
    school.delete()
    messages.success(request, f"School account '{school_name}' has been deleted.")
    return redirect('schools_management')
