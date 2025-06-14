from odoo import models, fields, api
from datetime import datetime


class GenerateSalaryWizard(models.TransientModel):
    _name = "generate.salary.wizard"
    _description = "Generate Salary for All Employees"

    month = fields.Selection(
        [(str(n), datetime(2024, n, 1).strftime("%B")) for n in range(1, 13)],
        string="Month",
        required=True,
    )
    year = fields.Integer(string="Year", default=datetime.now().year, required=True)

    def generate_salaries(self):
        # Get selected month and year
        month = int(self.month)
        year = self.year
        date_from = datetime(year, month, 1)
        date_to = (
            datetime(year, month + 1, 1) - timedelta(days=1)
            if month < 12
            else datetime(year, 12, 31)
        )

        # Fetch all employees
        employees = self.env["hr.employee"].search([])

        for employee in employees:
            # Get the previous month's payslip if it exists
            prev_payslip = self.env["hr.payslip"].search(
                [
                    ("employee_id", "=", employee.id),
                    ("date_from", "<", date_from),
                    ("date_to", "<", date_from),
                ],
                limit=1,
                order="date_to desc",
            )

            # Use the previous salary if available, otherwise default to 0
            prev_salary = prev_payslip.total_salary if prev_payslip else 0.0

            # Create new payslip for the selected month
            new_payslip = self.env["hr.payslip"].create(
                {
                    "employee_id": employee.id,
                    "date_from": date_from,
                    "date_to": date_to,
                    "wage": prev_salary,
                    "status": "generated",
                }
            )

            # Auto-approve attendance records matching the timesheet
            attendances = self.env["hr.attendance"].search(
                [
                    ("employee_id", "=", employee.id),
                    ("check_in", ">=", date_from),
                    ("check_out", "<=", date_to),
                ]
            )
            for attendance in attendances:
                # Check if there is a matching timesheet record
                timesheet = self.env["account.analytic.line"].search(
                    [
                        ("employee_id", "=", employee.id),
                        ("date", "=", attendance.check_in.date()),
                    ]
                )
                if timesheet:
                    attendance.approved = True

        return {"type": "ir.actions.client", "tag": "reload"}
