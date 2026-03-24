import openpyxl
from django.core.management.base import BaseCommand, CommandError
from tickets.models import School

class Command(BaseCommand):
    help = 'Imports school data directly from an Excel (.xlsx) file.'

    def add_arguments(self, parser):
        parser.add_argument('file_path', type=str, help='The path to the Excel file.')

    def handle(self, *args, **kwargs):
        file_path = kwargs['file_path']
        added_count = 0

        try:
            # Load the Excel workbook
            wb = openpyxl.load_workbook(file_path, data_only=True)
            sheet = wb.active
        except Exception as e:
            raise CommandError(f"Error opening file: {e}. Make sure you are pointing to a valid .xlsx file.")

        # Read through the rows, skipping the header (min_row=2)
        for row in sheet.iter_rows(min_row=2, values_only=True):
            # Pad the row with None just in case some trailing columns are completely empty
            row_data = list(row) + [None] * (10 - len(row))

            # --- LEFT SIDE: Secondary Schools (Columns 0, 2, 3) ---
            sec_district = row_data[0]
            sec_id = row_data[2]
            sec_name = row_data[3]

            if sec_id and sec_name:
                obj, created = School.objects.get_or_create(
                    school_id=str(sec_id).strip(),
                    defaults={
                        'name': str(sec_name).strip(),
                        'district': str(sec_district).strip() if sec_district else "Unknown"
                    }
                )
                if created: added_count += 1

            # --- RIGHT SIDE: Elementary Schools (Columns 5, 7, 8) ---
            elem_district = row_data[5]
            elem_id = row_data[7]
            elem_name = row_data[8]

            if elem_id and elem_name:
                obj, created = School.objects.get_or_create(
                    school_id=str(elem_id).strip(),
                    defaults={
                        'name': str(elem_name).strip(),
                        'district': str(elem_district).strip() if elem_district else "Unknown"
                    }
                )
                if created: added_count += 1

        self.stdout.write(self.style.SUCCESS(f'Successfully imported {added_count} schools from Excel!'))