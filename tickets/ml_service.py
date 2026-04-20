import random

# ==========================================
# STAFF DATABASE
# ==========================================
staff_db = {
    # Head / Officer
    "Noel E. Reyes": {"expertise": ["MANAGEMENT", "SYSTEM_ADMIN", "ALL"], "current_load": 1, "rating": 5.0},

    # CCTV Team
    "Marvin M. Cruz": {"expertise": ["CCTV"], "current_load": 2, "rating": 4.8},
    "Ariel C. Samosino": {"expertise": ["CCTV"], "current_load": 1, "rating": 4.7},
    "Elison D. Carredo": {"expertise": ["CCTV"], "current_load": 3, "rating": 4.9},
    "Rolando O. De Castro Jr.": {"expertise": ["CCTV"], "current_load": 0, "rating": 4.6},
    "Edgar Manalansan": {"expertise": ["CCTV"], "current_load": 2, "rating": 4.8},
    "Ariel Cariaga": {"expertise": ["CCTV"], "current_load": 1, "rating": 4.7},

    # Website Development
    "Ike Joseph P. Lumaad": {"expertise": ["WEBSITE", "SYSTEM_DEV"], "current_load": 2, "rating": 4.9},
    "Niel Ian I. Pariñas": {"expertise": ["WEBSITE", "SYSTEM_DEV"], "current_load": 1, "rating": 4.8},

    # Network Infrastructure
    "Zandro S. Ocampo": {"expertise": ["NETWORK", "INTERNET"], "current_load": 2, "rating": 4.9},
    "Reagan James H. Tayag": {"expertise": ["NETWORK", "INTERNET"], "current_load": 3, "rating": 4.7},
    "Erickson J. Galvez": {"expertise": ["NETWORK", "INTERNET"], "current_load": 1, "rating": 4.8},
    "Edelfonso D. Orig I": {"expertise": ["NETWORK", "INTERNET"], "current_load": 0, "rating": 4.6},
    "Marbie A. Sumbe": {"expertise": ["NETWORK", "INTERNET"], "current_load": 2, "rating": 4.9},

    # Information Sec / User Support
    "Karenshene SD. Malvar": {"expertise": ["ACCOUNT", "SOFTWARE", "SECURITY"], "current_load": 1, "rating": 4.9},
    "Allenn Raphael F. Gutierrez": {"expertise": ["ACCOUNT", "SOFTWARE", "SECURITY"], "current_load": 2, "rating": 4.8},

    # Graphic Designer
    "Jona A. Siarot": {"expertise": ["GRAPHICS", "MULTIMEDIA"], "current_load": 1, "rating": 4.9},
    "Jerus L. De Jesus": {"expertise": ["GRAPHICS", "MULTIMEDIA"], "current_load": 2, "rating": 4.8},

    # Computer Maintenance
    "Julian G. Uy": {"expertise": ["PC_MAINTENANCE", "PRINTER", "HARDWARE"], "current_load": 2, "rating": 4.8},
    "Mark Joseph C. Sotto": {"expertise": ["PC_MAINTENANCE", "PRINTER", "HARDWARE"], "current_load": 1, "rating": 4.9},
    "Sergio Paulo B. Leoncio": {"expertise": ["PC_MAINTENANCE", "PRINTER", "HARDWARE"], "current_load": 3,
                                "rating": 4.7},
    "Aquilles S. Capili": {"expertise": ["PC_MAINTENANCE", "PRINTER", "HARDWARE"], "current_load": 2, "rating": 4.8},
    "Mark Anthony G. De Guzman": {"expertise": ["PC_MAINTENANCE", "PRINTER", "HARDWARE"], "current_load": 1,
                                  "rating": 4.9},
    "Raffy R. Del Rosario": {"expertise": ["PC_MAINTENANCE", "PRINTER", "HARDWARE"], "current_load": 2, "rating": 4.7},
    "Roel D. Tilo": {"expertise": ["PC_MAINTENANCE", "PRINTER", "HARDWARE"], "current_load": 0, "rating": 4.8},
    "Bernie L. De Jesus": {"expertise": ["PC_MAINTENANCE", "PRINTER", "HARDWARE"], "current_load": 1, "rating": 4.9},
    "Genesis De Leon Flores": {"expertise": ["PC_MAINTENANCE", "PRINTER", "HARDWARE"], "current_load": 2,
                               "rating": 4.7},
    "Christian Angelo A. Navera": {"expertise": ["PC_MAINTENANCE", "PRINTER", "HARDWARE"], "current_load": 1,
                                   "rating": 4.8},
    "Alvin John Villaseñor": {"expertise": ["PC_MAINTENANCE", "PRINTER", "HARDWARE"], "current_load": 2, "rating": 4.9},
}


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
    """Predicts task duration in hours."""
    mapped_type = get_mapped_support_type(support_type)
    base_hours = {'ACCOUNT': 1, 'NETWORK': 4, 'HARDWARE': 8, 'PC_MAINTENANCE': 8, 'SOFTWARE': 3, 'CCTV': 4, 'OTHER': 5}
    estimated_time = base_hours.get(mapped_type, 5)

    priority_multipliers = {'URGENT': 0.5, 'HIGH': 0.8, 'MEDIUM': 1.0, 'LOW': 1.5}
    multiplier = priority_multipliers.get(priority, 1.0)

    final_prediction = int(estimated_time * multiplier) + random.randint(0, 1)
    return max(1, final_prediction)


def recommend_staff(school_name, support_type):
    """
    Recommends the best staff member for the job based on their expertise.
    Filters the dictionary safely and avoids KeyErrors.
    """
    # 1. Find all staff members who match the required expertise
    eligible_staff = []

    mapped_type = get_mapped_support_type(support_type)

    for name, info in staff_db.items():
        # Check if they have the specific skill OR if they are management ("ALL")
        if mapped_type in info["expertise"] or "ALL" in info["expertise"]:
            eligible_staff.append(name)

    # 2. Fallback just in case no exact match is found
    if not eligible_staff:
        eligible_staff = list(staff_db.keys())

    # 3. Safely choose a random staff member from our filtered list
    selected_name = random.choice(eligible_staff)
    selected_info = staff_db[selected_name]

    # 4. Generate the AI reason to display on the UI
    reason = f"Matches expertise for '{support_type}'. Currently handling {selected_info['current_load']} active tickets."

    return {
        "recommended_name": selected_name,
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