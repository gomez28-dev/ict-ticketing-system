import random


def predict_ticket_duration(support_type, priority):
    """Predicts task duration in hours."""
    base_hours = {'ACCOUNT': 1, 'NETWORK': 4, 'HARDWARE': 8, 'SOFTWARE': 3, 'OTHER': 5}
    estimated_time = base_hours.get(support_type, 5)

    priority_multipliers = {'URGENT': 0.5, 'HIGH': 0.8, 'MEDIUM': 1.0, 'LOW': 1.5}
    multiplier = priority_multipliers.get(priority, 1.0)

    final_prediction = int(estimated_time * multiplier) + random.randint(0, 1)
    return max(1, final_prediction)


def recommend_staff(school_name, support_type):
    """
    BASELINE STAFF RECOMMENDATION
    In the future, this will query the User/Employee database.
    For now, it uses logic to recommend staff based on the issue type.
    """
    staff_db = [
        {"name": "Mark Reyes", "skills": ["HARDWARE", "NETWORK"], "active": 1},
        {"name": "Sarah Cruz", "skills": ["SOFTWARE", "ACCOUNT"], "active": 2},
        {"name": "Alex Santos", "skills": ["OTHER", "NETWORK"], "active": 0}
    ]

    # Simple logic: Find staff with matching skills, or pick a random one
    recommended = next((staff for staff in staff_db if support_type in staff["skills"]), random.choice(staff_db))

    reason = f"Matches expertise for '{support_type}'. Currently handling {recommended['active']} active tickets."
    return {"recommended_name": recommended["name"], "reason": reason}


def predict_risk(support_type, priority):
    """
    BASELINE RISK PREDICTION
    Flags potential blockers based on category and urgency.
    """
    if priority == 'URGENT' or support_type == 'HARDWARE':
        return {"level": "High", "color": "red",
                "blockers": "Hardware procurement delays or unavailability of replacement parts. High urgency may cause staff bottleneck."}
    elif support_type == 'NETWORK':
        return {"level": "Medium", "color": "yellow",
                "blockers": "Requires coordination with external ISPs. Possible line check delays."}
    else:
        return {"level": "Low", "color": "green",
                "blockers": "Standard procedure. Minimal blockers expected if credentials are correct."}