from .models import Ticket, SchoolAccountRequest


def global_ticket_counts(request):
    """
    Automatically injects global ticket counts into every template
    so views don't have to fetch them manually.
    """
    context = {}
    if request.user.is_authenticated:
        # Get total pending for admins
        context['pending_count'] = Ticket.objects.filter(status='PENDING').count()

        # Get active ticket count for the logged-in user
        user_name = f"{request.user.first_name} {request.user.last_name}".strip()
        context['my_ticket_count'] = Ticket.objects.filter(
            admin_notes__icontains=user_name
        ).exclude(status__in=['RESOLVED', 'COMPLETED']).count()

        # Badge counts for Schools and Documents nav items
        context['pending_schools_count'] = SchoolAccountRequest.objects.filter(status='PENDING').count()
        context['under_review_docs_count'] = Ticket.objects.filter(status='UNDER_REVIEW').count()

    return context