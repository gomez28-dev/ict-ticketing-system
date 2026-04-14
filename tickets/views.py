from .ml_service import predict_ticket_duration, recommend_staff, predict_risk
from django.utils import timezone
from .models import Ticket, School
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
        school_name = request.POST.get('school_name')
        school_id = request.POST.get('school_id')
        password = request.POST.get('password')
        try:
            school = School.objects.get(name=school_name, school_id=school_id)
            if school.check_password(password):
                request.session['school_name'] = school.name
                request.session['school_district'] = school.district
                request.session['is_school_authenticated'] = True
                return redirect('public_submit')
            else:
                messages.error(request, 'Invalid Password. Please try again.')
        except School.DoesNotExist:
            messages.error(request, 'Invalid School Name or School ID. Please try again.')

    schools = School.objects.all().order_by('name')
    return render(request, 'tickets/school_login.html', {'schools': schools})

# ==========================================
# MAIN KANBAN & PUBLIC VIEWS
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

def public_submit(request):
    if not request.session.get('is_school_authenticated'):
        return redirect('school_login')

    success_ticket = None
    if request.method == 'POST':
        try:
            ticket = Ticket.objects.create(
                first_name=request.POST.get('first_name'),
                last_name=request.POST.get('last_name'),
                middle_name=request.POST.get('middle_name', ''),
                contact_number=request.POST.get('contact_number', ''),
                email=request.POST.get('email', ''),
                school_district=request.POST.get('school_district', 'Not Specified'),
                school_name=request.POST.get('school_name', 'Not Specified'),
                support_type=request.POST.get('support_type', 'OTHER'),
                description=request.POST.get('description', ''),
                status='PENDING',
                priority='MEDIUM'
            )
            ticket.predicted_hours = predict_ticket_duration(ticket.support_type, ticket.priority)
            ticket.save()
            success_ticket = ticket
            messages.success(request, f"Ticket {ticket.ticket_number} has been successfully submitted and placed in the queue.")
        except Exception as e:
            print(f"Submission Error: {e}")
            messages.error(request, "There was an error processing your request. Please try again.")

    return render(request, 'tickets/public_submit.html', {'success_ticket': success_ticket})

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

    recent_school_tickets = Ticket.objects.filter(
        school_name=ticket.school_name
    ).exclude(id=ticket.id).order_by('-created_at')[:5]

    context = {
        'ticket': ticket,
        'predicted_hours': predicted_hours,
        'staff_rec': staff_rec,
        'risk_assessment': risk_assessment,
        'staff_data': get_staff_data(),
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

        scheduled_time_str = request.POST.get('scheduled_time')
        if scheduled_time_str:
            ticket.scheduled_time = scheduled_time_str

        assigned_staff_list = request.POST.getlist('assigned_staff')
        if not assigned_staff_list:
            assigned_staff_str = 'Unassigned'
        else:
            unique_staff = list(set(assigned_staff_list))
            assigned_staff_str = ", ".join(unique_staff)

        existing_notes = ticket.admin_notes or ""
        ticket.admin_notes = f"Assigned to: {assigned_staff_str}\n{existing_notes}"
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
    return render(request, 'tickets/teams.html', {'staff_data': get_staff_data()})

# ==========================================
# UTILITY VIEWS
# ==========================================

def backlog_view(request):
    backlog_tickets = Ticket.objects.filter(status='BACKLOG').order_by('created_at')
    history_tickets = Ticket.objects.filter(status='RESOLVED').order_by('-updated_at')
    oldest_age = "0d"
    if backlog_tickets.exists():
        oldest_age = f"{(timezone.now() - backlog_tickets.first().created_at).days}d"

    context = {
        'backlog_tickets': backlog_tickets,
        'history_tickets': history_tickets,
        'in_backlog': backlog_tickets.count(),
        'high_urgent': backlog_tickets.filter(priority__in=['HIGH', 'URGENT']).count(),
        'oldest_age': oldest_age,
    }
    return render(request, 'tickets/backlog.html', context)

def move_from_backlog(request, ticket_id):
    if request.method == 'POST':
        ticket = get_object_or_404(Ticket, id=ticket_id)
        ticket.status = 'SCHEDULED'
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

@login_required
def employee_receipt_view(request, ticket_id):
    ticket = get_object_or_404(Ticket, id=ticket_id)
    return render(request, 'tickets/employee_receipt.html', {'ticket': ticket})

@login_required
def employee_ticket_review(request, ticket_id):
    ticket = get_object_or_404(Ticket, id=ticket_id)
    return render(request, 'tickets/employee_ticket_review.html', {'ticket': ticket})

@login_required
def accept_assignment(request, ticket_id):
    if request.method == 'POST':
        ticket = get_object_or_404(Ticket, id=ticket_id)
        ticket.status = 'SCHEDULED'
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
        ticket.save()
    return redirect('my_tickets')

@login_required
def unresolve_assignment(request, ticket_id):
    if request.method == 'POST':
        ticket = get_object_or_404(Ticket, id=ticket_id)
        ticket.status = 'UNRESOLVED'
        ticket.save()
    return redirect('my_tickets')