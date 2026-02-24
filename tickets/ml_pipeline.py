import os
import django
import pandas as pd
from sklearn.ensemble import GradientBoostingRegressor
from sklearn.model_selection import train_test_split
import joblib

# Setup Django environment so this script can talk to your database
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from tickets.models import Ticket


def train_duration_model():
    print("Fetching historical ticket data...")
    # 1. Gather all 'DONE' tickets that have completion dates
    completed_tickets = Ticket.objects.filter(status='DONE', actual_completion_date__isnull=False)

    if completed_tickets.count() < 5:
        print("Not enough completed tickets to train the AI. Please add more 'Done' test tickets!")
        return

    # 2. Extract features (Complexity, Priority) and target (Duration)
    data = []
    for ticket in completed_tickets:
        # Calculate duration in hours
        duration = (ticket.actual_completion_date - ticket.created_at).total_seconds() / 3600

        # Convert text priority to a numerical weight
        priority_map = {'LOW': 1, 'MEDIUM': 2, 'HIGH': 3, 'URGENT': 4}
        priority_weight = priority_map.get(ticket.priority, 2)

        data.append({
            'complexity': ticket.complexity,
            'priority': priority_weight,
            'duration_hours': duration
        })

    df = pd.DataFrame(data)

    # 3. Prepare data for scikit-learn
    X = df[['complexity', 'priority']]  # What the AI looks at
    y = df['duration_hours']  # What the AI tries to predict

    # 4. Train a Gradient Boosting Model
    print("Training predictive model...")
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)
    model = GradientBoostingRegressor(n_estimators=100, learning_rate=0.1, max_depth=3, random_state=42)
    model.fit(X_train, y_train)

    # 5. Save the trained model to a file
    joblib.dump(model, 'ticket_predictor.pkl')
    print("Model trained and saved successfully as 'ticket_predictor.pkl'!")


if __name__ == "__main__":
    train_duration_model()