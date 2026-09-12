from datetime import timedelta
import random
from django.utils import timezone
from django.db.models import Count, Q
from django.db.models.functions import TruncDate
from .models import Ticket, User


SUPPORT_TYPE_LABELS = {
    'CCTV': 'CCTV Maintenance/Check-Up or Repair Request',
    'PC_MAINTENANCE': 'Computer Maintenance/Check-Up or Repair Request',
    'NETWORK_MAINTENANCE': 'Computer Network Maintenance/Check-Up or Repair Request',
    'GOOGLE_ACCOUNT': 'Creation of Google Account',
    'MS_ACCOUNT': 'Creation of Microsoft Account',
    'PASSWORD_RESET': 'Password Reset for Microsoft or Google Account',
    'OTHER': 'Other Support',
}

SUPPORT_TYPE_SHORT_LABELS = {
    'CCTV': 'CCTV Repair',
    'PC_MAINTENANCE': 'PC Maintenance',
    'NETWORK_MAINTENANCE': 'Network Support',
    'GOOGLE_ACCOUNT': 'Google Account',
    'MS_ACCOUNT': 'MS Account',
    'PASSWORD_RESET': 'Password Reset',
    'OTHER': 'Other',
}


def _calculate_ticket_resolution_hours(ticket):
    """
    Computes resolution time in hours for a resolved/completed ticket.
    Uses actual timestamps if duration is significant (> 60 seconds),
    otherwise falls back to predicted_hours if available.
    """
    start = ticket.assigned_at or ticket.created_at
    end = ticket.actual_completion_date or ticket.updated_at
    if start and end:
        diff_seconds = (end - start).total_seconds()
        if diff_seconds > 60:
            return diff_seconds / 3600.0
    if ticket.predicted_hours:
        return float(ticket.predicted_hours)
    return None


def format_duration(hours):
    if hours is None:
        return "N/A"
    if hours < 1:
        minutes = max(1, int(round(hours * 60)))
        return f"{minutes} min{'s' if minutes != 1 else ''}"
    if hours < 24:
        return f"{hours:.1f} hrs"
    days = hours / 24.0
    return f"{days:.1f} days"


def get_analytics_report_context(period='all', start_date=None, end_date=None, user=None):
    """
    Compiles complete analytics and performance metrics for the PDF Report
    and Analytics Dashboard matching the ICT Helpdesk Analytics Report Template.
    """
    now = timezone.now()
    tickets_qs = Ticket.objects.all()

    # 1. Determine date filter range
    period_display = "All Records (All Time)"
    filter_start = None
    filter_end = None

    if period == 'today':
        filter_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        filter_end = now
        period_display = f"Today ({now.strftime('%B %d, %Y')})"
    elif period == 'this_week':
        filter_start = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
        filter_end = now
        period_display = f"This Week ({filter_start.strftime('%b %d')} - {filter_end.strftime('%b %d, %Y')})"
    elif period == 'this_month':
        filter_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        filter_end = now
        period_display = f"This Month ({now.strftime('%B %Y')})"
    elif period == 'last_30':
        filter_start = now - timedelta(days=30)
        filter_end = now
        period_display = f"Last 30 Days ({filter_start.strftime('%b %d')} - {filter_end.strftime('%b %d, %Y')})"
    elif period == 'this_year':
        filter_start = now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
        filter_end = now
        period_display = f"Year {now.year} to Date"
    elif period == 'custom' and start_date and end_date:
        try:
            from datetime import datetime
            if isinstance(start_date, str):
                start_date = datetime.strptime(start_date, '%Y-%m-%d')
            if isinstance(end_date, str):
                end_date = datetime.strptime(end_date, '%Y-%m-%d')
            filter_start = timezone.make_aware(datetime.combine(start_date, datetime.min.time())) if timezone.is_naive(start_date) else start_date
            filter_end = timezone.make_aware(datetime.combine(end_date, datetime.max.time())) if timezone.is_naive(end_date) else end_date
            period_display = f"{filter_start.strftime('%B %d, %Y')} - {filter_end.strftime('%B %d, %Y')}"
        except Exception:
            filter_start = None
            filter_end = None
            period_display = "All Records (All Time)"

    if filter_start and filter_end:
        tickets_qs = tickets_qs.filter(created_at__range=(filter_start, filter_end))

    # If 'all' period, calculate actual min and max dates for display context
    if period == 'all' and tickets_qs.exists():
        min_date = tickets_qs.order_by('created_at').first().created_at
        max_date = tickets_qs.order_by('-created_at').first().created_at
        if min_date and max_date:
            period_display = f"All Time ({min_date.strftime('%B %d, %Y')} - {max_date.strftime('%B %d, %Y')})"

    total_tickets = tickets_qs.count()

    # -------------------------------------------------------------
    # SECTION I. SYSTEM SUMMARY
    # -------------------------------------------------------------
    resolved_count = tickets_qs.filter(status__in=['RESOLVED', 'COMPLETED']).count()
    pending_count = tickets_qs.filter(status='PENDING').count()
    in_progress_count = tickets_qs.filter(status='IN_PROGRESS').count()
    under_review_count = tickets_qs.filter(status='UNDER_REVIEW').count()

    system_summary = {
        'total_tickets': total_tickets,
        'resolved': resolved_count,
        'pending': pending_count,
        'in_progress': in_progress_count,
        'under_review': under_review_count,
    }

    # -------------------------------------------------------------
    # SECTION II. SCHOOL COMPLAINT / REQUEST ANALYSIS
    # -------------------------------------------------------------
    school_counts = (
        tickets_qs.exclude(school_name__isnull=True)
        .exclude(school_name='')
        .values('school_name')
        .annotate(count=Count('id'))
        .order_by('-count')
    )

    top_schools = []
    top_school_name = "None"
    top_school_total = 0

    for idx, item in enumerate(school_counts[:5], start=1):
        s_name = item['school_name']
        s_count = item['count']
        pct = (s_count / total_tickets * 100.0) if total_tickets > 0 else 0.0
        top_schools.append({
            'rank': idx,
            'school_name': s_name,
            'count': s_count,
            'percentage': round(pct, 1),
        })
        if idx == 1:
            top_school_name = s_name
            top_school_total = s_count

    # Fill empty slots up to 5 if fewer than 5 exist
    while len(top_schools) < 5:
        top_schools.append({
            'rank': len(top_schools) + 1,
            'school_name': '—',
            'count': 0,
            'percentage': 0.0,
        })

    school_analysis = {
        'most_complaints_school': top_school_name,
        'most_complaints_total': top_school_total,
        'top_schools': top_schools,
    }

    # -------------------------------------------------------------
    # SECTION III. MOST REQUESTED SERVICES
    # -------------------------------------------------------------
    service_counts = (
        tickets_qs.exclude(support_type__isnull=True)
        .exclude(support_type='')
        .values('support_type')
        .annotate(count=Count('id'))
        .order_by('-count')
    )

    top_services = []
    top_service_name = "None"
    top_service_total = 0

    for idx, item in enumerate(service_counts[:5], start=1):
        st_code = item['support_type']
        s_count = item['count']
        full_label = SUPPORT_TYPE_LABELS.get(st_code, st_code)
        pct = (s_count / total_tickets * 100.0) if total_tickets > 0 else 0.0
        top_services.append({
            'rank': idx,
            'code': st_code,
            'service_name': full_label,
            'short_name': SUPPORT_TYPE_SHORT_LABELS.get(st_code, st_code),
            'count': s_count,
            'percentage': round(pct, 1),
        })
        if idx == 1:
            top_service_name = full_label
            top_service_total = s_count

    while len(top_services) < 5:
        top_services.append({
            'rank': len(top_services) + 1,
            'code': '',
            'service_name': '—',
            'short_name': '—',
            'count': 0,
            'percentage': 0.0,
        })

    service_analysis = {
        'most_requested_service': top_service_name,
        'most_requested_total': top_service_total,
        'top_services': top_services,
    }

    # -------------------------------------------------------------
    # SECTION IV. EMPLOYEE PERFORMANCE ANALYSIS
    # -------------------------------------------------------------
    members = User.objects.filter(role='MEMBER').exclude(is_superuser=True)
    employee_stats = []

    for emp in members:
        emp_name = emp.get_full_name().strip() or emp.username
        emp_name_lower = emp_name.lower()

        # Tickets handled by this employee within filtered ticket set
        emp_tickets = [
            t for t in tickets_qs
            if (t.assignee_id == emp.id) or (t.admin_notes and emp_name_lower in t.admin_notes.lower())
        ]
        tickets_handled = len(emp_tickets)

        resolved_tickets = [t for t in emp_tickets if t.status in ['RESOLVED', 'COMPLETED']]
        resolved_count_emp = len(resolved_tickets)

        # Average resolution time
        durations = []
        for t in resolved_tickets:
            dur = _calculate_ticket_resolution_hours(t)
            if dur is not None and dur > 0:
                durations.append(dur)

        avg_hours = (sum(durations) / len(durations)) if durations else None
        avg_res_display = format_duration(avg_hours)

        rating = emp.overall_rating if emp.overall_rating is not None else 0.0

        employee_stats.append({
            'user': emp,
            'name': emp_name,
            'tickets_handled': tickets_handled,
            'resolved': resolved_count_emp,
            'avg_resolution_time': avg_res_display,
            'avg_resolution_hours': avg_hours or 0.0,
            'rating': round(rating, 2),
            'rating_display': f"{rating:.2f} / 5",
        })

    # Sort employees by:
    # 1. rating desc, 2. resolved desc, 3. tickets_handled desc
    employee_stats.sort(
        key=lambda x: (x['rating'], x['resolved'], x['tickets_handled']),
        reverse=True
    )

    top_employees = []
    for idx, stat in enumerate(employee_stats[:5], start=1):
        stat['rank'] = idx
        top_employees.append(stat)

    while len(top_employees) < 5:
        top_employees.append({
            'rank': len(top_employees) + 1,
            'name': '—',
            'tickets_handled': 0,
            'resolved': 0,
            'avg_resolution_time': '—',
            'rating': 0.0,
            'rating_display': '—',
        })

    top_employee_name = top_employees[0]['name'] if top_employees and top_employees[0]['name'] != '—' else "N/A"
    top_employee_rating = f"{top_employees[0]['rating']:.2f}" if top_employees and top_employees[0]['name'] != '—' else "0.00"

    employee_analysis = {
        'top_employee_name': top_employee_name,
        'top_employee_rating': top_employee_rating,
        'top_employees': top_employees,
    }

    # -------------------------------------------------------------
    # SECTION V. SYSTEM ANALYTICS (CHARTS DATA)
    # -------------------------------------------------------------
    # Chart A: System Activity (Timeline)
    if tickets_qs.exists():
        earliest = tickets_qs.order_by('created_at').first().created_at.date()
        latest = tickets_qs.order_by('-created_at').first().created_at.date()
        span_days = (latest - earliest).days + 1

        if span_days <= 14:
            chart_dates = [earliest + timedelta(days=i) for i in range(span_days)]
        elif span_days <= 35:
            chart_dates = [earliest + timedelta(days=i) for i in range(span_days)]
        else:
            chart_dates = [earliest + timedelta(days=int(i * span_days / 14)) for i in range(15)]
            chart_dates = sorted(list(set(chart_dates)))
    else:
        chart_dates = [now.date() - timedelta(days=i) for i in reversed(range(7))]

    activity_labels = [d.strftime('%b %d') for d in chart_dates]

    daily_received = (
        tickets_qs.annotate(day=TruncDate('created_at'))
        .values('day')
        .annotate(c=Count('id'))
    )
    rec_map = {item['day']: item['c'] for item in daily_received}

    daily_resolved = (
        tickets_qs.filter(status__in=['RESOLVED', 'COMPLETED'])
        .annotate(day=TruncDate('actual_completion_date'))
        .values('day')
        .annotate(c=Count('id'))
    )
    res_map = {item['day']: item['c'] for item in daily_resolved if item['day']}

    activity_received = [rec_map.get(d, 0) for d in chart_dates]
    activity_resolved = [res_map.get(d, 0) for d in chart_dates]

    # Chart B: Requests by School
    valid_schools = [s for s in top_schools if s['school_name'] != '—' and s['count'] > 0]
    school_chart_labels = [s['school_name'] for s in valid_schools]
    school_chart_data = [s['count'] for s in valid_schools]

    # Chart C: Most Requested Services
    valid_services = [s for s in top_services if s['service_name'] != '—' and s['count'] > 0]
    service_chart_labels = [s['short_name'] for s in valid_services]
    service_chart_data = [s['count'] for s in valid_services]

    # Chart D: Employee Performance Ranking
    valid_emp_ranks = [e for e in employee_stats if e['name'] != '—' and e['rating'] > 0][:5]
    emp_chart_labels = [e['name'] for e in valid_emp_ranks]
    emp_chart_data = [e['rating'] for e in valid_emp_ranks]

    chart_payload = {
        'activity': {
            'labels': activity_labels,
            'received': activity_received,
            'resolved': activity_resolved,
        },
        'schools': {
            'labels': school_chart_labels,
            'data': school_chart_data,
        },
        'services': {
            'labels': service_chart_labels,
            'data': service_chart_data,
        },
        'employees': {
            'labels': emp_chart_labels,
            'data': emp_chart_data,
        },
    }

    # -------------------------------------------------------------
    # SECTION VI. REPORT CERTIFICATION & METADATA
    # -------------------------------------------------------------
    gen_by_name = user.get_full_name().strip() if (user and user.get_full_name()) else (user.username if user else "ICT Administrator")
    gen_by_role = "ICT Administrator"
    if user and user.is_superuser:
        gen_by_role = "ICT Head"
    elif user and getattr(user, 'role', '') == 'ADMIN':
        gen_by_role = "ICT Secretary / Admin"

    ict_head_user = User.objects.filter(is_superuser=True).first()
    verified_by_name = ict_head_user.get_full_name() if (ict_head_user and ict_head_user.get_full_name()) else "Ramon Sy"
    verified_by_title = "Division IT Officer / ICT Head"

    date_str = now.strftime('%Y%m%d')
    rand_seq = random.randint(1000, 9999)
    report_ref_no = f"ICT-AR-{date_str}-{rand_seq}"

    context = {
        'period': period,
        'start_date': start_date if isinstance(start_date, str) else (start_date.strftime('%Y-%m-%d') if start_date else ''),
        'end_date': end_date if isinstance(end_date, str) else (end_date.strftime('%Y-%m-%d') if end_date else ''),
        'reporting_period': period_display,
        'date_generated': now.strftime('%B %d, %Y'),
        'date_generated_full': now.strftime('%B %d, %Y %I:%M %p'),
        'generated_by': f"{gen_by_name} ({gen_by_role})",
        'report_reference_no': report_ref_no,
        'system_summary': system_summary,
        'school_analysis': school_analysis,
        'service_analysis': service_analysis,
        'employee_analysis': employee_analysis,
        'charts': chart_payload,
        'prepared_by_name': gen_by_name,
        'prepared_by_title': gen_by_role,
        'verified_by_name': verified_by_name,
        'verified_by_title': verified_by_title,
    }

    return context
