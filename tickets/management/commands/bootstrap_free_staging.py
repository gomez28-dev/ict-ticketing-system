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

        self.stdout.write(self.style.HTTP_INFO("Running performance data import..."))
        try:
            call_command("import_performance")
            self.stdout.write(self.style.SUCCESS("Performance data imported successfully."))
        except CommandError as exc:
            self.stdout.write(
                self.style.WARNING(f"Performance import failed (non-fatal): {exc}")
            )
        except Exception as exc:
            self.stdout.write(
                self.style.WARNING(f"Performance import error (non-fatal): {exc}")
            )
