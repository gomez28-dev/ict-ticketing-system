from .ml_service import predict_ticket_duration
from django.utils import timezone
from django.db.models import Count
from django.shortcuts import render
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
    # We exclude 'PENDING' because those haven't been approved to the main board yet
    active_tickets = Ticket.objects.exclude(status='PENDING')

    # 1. Calculate Top Card Metrics
    total = active_tickets.count()
    open_count = active_tickets.filter(status__in=['BACKLOG', 'TODO']).count()
    in_progress = active_tickets.filter(status='IN_PROGRESS').count()
    resolved = active_tickets.filter(status__in=['REVIEW', 'DONE']).count()

    # 2. Calculate Overall Resolution Rate for the progress bar
    resolution_rate = 0
    if total > 0:
        resolution_rate = int((resolved / total) * 100)

    # 3. Get data for "Requests by Type"
    type_counts = active_tickets.values('support_type').annotate(count=Count('id'))
    support_dict = dict(Ticket.SUPPORT_CHOICES)

    chart_data = []
    for item in type_counts:
        if item['support_type']:  # Ignore empty ones
            name = support_dict.get(item['support_type'], 'Other')
            # Calculate a percentage width for the visual bar chart
            width = int((item['count'] / total) * 100) if total > 0 else 0
            chart_data.append({'name': name, 'count': item['count'], 'width': width})

    context = {
        'total_tickets': total,
        'open_tickets': open_count,
        'in_progress_tickets': in_progress,
        'resolved_tickets': resolved,
        'resolution_rate': resolution_rate,
        'chart_data': chart_data,
    }
    return render(request, 'tickets/analytics.html', context)


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