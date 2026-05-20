import os
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.management import BaseCommand, call_command, CommandError


def env_bool(name, default=False):
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


class Command(BaseCommand):
    help = "Bootstrap free staging deploys (superuser + optional school import + optional performance import)."

    def handle(self, *args, **options):
        self._ensure_superuser()
        self._import_schools_if_enabled()
        self._import_performance_if_enabled()
        self._sync_staff_expertise()
        self._ensure_test_accounts()
        self._cleanup_historical_notes()

    def _ensure_superuser(self):
        username = os.environ.get("DJANGO_SUPERUSER_USERNAME")
        email = os.environ.get("DJANGO_SUPERUSER_EMAIL")
        password = os.environ.get("DJANGO_SUPERUSER_PASSWORD")
        role = os.environ.get("DJANGO_SUPERUSER_ROLE", "ADMIN")

        if not username or not email or not password:
            self.stdout.write(
                self.style.WARNING(
                    "Skipping superuser bootstrap: set DJANGO_SUPERUSER_USERNAME, "
                    "DJANGO_SUPERUSER_EMAIL, and DJANGO_SUPERUSER_PASSWORD."
                )
            )
            return

        user_model = get_user_model()
        user, created = user_model.objects.get_or_create(
            username=username,
            defaults={
                "email": email,
            },
        )
        user.email = email
        user.is_superuser = True
        user.is_staff = True
        if hasattr(user, "role"):
            user.role = role
        user.set_password(password)
        user.save()

        if created:
            self.stdout.write(self.style.SUCCESS(f"Created superuser '{username}'"))
        else:
            self.stdout.write(self.style.SUCCESS(f"Updated superuser '{username}'"))

    def _import_schools_if_enabled(self):
        if not env_bool("BOOTSTRAP_IMPORT_SCHOOLS", default=True):
            self.stdout.write("Skipping school import (BOOTSTRAP_IMPORT_SCHOOLS disabled).")
            return

        school_file = os.environ.get("BOOTSTRAP_SCHOOLS_FILE", "schools.xlsx")
        school_path = Path(school_file)
        if not school_path.exists():
            self.stdout.write(
                self.style.WARNING(
                    f"Skipping school import: '{school_file}' not found in deploy root."
                )
            )
            return

        try:
            call_command("import_schools", school_file)
        except CommandError as exc:
            raise CommandError(f"School import failed: {exc}") from exc

    def _import_performance_if_enabled(self):
        if not env_bool("BOOTSTRAP_IMPORT_PERFORMANCE", default=False):
            self.stdout.write("Skipping performance import (BOOTSTRAP_IMPORT_PERFORMANCE disabled).")
            return

        self.stdout.write(self.style.WARNING("!!! STARTING EMPLOYEE IMPORT SCRIPT !!!"))
        call_command("import_performance")
        self.stdout.write(self.style.SUCCESS("Performance data imported successfully."))

    def _sync_staff_expertise(self):
        from tickets.staff_data import STAFF_LIST
        from tickets.models import User
        
        users = User.objects.filter(is_staff=True)
        updated_count = 0
        
        for staff in STAFF_LIST:
            staff_name_lower = staff['name'].lower()
            for u in users:
                u_first = (u.first_name or '').lower()
                u_last = (u.last_name or '').lower()
                
                db_full_name = f"{u_first} {u_last}".strip()
                if db_full_name == staff_name_lower or (u_first and u_last and u_first in staff_name_lower and u_last in staff_name_lower):
                    expertise_str = ", ".join(staff['expertise'])
                    u.expertise = expertise_str
                    u.save(update_fields=['expertise'])
                    updated_count += 1
                    break
                    
        self.stdout.write(self.style.SUCCESS(f"Successfully synced expertise tags for {updated_count} employees."))

    def _ensure_test_accounts(self):
        from tickets.models import User
        from django.contrib.auth.hashers import make_password
        from django.db import transaction

        test_accounts = [
            {
                'email': 'ramon.sy@email.com',
                'username': 'ramon.sy',
                'first_name': 'Ramon',
                'last_name': 'Sy',
                'role': 'ADMIN',
                'is_staff': True,
                'is_superuser': True,
                'password': 'super123'
            },
            {
                'email': 'alice.tan@email.com',
                'username': 'alice.tan',
                'first_name': 'Alice',
                'last_name': 'Tan',
                'role': 'ADMIN',
                'is_staff': True,
                'is_superuser': False,
                'password': 'admin123'
            },
            {
                'email': 'juan.pedro@email.com',
                'username': 'juan.pedro',
                'first_name': 'Juan',
                'last_name': 'Pedro',
                'role': 'MEMBER',
                'is_staff': True,
                'is_superuser': False,
                'password': 'emp123',
                'expertise': 'SYSTEM TESTING, ALL'
            }
        ]

        with transaction.atomic():
            for acc in test_accounts:
                # Remove duplicate accounts under new username/email that might conflict
                duplicates = User.objects.filter(email__iexact=acc['email']).exclude(username__iexact=acc['username'])
                for dup in duplicates:
                    dup.delete()

                user = User.objects.filter(email__iexact=acc['email']).first()
                if not user:
                    user = User.objects.filter(username__iexact=acc['username']).first()

                if not user:
                    user = User.objects.create(
                        username=acc['username'],
                        email=acc['email'],
                        first_name=acc['first_name'],
                        last_name=acc['last_name'],
                        role=acc['role'],
                        is_staff=acc['is_staff'],
                        is_superuser=acc['is_superuser'],
                    )
                    user.set_password(acc['password'])
                    if 'expertise' in acc:
                        user.expertise = acc['expertise']
                    user.save()
                    self.stdout.write(self.style.SUCCESS(f"Created test account: {acc['email']}"))
                else:
                    # Update details
                    user.first_name = acc['first_name']
                    user.last_name = acc['last_name']
                    user.role = acc['role']
                    user.is_staff = acc['is_staff']
                    user.is_superuser = acc['is_superuser']
                    if 'expertise' in acc and 'ALL' not in (user.expertise or ''):
                        user.expertise = acc['expertise']
                    user.save()
                    self.stdout.write(self.style.SUCCESS(f"Updated test account: {acc['email']}"))

    def _cleanup_historical_notes(self):
        from tickets.models import Ticket, PerformanceReview

        replacements = [
            ("Test Employee", "Juan Pedro"),
            ("testemployee", "Juan Pedro"),
            ("Test Superadmin", "Ramon Sy"),
            ("Test Admin", "Alice Tan"),
        ]

        ticket_count = 0
        for old_str, new_str in replacements:
            for ticket in Ticket.objects.filter(admin_notes__contains=old_str):
                ticket.admin_notes = ticket.admin_notes.replace(old_str, new_str)
                ticket.save(update_fields=['admin_notes'])
                ticket_count += 1

        review_count = 0
        for old_str, new_str in replacements:
            for review in PerformanceReview.objects.filter(notes__contains=old_str):
                review.notes = review.notes.replace(old_str, new_str)
                review.save(update_fields=['notes'])
                review_count += 1

        if ticket_count > 0 or review_count > 0:
            self.stdout.write(self.style.SUCCESS(
                f"Successfully cleaned up historical notes: {ticket_count} tickets, {review_count} reviews."
            ))
        else:
            self.stdout.write(self.style.SUCCESS("No historical notes needed cleanup."))
