"""
Import employee performance data and task history from CSVs exported from
the 'ICT HELPDESK DATA.xlsx' workbook.

Usage:
    python manage.py import_performance

Expected files in data/ folder:
    - employee_performance.csv  (headers: Employee, Tasks Done, Quality (%), Efficiency (%), Timeliness (%), Overall (5))
    - employee_task_history.csv (headers: Employee, Task Type, School, District)
"""
import csv
import os
import re

from django.core.management.base import BaseCommand
from django.contrib.auth.hashers import make_password
from django.utils import timezone

from tickets.models import User, Ticket


# Map CSV task type strings to Ticket.SupportType values
TASK_TYPE_MAP = {
    'cctv maintenance': 'CCTV',
    'cctv': 'CCTV',
    'computer maintenance': 'PC_MAINTENANCE',
    'network maintenance': 'NETWORK_MAINTENANCE',
    'network support': 'NETWORK_MAINTENANCE',
    'software support': 'OTHER',
    'other support': 'OTHER',
    'password reset': 'PASSWORD_RESET',
    'account / password support': 'PASSWORD_RESET',
    'account/password support': 'PASSWORD_RESET',
}


def parse_name(full_name):
    """
    Parse 'MARVIN M. CRUZ' into (first_name, last_name).
    Strategy: first token = first name, last token = last name.
    Middle initials/tokens are discarded.
    Handles special cases like 'ROLANDO JR. O. DE CASTRO'.
    """
    parts = full_name.strip().split()
    if not parts:
        return '', ''
    if len(parts) == 1:
        return parts[0].title(), ''

    first = parts[0].title()
    # Handle 'JR.' as part of first name
    idx = 1
    if idx < len(parts) and parts[idx].upper().rstrip('.') in ('JR', 'SR', 'II', 'III', 'IV'):
        first = f"{first} {parts[idx].title()}"
        idx += 1

    last = ' '.join(parts[-1:]).title()
    # Handle compound last names like 'DE CASTRO', 'DE GUZMAN', 'DE JESUS'
    for i in range(len(parts) - 2, idx - 1, -1):
        if parts[i].upper() in ('DE', 'DEL', 'DELA', 'SAN', 'VAN', 'LOS'):
            last = ' '.join(p.title() for p in parts[i:])
            break

    return first, last


def make_username(first, last):
    """Generate a clean username from first+last name."""
    base = f"{first}.{last}".lower().replace(' ', '')
    # Remove non-alphanumeric except dots
    base = re.sub(r'[^a-z0-9.]', '', base)
    return base or 'employee'


class Command(BaseCommand):
    help = 'Import employee performance metrics and task history from CSVs in data/ folder.'

    def _find_file(self, data_dir, keyword):
        """Scan data/ for a CSV file whose name contains the keyword (case-insensitive)."""
        keyword_lower = keyword.lower()
        for fname in os.listdir(data_dir):
            if keyword_lower in fname.lower() and fname.lower().endswith('.csv'):
                return os.path.join(data_dir, fname)
        return None

    def handle(self, *args, **options):
        data_dir = os.path.join(os.path.dirname(os.path.dirname(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))))), 'data')

        if not os.path.isdir(data_dir):
            self.stderr.write(self.style.ERROR(f"Data directory not found: {data_dir}"))
            return

        perf_path = self._find_file(data_dir, 'PERFORMANCE')
        task_path = self._find_file(data_dir, 'TASK HISTORY')

        if not perf_path:
            self.stderr.write(self.style.ERROR("No CSV with 'PERFORMANCE' in name found in data/ folder."))
            return
        if not task_path:
            self.stderr.write(self.style.ERROR("No CSV with 'TASK HISTORY' in name found in data/ folder."))
            return

        self.stdout.write(f"  Found performance file: {os.path.basename(perf_path)}")
        self.stdout.write(f"  Found task history file: {os.path.basename(task_path)}")

        # ── Phase 1: Import Performance & Create Users ──
        self.stdout.write(self.style.HTTP_INFO("\n[Phase 1] Importing Employee Performance...\n"))
        user_cache = {}  # full_name_upper -> User object
        created_count = 0
        updated_count = 0

        with open(perf_path, newline='', encoding='utf-8-sig') as f:
            for row in csv.DictReader(f):
                name = row.get('Employee', '').strip()
                if not name:
                    continue

                first, last = parse_name(name)
                if not first:
                    continue

                # Try to find existing user
                user = None
                try:
                    user = User.objects.get(first_name__iexact=first, last_name__iexact=last)
                except User.DoesNotExist:
                    pass
                except User.MultipleObjectsReturned:
                    user = User.objects.filter(
                        first_name__iexact=first, last_name__iexact=last
                    ).first()

                if not user:
                    username = make_username(first, last)
                    # Ensure unique username
                    base_username = username
                    counter = 1
                    while User.objects.filter(username=username).exists():
                        username = f"{base_username}{counter}"
                        counter += 1

                    user = User.objects.create(
                        username=username,
                        first_name=first,
                        last_name=last,
                        email=f"{username}@ict.deped.gov.ph",
                        role='MEMBER',
                        is_staff=True,
                        password=make_password('Employee123!'),
                    )
                    created_count += 1
                    self.stdout.write(self.style.SUCCESS(f"  + Created user: {first} {last} ({username})"))

                # Update performance metrics
                try:
                    tasks_done = int(float(row.get('Tasks Done', '0').strip() or '0'))
                    quality = float(row.get('Quality (%)', '0').strip() or '0')
                    efficiency = float(row.get('Efficiency (%)', '0').strip() or '0')
                    timeliness = float(row.get('Timeliness (%)', '0').strip() or '0')
                    overall = float(row.get('Overall (5)', '0').strip() or '0')

                    # Quality/Efficiency/Timeliness are 0-100 in CSV, store as 0-5 scale
                    user.quality_score = round(quality / 20, 2)
                    user.efficiency_score = round(efficiency / 20, 2)
                    user.timeliness_score = round(timeliness / 20, 2)
                    user.overall_rating = round(overall, 2)
                    user.total_tasks_done = tasks_done
                    user.total_reviews = tasks_done  # Use tasks as proxy for reviews
                    user.save()
                    updated_count += 1

                    self.stdout.write(
                        f"  > {first} {last} -- Q:{user.quality_score} "
                        f"E:{user.efficiency_score} T:{user.timeliness_score} "
                        f"R:{user.overall_rating} Tasks:{tasks_done}"
                    )
                except (ValueError, TypeError) as e:
                    self.stderr.write(self.style.ERROR(f"  X {name}: {e}"))

                user_cache[name.upper()] = user

        self.stdout.write(self.style.SUCCESS(
            f"\n  Users created: {created_count} | Updated: {updated_count}\n"
        ))

        # ── Phase 2: Import Task History as Completed Tickets ──
        self.stdout.write(self.style.HTTP_INFO("[Phase 2] Importing Task History as Tickets...\n"))
        tickets_created = 0
        tickets_skipped = 0

        with open(task_path, newline='', encoding='utf-8-sig') as f:
            for row in csv.DictReader(f):
                emp_name = row.get('Employee', '').strip()
                task_type = row.get('Task Type', '').strip()
                school = row.get('School', '').strip()
                district = row.get('District', '').strip()

                if not emp_name or not task_type or task_type.lower() == 'no task':
                    tickets_skipped += 1
                    continue

                # Clean encoding artifacts
                school = school.replace('\ufffd', '').strip()
                district = district.replace('\ufffd', '').strip()

                if not school or school in ('—', '-', '�'):
                    tickets_skipped += 1
                    continue

                # Find the user from cache
                user = user_cache.get(emp_name.upper())
                if not user:
                    first, last = parse_name(emp_name)
                    try:
                        user = User.objects.get(first_name__iexact=first, last_name__iexact=last)
                        user_cache[emp_name.upper()] = user
                    except (User.DoesNotExist, User.MultipleObjectsReturned):
                        self.stdout.write(self.style.WARNING(
                            f"  ! No user for '{emp_name}' -- skipping ticket."
                        ))
                        tickets_skipped += 1
                        continue

                # Map task type to SupportType
                support_type = TASK_TYPE_MAP.get(task_type.lower(), 'OTHER')

                # Build descriptive admin_notes for the employee matching query
                user_full_name = f"{user.first_name} {user.last_name}"

                ticket = Ticket.objects.create(
                    title=f"{task_type} - {school}",
                    description=f"Completed {task_type} at {school}, {district}.",
                    status='COMPLETED',
                    support_type=support_type,
                    school_name=school,
                    school_district=district,
                    first_name=user.first_name,
                    last_name=user.last_name,
                    assignee=user,
                    admin_notes=f"Assigned to: {user_full_name}",
                    actual_completion_date=timezone.now(),
                )
                tickets_created += 1
                self.stdout.write(f"  > {ticket.ticket_number} -> {user_full_name} | {task_type} @ {school}")

        self.stdout.write(self.style.SUCCESS(
            f"\n  Tickets created: {tickets_created} | Skipped: {tickets_skipped}"
        ))
        self.stdout.write(self.style.SUCCESS("\nImport complete!\n"))
