from .ml_service import predict_ticket_duration, recommend_staff, predict_risk
from django.utils import timezone
from .models import Ticket
from .forms import PublicTicketForm
from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse
from django.db.models import Q
import json
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import user_passes_test

User = get_user_model()


def is_superadmin(user):
    """Check if the user is a superuser."""
    return user.is_superuser


@user_passes_test(is_superadmin, login_url='dashboard')
def add_employee(request):
    """Secure view to allow Super Admins to create new staff accounts."""
    error = None

    if request.method == 'POST':
        first_name = request.POST.get('first_name')
        last_name = request.POST.get('last_name')
        email = request.POST.get('email')
        role = request.POST.get('role', 'MEMBER')
        password = request.POST.get('password')

        # Use email as the username for simplicity, or generate a username
        username = email.split('@')[0] if email else f"{first_name.lower()}.{last_name.lower()}"

        # Check if user already exists
        if User.objects.filter(username=username).exists() or User.objects.filter(email=email).exists():
            error = "An employee with this email or username already exists."
        else:
            # Create the new user securely
            new_user = User.objects.create_user(
                username=username,
                email=email,
                password=password,
                first_name=first_name,
                last_name=last_name,
                role=role
            )

            # If they are added as an ADMIN or MANAGER, grant them staff status
            if role in ['ADMIN', 'MANAGER']:
                new_user.is_staff = True
                new_user.save()

            return redirect('teams')

    return render(request, 'tickets/add_employee.html', {'error': error})


# ==========================================
# AUTHENTICATION VIEWS
# ==========================================

def custom_login(request):
    """Handles the custom dark-mode login page."""
    # Redirect if already logged in
    if request.user.is_authenticated:
        return redirect('dashboard')

    if request.method == 'POST':
        email_input = request.POST.get('email', '').strip()

        # --- CONDITIONAL LOGIN BYPASS FOR DEVELOPMENT ---
        if email_input == 'admin@test.com':
            # 1. Log in as a regular Admin
            # Get or create a hardcoded standard Admin account
            user, created = User.objects.get_or_create(
                username='testadmin',
                defaults={
                    'email': 'admin@test.com',
                    'first_name': 'Test',
                    'last_name': 'Admin',
                    'role': 'ADMIN',
                    'is_staff': True,
                    'is_superuser': False
                }
            )
            # If it just created the user, set a dummy password and save
            if created:
                user.set_password('AdminPass123!')
                user.save()

        else:
            # 2. Log in as Super Admin
            # Find the actual superuser in the database instead of just the first user
            user = User.objects.filter(is_superuser=True).first()

            # Fallback just in case no superuser exists yet
            if not user:
                user = User.objects.first()

        # Log the selected user in and redirect
        if user:
            login(request, user)
        return redirect('dashboard')

    return render(request, 'tickets/login.html')


def custom_logout(request):
    """Logs the user out and redirects to the public submission page."""
    logout(request)
    return redirect('public_submit')

# ==========================================
# MAIN KANBAN & PUBLIC VIEWS
# ==========================================

def dashboard(request):
    """Loads the main Kanban board."""
    tickets = Ticket.objects.all()
    # Notice: We removed the slow AI loop here because predictions
    # are now saved directly to the database during Triage!
    return render(request, 'tickets/dashboard.html', {'tickets': tickets})

def public_submit(request):
    """Handles the public form submission from users."""
    success_ticket = None

    if request.method == 'POST':
        form = PublicTicketForm(request.POST)
        if form.is_valid():
            ticket = form.save(commit=False)
            # Run baseline AI prediction on submission
            ticket.predicted_hours = predict_ticket_duration(
                support_type=ticket.support_type,
                priority=ticket.priority
            )
            ticket.save()
            success_ticket = ticket
            form = PublicTicketForm()
    else:
        form = PublicTicketForm()

    return render(request, 'tickets/public_submit.html', {
        'form': form,
        'success_ticket': success_ticket
    })

def requests_view(request):
    """Shows all pending requests waiting for Triage."""
    pending_requests = Ticket.objects.filter(status='PENDING').order_by('-created_at')
    return render(request, 'tickets/requests.html', {'pending_requests': pending_requests})

def delete_request(request, ticket_id):
    """Permanently deletes a spam or invalid request."""
    if request.method == 'POST':
        ticket = get_object_or_404(Ticket, id=ticket_id)
        ticket.delete()
    return redirect('requests')


# ==========================================
# AI TRIAGE WORKFLOW
# ==========================================

def ticket_triage_view(request, ticket_id):
    """Loads the AI Triage Screen for a pending request."""
    ticket = get_object_or_404(Ticket, id=ticket_id)

    # Run the AI Models
    predicted_hours = predict_ticket_duration(ticket.support_type, ticket.priority)
    staff_rec = recommend_staff(ticket.school_name, ticket.support_type)
    risk_assessment = predict_risk(ticket.support_type, ticket.priority)

    return render(request, 'tickets/ticket_creation.html', {
        'ticket': ticket,
        'predicted_hours': predicted_hours,
        'staff_rec': staff_rec,
        'risk_assessment': risk_assessment
    })


def approve_request(request, ticket_id):
    """Saves the finalized triage data and moves ticket to the board."""
    ticket = get_object_or_404(Ticket, id=ticket_id)

    if request.method == 'POST':
        ticket.status = request.POST.get('status', 'TODO')
        ticket.priority = request.POST.get('priority', ticket.priority)

        # Retrieve MULTIPLE assigned staff as a list using getlist()
        assigned_staff_list = request.POST.getlist('assigned_staff')

        if not assigned_staff_list:
            assigned_staff_str = 'Unassigned'
        else:
            # Remove duplicates just in case
            unique_staff = list(set(assigned_staff_list))
            assigned_staff_str = ", ".join(unique_staff)

        # Append assigned staff to notes
        existing_notes = ticket.admin_notes or ""
        ticket.admin_notes = f"Assigned to: {assigned_staff_str}\n{existing_notes}"

        # Save AI predicted hours
        ticket.predicted_hours = request.POST.get('predicted_hours', 1)
        ticket.save()

    return redirect('dashboard')


# ==========================================
# ANALYTICS & TEAMS (MOCK DATA)
# ==========================================

def get_mock_staff_data():
    """Centralized mock data for Employees."""
    return [
        {"name": "Mark Reyes", "role": "Hardware & Network Specialist", "skills": ["HARDWARE", "NETWORK", "CCTV"], "active_tickets": 3, "resolved_tickets": 42, "rating": 4.8},
        {"name": "Sarah Cruz", "role": "Software Support Lead", "skills": ["SOFTWARE", "ACCOUNT"], "active_tickets": 1, "resolved_tickets": 56, "rating": 4.9},
        {"name": "Alex Santos", "role": "General IT Technician", "skills": ["OTHER", "NETWORK"], "active_tickets": 2, "resolved_tickets": 31, "rating": 4.5}
    ]

def get_mock_chart_data():
    """Generates 7-day mock trend data for the System Activity chart."""
    return {
        'labels': ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'],
        'received': [8, 12, 15, 9, 14, 5, 3],
        'resolved': [6, 10, 18, 12, 11, 8, 4]
    }

def analytics_dashboard(request):
    """Main dashboard view with metrics, chart, and top performers."""
    total_tickets = Ticket.objects.count()
    resolved_tickets = Ticket.objects.filter(status__in=['REVIEW', 'DONE']).count()
    pending_requests = Ticket.objects.filter(status='PENDING').count()

    context = {
        'total_tickets': total_tickets,
        'resolved_tickets': resolved_tickets,
        'pending_requests': pending_requests,
        'staff_data': get_mock_staff_data(),
        'chart_labels': get_mock_chart_data()['labels'],
        'chart_received': get_mock_chart_data()['received'],
        'chart_resolved': get_mock_chart_data()['resolved'],
    }
    return render(request, 'tickets/analytics.html', context)

def teams_view(request):
    """View for the Employee Management page."""
    return render(request, 'tickets/teams.html', {'staff_data': get_mock_staff_data()})


# ==========================================
# UTILITY VIEWS (Backlog, Search, Settings, AJAX)
# ==========================================

def backlog_view(request):
    """Shows unresolved tickets and archived history."""
    backlog_tickets = Ticket.objects.filter(status='BACKLOG').order_by('created_at')
    history_tickets = Ticket.objects.filter(status__in=['REVIEW', 'DONE']).order_by('-updated_at')

    oldest_age = "0d"
    if backlog_tickets.exists():
        oldest_ticket = backlog_tickets.first()
        delta = timezone.now() - oldest_ticket.created_at
        oldest_age = f"{delta.days}d"

    return render(request, 'tickets/backlog.html', {
        'backlog_tickets': backlog_tickets,
        'history_tickets': history_tickets,
        'in_backlog': backlog_tickets.count(),
        'high_urgent': backlog_tickets.filter(priority__in=['HIGH', 'URGENT']).count(),
        'oldest_age': oldest_age,
    })

def move_from_backlog(request, ticket_id):
    """Moves a ticket from Backlog to the 'Open' column."""
    if request.method == 'POST':
        ticket = get_object_or_404(Ticket, id=ticket_id)
        ticket.status = 'TODO'
        ticket.save()
    return redirect('backlog')

def search_tickets(request):
    """Handles global ticket searching."""
    query = request.GET.get('q', '')
    results = []
    if query:
        results = Ticket.objects.filter(
            Q(ticket_number__icontains=query) |
            Q(title__icontains=query) |
            Q(first_name__icontains=query) |
            Q(last_name__icontains=query) |
            Q(school_name__icontains=query)
        ).order_by('-created_at')

    return render(request, 'tickets/search_results.html', {'query': query, 'results': results})

def update_ticket_ajax(request, ticket_id):
    """Handles background saves from the Kanban board modal."""
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
    """Loads the settings UI."""
    return render(request, 'tickets/settings.html')


def admin_create_ticket(request):
    """Allows Admins to manually create a ticket from the dashboard."""
    if request.method == 'POST':
        ticket = Ticket.objects.create(
            first_name=request.POST.get('first_name'),
            last_name=request.POST.get('last_name'),
            email=request.POST.get('email', ''),
            contact_number=request.POST.get('contact_number', ''),
            school_name=request.POST.get('school_name', 'Not Specified'),
            barangay=request.POST.get('barangay', 'Not Specified'),  # <-- NEW LINE
            school_district=request.POST.get('school_district', 'DISTRICT_I'),
            support_type=request.POST.get('support_type', 'OTHER'),
            description=request.POST.get('description', ''),
            priority=request.POST.get('priority', 'MEDIUM'),
            status=request.POST.get('status', 'TODO'),
            predicted_hours=request.POST.get('predicted_hours', 1)
        )

        # Handle multiple assigned staff
        assigned_staff_list = request.POST.getlist('assigned_staff')
        if assigned_staff_list:
            unique_staff = list(set(assigned_staff_list))
            assigned_staff_str = ", ".join(unique_staff)
            ticket.admin_notes = f"Assigned to: {assigned_staff_str}\n"
            ticket.save()

        return redirect('dashboard')

    return render(request, 'tickets/admin_create_ticket.html')