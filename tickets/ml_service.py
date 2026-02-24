# tickets/ml_service.py
import random


def predict_ticket_duration(support_type, priority):
    """
    BASELINE PREDICTION MODEL
    Estimates task resolution time (in hours) based on complexity and priority.

    CAPSTONE UPGRADE PATH:
    Once the Division Office of Valenzuela accumulates enough historical data,
    replace this baseline logic by loading a trained XGBoost model (.pkl)
    to perform true predictive analytics based on exploratory data analysis.

    Example future implementation:
    # model = joblib.load('xgboost_duration_model.pkl')
    # return model.predict([[support_type_encoded, priority_encoded]])[0]
    """

    # 1. Base hours estimated by Support Type complexity
    base_hours = {
        'ACCOUNT': 1,  # Password resets, Google/Microsoft accounts are fast
        'NETWORK': 4,  # Connectivity issues take a bit longer
        'HARDWARE': 8,  # Physical repairs take a full day
        'SOFTWARE': 3,  # Installations and troubleshooting
        'OTHER': 5  # Default average
    }

    # Get the base time (default to 5 if support_type isn't in our dictionary)
    estimated_time = base_hours.get(support_type, 5)

    # 2. Apply a multiplier based on Priority
    # Urgent tasks are pushed to the front of the line (faster completion)
    # Low priority tasks sit in the queue longer (slower completion)
    priority_multipliers = {
        'URGENT': 0.5,
        'HIGH': 0.8,
        'MEDIUM': 1.0,
        'LOW': 1.5
    }

    multiplier = priority_multipliers.get(priority, 1.0)

    # Calculate final predicted hours (add a tiny bit of random variance for realism in the demo)
    final_prediction = int(estimated_time * multiplier) + random.randint(0, 1)

    # Ensure it never predicts 0 hours (minimum 1 hour)
    return max(1, final_prediction)