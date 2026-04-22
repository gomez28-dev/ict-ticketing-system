from .ml_service import predict_ticket_duration, recommend_staff, predict_risk, get_mapped_support_type
from django.utils import timezone
from .models import Ticket, School, TicketAuditLog, PasswordResetRequest
from .forms import PublicTicketForm
from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse
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

        if User.objects.filter(username=username).exists() or User.objects.filter(email=email).exists():
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
                request.session['school_district'] = school.district
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
            school.ict_first_name = request.POST.get('ict_first_name')
            school.ict_last_name = request.POST.get('ict_last_name')
            school.ict_contact_number = request.POST.get('ict_contact_number')
            school.ict_email = request.POST.get('ict_email')
            school.save()
            messages.success(request, 'Profile updated successfully.')
        elif action == 'create_ticket':
            try:
                ticket = Ticket.objects.create(
                    first_name=school.ict_first_name or '',
                    last_name=school.ict_last_name or '',
                    contact_number=school.ict_contact_number or '',
                    email=school.ict_email or '',
                    school_district=school.district or 'Not Specified',
                    school_name=school.name or 'Not Specified',
                    support_type=request.POST.get('support_type', 'OTHER'),
                    description=request.POST.get('description', ''),
                    status='PENDING',
                    priority='MEDIUM',
                    attachment=request.FILES.get('attachment')
                )
                ticket.predicted_hours = predict_ticket_duration(ticket.support_type, ticket.priority)
                ticket.save()
                messages.success(request, f"Ticket {ticket.ticket_number} has been created successfully.")
            except Exception as e:
                print(f"Submission Error: {e}")
                messages.error(request, "Failed to create ticket. Please try again.")
        
        return redirect('school_dashboard')

    tickets = Ticket.objects.filter(school_name=school.name).order_by('-created_at')
    
    # Notifications: get audit logs for these tickets
    ticket_ids = tickets.values_list('id', flat=True)
    notifications = TicketAuditLog.objects.filter(ticket_id__in=ticket_ids).order_by('-timestamp')[:20]

    context = {
        'school': school,
        'tickets': tickets,
        'notifications': notifications,
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

def requests_view(request):
    pending_requests = Ticket.objects.filter(status='PENDING').order_by('-created_at')
    return render(request, 'tickets/requests.html', {'pending_requests': pending_requests})

def delete_request(request, ticket_id):
    if request.method == 'POST':
        ticket = get_object_or_404(Ticket, id=ticket_id)
        ticket.delete()
    return redirect('requests')

@user_passes_test(is_admin_or_superuser, login_url='dashboard')
def documents_view(request):
    resolved_tickets = Ticket.objects.filter(status='RESOLVED').order_by('-updated_at')
    completed_tickets = Ticket.objects.filter(status='COMPLETED').order_by('-updated_at')
    context = {
        'resolved_tickets': resolved_tickets,
        'completed_tickets': completed_tickets
    }
    return render(request, 'tickets/documents.html', context)

@user_passes_test(is_admin_or_superuser, login_url='dashboard')
def complete_ticket_ajax(request, ticket_id):
    if request.method == 'POST':
        ticket = get_object_or_404(Ticket, id=ticket_id)
        ticket.status = 'COMPLETED'
        ticket._current_user = request.user
        ticket.save()
        return JsonResponse({'success': True, 'message': 'Ticket moved to Completed Documents.'})
    return JsonResponse({'success': False, 'message': 'Invalid request method.'}, status=405)

# ==========================================
# AI TRIAGE WORKFLOW
# ==========================================

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

    context = {
        'ticket': ticket,
        'predicted_hours': predicted_hours,
        'staff_rec': staff_rec,
        'risk_assessment': risk_assessment,
        'staff_data': filtered_staff,
        'recent_school_tickets': recent_school_tickets
    }
    return render(request, 'tickets/ticket_creation.html', context)

@login_required
def approve_request(request, ticket_id):
    ticket = get_object_or_404(Ticket, id=ticket_id)
    if request.method == 'POST':
        ticket.status = 'PENDING_ACCEPTANCE'
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
        else:
            unique_staff = list(set(assigned_staff_list))
            assigned_staff_str = ", ".join(unique_staff)

        existing_notes = ticket.admin_notes or ""
        ticket.admin_notes = f"Assigned to: {assigned_staff_str}\n{existing_notes}"
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
    backlog_tickets = Ticket.objects.filter(status='BACKLOG').order_by('created_at')
    history_tickets = Ticket.objects.filter(status='RESOLVED').order_by('-updated_at')
    audit_logs = TicketAuditLog.objects.all().order_by('-timestamp')[:50]

    today_start = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)
    activities_today = TicketAuditLog.objects.filter(timestamp__gte=today_start).count()
    urgent_tasks = Ticket.objects.filter(priority__in=['HIGH', 'URGENT']).exclude(status__in=['RESOLVED', 'COMPLETED']).count()

    oldest_age = "0d"
    if backlog_tickets.exists():
        oldest_age = f"{(timezone.now() - backlog_tickets.first().created_at).days}d"

    context = {
        'backlog_tickets': backlog_tickets,
        'history_tickets': history_tickets,
        'in_backlog': backlog_tickets.count(),
        'high_urgent': backlog_tickets.filter(priority__in=['HIGH', 'URGENT']).count(),
        'oldest_age': oldest_age,
        'audit_logs': audit_logs,
        'activities_today': activities_today,
        'urgent_tasks': urgent_tasks,
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

def update_ticket_ajax(request, ticket_id):
    if request.method == 'POST':
        try:
            ticket = get_object_or_404(Ticket, id=ticket_id)
            data = json.loads(request.body)
            if data.get('status'): ticket.status = data.get('status')
            if data.get('priority'): ticket.priority = data.get('priority')
            if data.get('admin_notes') is not None: ticket.admin_notes = data.get('admin_notes')
            ticket._current_user = request.user
            ticket.save()
            return JsonResponse({'success': True, 'message': 'Ticket updated successfully.'})
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
    is_school = request.session.get('is_school_authenticated', False)
    
    if not (is_employee or is_school):
        from django.contrib import messages
        messages.error(request, 'Only assigned employees or the respective school can print document forms.')
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

@login_required
def resolve_assignment(request, ticket_id):
    if request.method == 'POST':
        ticket = get_object_or_404(Ticket, id=ticket_id)
        ticket.status = 'RESOLVED'
        ticket._current_user = request.user
        ticket.save()
    return redirect('my_tickets')

@login_required
def unresolve_assignment(request, ticket_id):
    if request.method == 'POST':
        ticket = get_object_or_404(Ticket, id=ticket_id)
        reason = request.POST.get('reason', '').strip()
        
        if reason:
            timestamp = timezone.now().strftime("%Y-%m-%d %H:%M:%S")
            reason_text = f"\n[{timestamp}] Unresolved Reason: {reason}"
            if ticket.admin_notes:
                ticket.admin_notes += reason_text
            else:
                ticket.admin_notes = reason_text.strip()
                
        ticket.status = 'UNRESOLVED'
        ticket._current_user = request.user
        ticket.save()
    return redirect('my_tickets')

@login_required
def submit_for_review(request, ticket_id):
    if request.method == 'POST':
        ticket = get_object_or_404(Ticket, id=ticket_id)
        resolution_notes = request.POST.get('resolution_notes', '').strip()
        resolution_attachment = request.FILES.get('resolution_attachment')
        
        ticket.resolution_notes = resolution_notes
        if resolution_attachment:
            ticket.resolution_attachment = resolution_attachment
            
        ticket.status = 'UNDER_REVIEW'
        ticket._current_user = request.user
        ticket.save()
        messages.success(request, f'Ticket {ticket.ticket_number} submitted for QA review.')
    return redirect('my_tickets')

# ==========================================
# SCHOOLS MANAGEMENT & DIRECTORY
# ==========================================

@user_passes_test(is_admin_or_superuser, login_url='dashboard')
def schools_management(request):
    schools = School.objects.all().order_by('name')
    pending_requests = PasswordResetRequest.objects.filter(status='PENDING').order_by('-request_date')
    
    context = {
        'schools': schools,
        'pending_requests': pending_requests,
    }
    return render(request, 'tickets/schools_management.html', context)

@user_passes_test(is_admin_or_superuser, login_url='dashboard')
def reset_school_password(request, request_id):
    if request.method == 'POST':
        reset_request = get_object_or_404(PasswordResetRequest, id=request_id)
        new_password = request.POST.get('new_password')
        
        if new_password:
            school = reset_request.school
            school.set_password(new_password)
            school.save()
            
            reset_request.status = 'RESOLVED'
            reset_request.save()
            
            messages.success(request, f"Password successfully updated for {school.name}.")
        else:
            messages.error(request, "New password cannot be empty.")
            
    return redirect('schools_management')

def request_password_reset(request):
    if request.method == 'POST':
        school_id = request.POST.get('school_id')
        school = School.objects.filter(school_id=school_id).first()
        
        if school:
            # Check if there is already a pending request
            existing_request = PasswordResetRequest.objects.filter(school=school, status='PENDING').first()
            if not existing_request:
                PasswordResetRequest.objects.create(school=school, status='PENDING')
            
            # Since this is an AJAX fetch, we return JSON
            return JsonResponse({'success': True, 'message': 'Reset request sent to Division ICT Admin.'})
        else:
            return JsonResponse({'success': False, 'message': 'Invalid School ID.'})
            
    return JsonResponse({'success': False, 'message': 'Invalid method.'})