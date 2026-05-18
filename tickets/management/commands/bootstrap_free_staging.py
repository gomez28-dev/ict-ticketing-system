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
