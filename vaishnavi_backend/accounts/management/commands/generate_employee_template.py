"""
Management command: generate the bulk-upload Excel template straight from
the live model definitions, using BulkEmployeeImporter's own column spec —
so the template can never drift out of sync with CustomUser / EmployeeProfile.

Usage:
    python manage.py generate_employee_template [--out employee_bulk_upload_template.xlsx]
/management/commands/generate_employee_template.py

"""
import openpyxl
from openpyxl.comments import Comment
from openpyxl.styles import Font, PatternFill
from django.core.management.base import BaseCommand

from accounts.utils import BulkEmployeeImporter  


class Command(BaseCommand):
    help = "Generate the bulk employee upload .xlsx template from the current models."

    def add_arguments(self, parser):
        parser.add_argument(
            "--out",
            default="employee_bulk_upload_template.xlsx",
            help="Output file path.",
        )

    def handle(self, *args, **options):
        # created_by is only used by the importer for row processing, not
        # for building columns, so a throwaway instance is fine here.
        from accounts.models import CustomUser

        importer = BulkEmployeeImporter.__new__(BulkEmployeeImporter)
        importer.created_by = None
        importer.user_fields = {
            f.name: f for f in BulkEmployeeImporter._iter_fields(
                CustomUser, BulkEmployeeImporter.EXCLUDED_USER_FIELDS
            )
        }
        from accounts.models import EmployeeProfile  

        importer.profile_fields = {
            f.name: f for f in BulkEmployeeImporter._iter_fields(
                EmployeeProfile, BulkEmployeeImporter.EXCLUDED_PROFILE_FIELDS
            )
        }
        columns = importer._build_columns()

        wb = openpyxl.Workbook()
        sheet = wb.active
        sheet.title = "Employees"

        header_font = Font(name="Arial", bold=True, color="FFFFFF")
        header_fill = PatternFill(start_color="305496", end_color="305496", fill_type="solid")
        example_font = Font(name="Arial", italic=True, color="808080")

        for col_idx, (key, header, target, required, help_text) in enumerate(columns, start=1):
            cell = sheet.cell(row=1, column=col_idx, value=header)
            cell.font = header_font
            cell.fill = header_fill
            if help_text:
                cell.comment = Comment(help_text, "Bulk Upload Template")
            sheet.column_dimensions[cell.column_letter].width = max(18, len(header) + 2)

        # One example row so users see the expected format (blank Action/Employee ID = create)
        example = {
            "action": "",
            "employee_id": "",
        }
        for col_idx, (key, header, target, required, help_text) in enumerate(columns, start=1):
            val = example.get(key, "")
            c = sheet.cell(row=2, column=col_idx, value=val)
            c.font = example_font

        legend = wb.create_sheet("Instructions")
        legend["A1"] = "How to use this template"
        legend["A1"].font = Font(name="Arial", bold=True, size=13)
        legend["A3"] = "• Leave 'Action' blank to auto-detect Create vs Update from Mobile Number / Employee ID."
        legend["A4"] = "• Fields marked with * are required when creating a new employee."
        legend["A5"] = "• Hover over a column header to see its format / allowed values."
        legend["A6"] = "• Leave 'Employee ID' blank when creating — it is generated automatically."
        legend["A7"] = f"• Max {BulkEmployeeImporter.MAX_ROWS} rows per upload."
        for row in range(3, 8):
            legend[f"A{row}"].font = Font(name="Arial", size=11)
        legend.column_dimensions["A"].width = 100

        wb.save(options["out"])
        self.stdout.write(self.style.SUCCESS(f"Template written to {options['out']}"))