import random
import math

from .staff_data import STAFF_LIST


# ==========================================
# PREDICTION SERVICES
# ==========================================

def get_mapped_support_type(support_type):
    """
    Maps the values from the Ticket's public submission form to the
    internal expertise and ML feature categories.
    """
    mapping = {
        'CCTV': 'CCTV',
        'PC_MAINTENANCE': 'PC_MAINTENANCE',
        'NETWORK_MAINTENANCE': 'NETWORK',
        'GOOGLE_ACCOUNT': 'ACCOUNT',
        'MS_ACCOUNT': 'ACCOUNT',
        'PASSWORD_RESET': 'ACCOUNT',
        'OTHER': 'OTHER',
    }
    return mapping.get(support_type, 'OTHER')


def predict_ticket_duration(support_type, priority):
    """
    Predicts task duration in hours AND days.
    Returns a dict with 'predicted_hours' and 'predicted_days'.
    """
    mapped_type = get_mapped_support_type(support_type)
    base_hours = {'ACCOUNT': 1, 'NETWORK': 4, 'HARDWARE': 8, 'PC_MAINTENANCE': 8, 'SOFTWARE': 3, 'CCTV': 4, 'OTHER': 5}
    estimated_time = base_hours.get(mapped_type, 5)

    priority_multipliers = {'URGENT': 0.5, 'HIGH': 0.8, 'MEDIUM': 1.0, 'LOW': 1.5}
    multiplier = priority_multipliers.get(priority, 1.0)

    final_hours = int(estimated_time * multiplier) + random.randint(0, 1)
    final_hours = max(1, final_hours)

    # Convert hours to days: divide by 8 working hours per day, round up, minimum 1
    predicted_days = max(1, math.ceil(final_hours / 8))

    return {
        'predicted_hours': final_hours,
        'predicted_days': predicted_days,
    }


def recommend_staff(school_name, support_type):
    """
    Recommends the best staff member for the job based on their expertise.
    Filters the dictionary safely and avoids KeyErrors.
    """
    # 1. Find all staff members who match the required expertise
    eligible_staff = []

    mapped_type = get_mapped_support_type(support_type)

    for staff in STAFF_LIST:
        expertise = [e.replace(' ', '_') for e in staff['expertise']]
        if mapped_type in expertise or "ALL" in expertise or "MANAGEMENT" in expertise:
            eligible_staff.append(staff)

    # 2. Fallback just in case no exact match is found
    if not eligible_staff:
        eligible_staff = STAFF_LIST

    # 3. Safely choose a random staff member from our filtered list
    selected_staff = random.choice(eligible_staff)

    # 4. Generate the AI reason to display on the UI
    from .models import Ticket
    # Calculate live current load
    current_load = Ticket.objects.filter(
        admin_notes__icontains=selected_staff['name']
    ).exclude(status__in=['RESOLVED', 'COMPLETED']).count()

    reason = f"Matches expertise for '{support_type}'. Currently handling {current_load} active tickets."

    return {
        "recommended_name": selected_staff['name'],
        "reason": reason
    }


def predict_risk(support_type, priority):
    """
    BASELINE RISK PREDICTION
    Flags potential blockers based on category and urgency.
    """
    mapped_type = get_mapped_support_type(support_type)
    
    if priority == 'URGENT' or mapped_type in ['HARDWARE', 'PC_MAINTENANCE']:
        return {"level": "High", "color": "red",
                "blockers": "Hardware procurement delays or unavailability of replacement parts. High urgency may cause staff bottleneck."}
    elif mapped_type == 'NETWORK':
        return {"level": "Medium", "color": "yellow",
                "blockers": "Requires coordination with external ISPs. Possible line check delays."}
    else:
        return {"level": "Low", "color": "green",
                "blockers": "Standard procedure. Minimal blockers expected if credentials are correct."}


def calculate_overall_rating(quality, efficiency, timeliness):
    """
    Calculates an overall performance rating from individual scores.
    Score to percentage map: 5 → 100%, 4 → 80%, 3 → 60%, 2 → 40%
    Formula: overall = (quality_pct × 5 × 0.40) + (efficiency_pct × 5 × 0.30) + (timeliness_pct × 5 × 0.30)
    Returns the overall float value rounded to 2 decimal places.
    """
    score_to_pct = {5: 1.0, 4: 0.8, 3: 0.6, 2: 0.4}

    quality_pct = score_to_pct.get(quality, 0.6)
    efficiency_pct = score_to_pct.get(efficiency, 0.6)
    timeliness_pct = score_to_pct.get(timeliness, 0.6)

    overall = (quality_pct * 5 * 0.40) + (efficiency_pct * 5 * 0.30) + (timeliness_pct * 5 * 0.30)
    return round(overall, 2)