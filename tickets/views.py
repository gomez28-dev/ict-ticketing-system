from .ml_service import predict_ticket_duration, recommend_staff, predict_risk
from django.utils import timezone
from django.db.models import Count
from .models import Ticket
from .forms import PublicTicketForm
from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse
from django.db.models import Q
import json
import joblib
import os


def predict_duration(complexity, priority_str):
    # Map priority back to numbers
    priority_map = {'LOW': 1, 'MEDIUM': 2, 'HIGH': 3, 'URGENT': 4}
    priority_weight = priority_map.get(priority_str, 2)

    # Load the trained AI model
    model_path = 'ticket_predictor.pkl'
    if os.path.exists(model_path):
        model = joblib.load(model_path)
        # Ask the AI for a prediction (returns hours)
        prediction = model.predict([[complexity, priority_weight]])[0]
        return round(prediction, 1)
    return None

def dashboard(request):
    tickets = Ticket.objects.all()

    # Example: Let's predict the duration for tickets in the Backlog
    for ticket in tickets:
        if ticket.status == 'BACKLOG':
            # Dynamically attach the AI prediction to the ticket object
            ticket.predicted_hours = predict_duration(ticket.complexity, ticket.priority)

    return render(request, 'tickets/dashboard.html', {'tickets': tickets})


def public_submit(request):
    success_ticket = None

    if request.method == 'POST':
        form = PublicTicketForm(request.POST)
        if form.is_valid():
            ticket = form.save(commit=False)

            # --- START OF NEW AI LOGIC ---
            # Predict the hours based on the form data
            ticket.predicted_hours = predict_ticket_duration(
                support_type=ticket.support_type,
                priority=ticket.priority
            )
            # --- END OF NEW AI LOGIC ---
            ticket.save()
            success_ticket = ticket
            form = PublicTicketForm()  # Clear the form after success
    else:
        form = PublicTicketForm()

    return render(request, 'tickets/public_submit.html', {
        'form': form,
        'success_ticket': success_ticket
    })


def requests_view(request):
    # Fetch only tickets that are 'PENDING' review, newest first
    pending_requests = Ticket.objects.filter(status='PENDING').order_by('-created_at')

    return render(request, 'tickets/requests.html', {
        'pending_requests': pending_requests
    })
def approve_request(request, ticket_id):
    if request.method == 'POST':
        # Find the specific ticket, or return a 404 error if it doesn't exist
        ticket = get_object_or_404(Ticket, id=ticket_id)
        # Change status to TODO so it appears in the 'Open' column of the Kanban board
        ticket.status = 'TODO'
        ticket.save()
    # Send the user back to the requests page to review the next one
    return redirect('requests')

def delete_request(request, ticket_id):
    if request.method == 'POST':
        ticket = get_object_or_404(Ticket, id=ticket_id)
        ticket.delete()
    return redirect('requests')


def analytics_dashboard(request):
    """Main dashboard view with metrics, chart, and top performers."""
    total_tickets = Ticket.objects.count()
    resolved_tickets = Ticket.objects.filter(status__in=['REVIEW', 'DONE']).count()
    pending_requests = Ticket.objects.filter(status='PENDING').count()

    staff_data = get_mock_staff_data()
    chart_data = get_mock_chart_data()  # Fetch the chart data

    context = {
        'total_tickets': total_tickets,
        'resolved_tickets': resolved_tickets,
        'pending_requests': pending_requests,
        'staff_data': staff_data,
        'chart_labels': chart_data['labels'],  # Send labels to JS
        'chart_received': chart_data['received'],  # Send received line to JS
        'chart_resolved': chart_data['resolved'],  # Send resolved line to JS
    }
    return render(request, 'tickets/analytics.html', context)


def get_mock_staff_data():
    """Centralized mock data for Staff & Teams.
    Eventually, this will be replaced by querying a custom User database."""
    return [
        {
            "name": "Mark Reyes",
            "role": "Hardware & Network Specialist",
            "skills": ["HARDWARE", "NETWORK", "CCTV"],
            "active_tickets": 3,
            "resolved_tickets": 42,
            "rating": 4.8
        },
        {
            "name": "Sarah Cruz",
            "role": "Software Support Lead",
            "skills": ["SOFTWARE", "ACCOUNT"],
            "active_tickets": 1,
            "resolved_tickets": 56,
            "rating": 4.9
        },
        {
            "name": "Alex Santos",
            "role": "General IT Technician",
            "skills": ["OTHER", "NETWORK"],
            "active_tickets": 2,
            "resolved_tickets": 31,
            "rating": 4.5
        }
    ]


def teams_view(request):
    """View for the Teams & Staff Management page."""
    staff_data = get_mock_staff_data()
    return render(request, 'tickets/teams.html', {'staff_data': staff_data})


def backlog_view(request):
    # 1. Fetch tickets in the backlog, sorted by oldest first
    backlog_tickets = Ticket.objects.filter(status='BACKLOG').order_by('created_at')

    # 2. Fetch History (Resolved/Done tickets), sorted by most recently updated
    history_tickets = Ticket.objects.filter(status__in=['REVIEW', 'DONE']).order_by('-updated_at')

    # Calculate the metrics for the top cards (based only on active backlog)
    in_backlog = backlog_tickets.count()
    high_urgent = backlog_tickets.filter(priority__in=['HIGH', 'URGENT']).count()

    # Calculate the age of the oldest ticket in days
    oldest_age = "0d"
    if backlog_tickets.exists():
        oldest_ticket = backlog_tickets.first()
        delta = timezone.now() - oldest_ticket.created_at
        oldest_age = f"{delta.days}d"

    return render(request, 'tickets/backlog.html', {
        'backlog_tickets': backlog_tickets,
        'history_tickets': history_tickets,
        'in_backlog': in_backlog,
        'high_urgent': high_urgent,
        'oldest_age': oldest_age,
    })


def search_tickets(request):
    # Grab what the user typed in the search bar
    query = request.GET.get('q', '')
    results = []

    if query:
        # Scan multiple fields for the search term using Q objects
        results = Ticket.objects.filter(
            Q(ticket_number__icontains=query) |
            Q(title__icontains=query) |
            Q(first_name__icontains=query) |
            Q(last_name__icontains=query) |
            Q(school_name__icontains=query)
        ).order_by('-created_at')

    return render(request, 'tickets/search_results.html', {
        'query': query,
        'results': results
    })


def move_from_backlog(request, ticket_id):
    # Moves a ticket from Backlog to the 'Open' (TODO) column
    if request.method == 'POST':
        ticket = get_object_or_404(Ticket, id=ticket_id)
        ticket.status = 'TODO'
        ticket.save()
    return redirect('backlog')


def update_ticket_ajax(request, ticket_id):
    if request.method == 'POST':
        try:
            ticket = get_object_or_404(Ticket, id=ticket_id)
            data = json.loads(request.body)

            # Grab all the data sent from our JavaScript
            new_status = data.get('status')
            new_priority = data.get('priority')
            new_notes = data.get('admin_notes')

            # Update fields
            if new_status:
                ticket.status = new_status
            if new_priority:
                ticket.priority = new_priority
            if new_notes is not None:  # Allows clearing the notes to blank
                ticket.admin_notes = new_notes

            ticket.save()
            return JsonResponse({'success': True, 'message': 'Ticket updated successfully.'})
        except Exception as e:
            return JsonResponse({'success': False, 'message': str(e)}, status=400)

    return JsonResponse({'success': False, 'message': 'Invalid request method.'}, status=405)

def settings_view(request):
    return render(request, 'tickets/settings.html')


def ticket_triage_view(request, ticket_id):
    """Loads the AI Triage Screen for a pending request."""
    ticket = get_object_or_404(Ticket, id=ticket_id)

    # 1. Run the AI Models
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
        # Grab the finalized data from the Triage Screen
        ticket.status = request.POST.get('status', 'TODO')
        ticket.priority = request.POST.get('priority', ticket.priority)

        # We append the assigned staff to the admin notes so we don't have to alter the database!
        assigned_staff = request.POST.get('assigned_staff', 'Unassigned')
        existing_notes = ticket.admin_notes or ""
        ticket.admin_notes = f"Assigned to: {assigned_staff}\n{existing_notes}"

        # Save the AI predicted hours
        ticket.predicted_hours = request.POST.get('predicted_hours', 1)

        ticket.save()

    return redirect('dashboard')

def get_mock_staff_data():
    """Centralized mock data for Staff & Teams.
    Eventually, this will be replaced by querying a custom User or Staff profile model."""
    return [
        {
            "name": "Mark Reyes",
            "role": "Hardware & Network Specialist",
            "skills": ["HARDWARE", "NETWORK", "CCTV"],
            "active_tickets": 3,
            "resolved_tickets": 42,
            "rating": 4.8
        },
        {
            "name": "Sarah Cruz",
            "role": "Software Support Lead",
            "skills": ["SOFTWARE", "ACCOUNT"],
            "active_tickets": 1,
            "resolved_tickets": 56,
            "rating": 4.9
        },
        {
            "name": "Alex Santos",
            "role": "General IT Technician",
            "skills": ["OTHER", "NETWORK"],
            "active_tickets": 2,
            "resolved_tickets": 31,
            "rating": 4.5
        }
    ]

def teams_view(request):
    """View for the Teams & Staff Management page."""
    staff_data = get_mock_staff_data()
    return render(request, 'tickets/teams.html', {'staff_data': staff_data})

def get_mock_chart_data():
    """Generates 7-day mock trend data for the System Activity chart."""
    return {
        'labels': ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'],
        'received': [8, 12, 15, 9, 14, 5, 3],
        'resolved': [6, 10, 18, 12, 11, 8, 4]
    }