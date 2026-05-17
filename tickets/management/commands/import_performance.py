"""
Import employee performance data from CSV files in the data/ folder.

Usage:
    python manage.py import_performance data/employee_performance.csv

CSV Format (expected columns):
    first_name, last_name, quality_score, efficiency_score, timeliness_score, overall_rating, total_tasks_done
"""
import csv
import os

from django.core.management.base import BaseCommand, CommandError
from tickets.models import User


class Command(BaseCommand):
    help = 'Import employee performance metrics from a CSV file into User model fields.'

    def add_arguments(self, parser):
        parser.add_argument('csv_path', type=str, help='Path to the CSV file (e.g., data/performance.csv)')

    def handle(self, *args, **options):
        csv_path = options['csv_path']

        if not os.path.exists(csv_path):
            raise CommandError(f"File not found: {csv_path}")

        updated = 0
        skipped = 0
        errors = 0

        self.stdout.write(self.style.HTTP_INFO(f"\n📂 Reading: {csv_path}\n"))

        with open(csv_path, newline='', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)

            # Validate required columns
            required = {'first_name', 'last_name'}
            if not required.issubset(set(reader.fieldnames or [])):
                raise CommandError(
                    f"CSV must have at least these columns: {required}. "
                    f"Found: {reader.fieldnames}"
                )

            for row_num, row in enumerate(reader, start=2):
                first = row.get('first_name', '').strip()
                last = row.get('last_name', '').strip()

                if not first or not last:
                    self.stdout.write(self.style.WARNING(f"  Row {row_num}: Skipped — missing name."))
                    skipped += 1
                    continue

                try:
                    user = User.objects.get(first_name__iexact=first, last_name__iexact=last)
                except User.DoesNotExist:
                    self.stdout.write(self.style.WARNING(
                        f"  Row {row_num}: No user found for '{first} {last}' — skipped."
                    ))
                    skipped += 1
                    continue
                except User.MultipleObjectsReturned:
                    self.stdout.write(self.style.WARNING(
                        f"  Row {row_num}: Multiple users match '{first} {last}' — skipped."
                    ))
                    skipped += 1
                    continue

                try:
                    changed = False
                    for field in ['quality_score', 'efficiency_score', 'timeliness_score', 'overall_rating']:
                        val = row.get(field, '').strip()
                        if val:
                            setattr(user, field, float(val))
                            changed = True

                    tasks_val = row.get('total_tasks_done', '').strip()
                    if tasks_val:
                        user.total_tasks_done = int(tasks_val)
                        changed = True

                    reviews_val = row.get('total_reviews', '').strip()
                    if reviews_val:
                        user.total_reviews = int(reviews_val)
                        changed = True

                    if changed:
                        user.save()
                        updated += 1
                        self.stdout.write(self.style.SUCCESS(
                            f"  ✓ {first} {last} — updated "
                            f"(Q:{user.quality_score} E:{user.efficiency_score} "
                            f"T:{user.timeliness_score} R:{user.overall_rating})"
                        ))
                    else:
                        skipped += 1
                        self.stdout.write(f"  – {first} {last} — no data columns to update.")

                except (ValueError, TypeError) as e:
                    errors += 1
                    self.stdout.write(self.style.ERROR(f"  ✗ Row {row_num} ({first} {last}): {e}"))

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS(f"✅ Done. Updated: {updated} | Skipped: {skipped} | Errors: {errors}"))
