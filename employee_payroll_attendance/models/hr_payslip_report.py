from odoo import fields, models, api
import logging
from datetime import timedelta
import json


_logger = logging.getLogger(__name__)


class HrAttendance(models.Model):
    _inherit = "hr.attendance"

    approved = fields.Boolean(string="Approved", default=False)
    approved_by = fields.Many2one("res.users", string="Approved By", readonly=True)

    approved_by = fields.Many2one("res.users", string="Approved By", readonly=True)
    
    

    def toggle_approval(self):
        """Toggle the approval status of the attendance and update related payslip if applicable."""
        for record in self:
            record.approved = not record.approved
            _logger.info(
                f"Toggled approval for {record.employee_id.name} on {record.check_in} to {record.approved}"
            )

            # Find and update the related payslip
            payslip = self.env["hr.payslip"].search(
                [
                    ("employee_id", "=", record.employee_id.id),
                    ("date_from", "<=", record.check_in.date()),
                    ("date_to", ">=", record.check_out.date()),
                ],
                limit=1,
            )

            if payslip:
                payslip._compute_worked_hours()
                payslip._compute_total_salary()
                payslip._compute_additional_fields()
                _logger.info(
                    f"Recomputed fields for payslip of {record.employee_id.name}"
                )

    def approve_attendance(self):
        """Set the approved status to True."""
        for record in self:
            record.approved = True
            _logger.info(
                f"Approved attendance for {record.employee_id.name} on {record.check_in}"
            )

    def action_view_details(self):
        """Opens the popup view showing timesheets related to the selected attendance."""
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": "Attendance and Timesheet Details",
            "view_mode": "form",
            "res_model": "attendance.timesheet.details",
            "target": "new",
            "context": {
                "default_employee_id": self.employee_id.id,
                "default_date": self.check_in.date(),
                "default_check_in": self.check_in,
                "default_check_out": self.check_out,
                "default_worked_hours": self.worked_hours,
            },
        }


class HrPayslipReport(models.Model):
    _name = "hr.payslip.report"
    _description = "Employee Payslip Report"

    employee_id = fields.Many2one("hr.employee", string="Employee", required=True)
    date_from = fields.Date(string="Start Date", required=True)
    date_to = fields.Date(string="End Date", required=True)
    worked_hours = fields.Float(string="Worked Hours")
    total_working_days = fields.Integer(string="Total Working Days")
    total_working_hours = fields.Float(string="Total Working Hours")
    approved_working_hours = fields.Float(string="Approved Working Hours")
    total_salary = fields.Float(string="Total Salary")
    converted_salary_vnd = fields.Float(string="Salary in VND", store=True)
    monthly_wage_vnd = fields.Float(string="Monthly Wage (VND)")
    hourly_rate_vnd = fields.Float(
        string="Hourly Rate (VND)", help="Hourly rate in VND."
    )

    # New fields for additional allowances and bonuses
    insurance = fields.Float(string="Insurance", readonly=True)
    meal_allowance = fields.Float(string="Meal Allowance", readonly=True)
    kpi_bonus = fields.Float(string="KPI Bonus", readonly=True)
    other_bonus = fields.Float(string="Other Bonus", readonly=True)

    insurance_vnd = fields.Float(string="Insurance (VND)", readonly=True)
    meal_allowance_vnd = fields.Float(string="Meal Allowance (VND)", readonly=True)
    kpi_bonus_vnd = fields.Float(string="KPI Bonus (VND)", readonly=True)
    other_bonus_vnd = fields.Float(string="Other Bonus (VND)", readonly=True)

    # New One2many field for related attendance records
    attendance_ids = fields.One2many(
        "hr.payslip.report.attendance",
        "payslip_report_id",
        string="Attendance Records",
        readonly=True,
    )
    attendance_line_ids = fields.One2many(
        "hr.payslip.attendance",
        "payslip_id",
        string="Attendance Records",
        readonly=True,
    )

    status = fields.Selection(
        [
            ("draft", "Draft"),
            ("generated", "Payslip Generated"),
            ("employee_confirm", "Employee Confirm"),
            ("transfer_payment", "Transfer Payment"),
            ("done", "Done"),
        ],
        default="draft",
        string="Status",
    )
    probation_start_date = fields.Date(string="Probation Start Date")
    probation_end_date = fields.Date(string="Probation End Date")
    probation_percentage = fields.Float(string="Probation Percentage", default=85.0)
    probation_hours = fields.Float(string="Approved Hours (Probation)", store=True)
    probation_salary = fields.Float(string="Salary (Probation)", store=True)

    def action_employee_confirm(self):
        # Find the related hr.payslip record based on the employee and date range
        related_payslip = self.env["hr.payslip"].search(
            [
                ("employee_id", "=", self.employee_id.id),
                ("date_from", "=", self.date_from),
                ("date_to", "=", self.date_to),
            ],
            limit=1,
        )

        if related_payslip:
            related_payslip.action_employee_confirm()


class HrPayslipReportAttendance(models.Model):
    _name = "hr.payslip.report.attendance"
    _description = "Payslip Report Attendance"

    payslip_report_id = fields.Many2one(
        "hr.payslip.report", string="Payslip Report", ondelete="cascade"
    )
    date = fields.Date(string="Date")
    check_in = fields.Datetime(string="Check In")
    check_out = fields.Datetime(string="Check Out")
    worked_hours = fields.Float(string="Worked Hours")
    approved = fields.Boolean(string="Approved", readonly=True)


class HrEmployee(models.Model):
    _inherit = "hr.employee"

    payslip_ids = fields.One2many(
        "hr.payslip", "employee_id", string="Payslips"
    )

    payslip_report_ids = fields.One2many(
        "hr.payslip.report", "employee_id", string="Payslip Reports"
    )

    def action_generate_payslip(self):
        """Generate a payslip for the current month for each selected employee."""
        for employee in self:
            today = fields.Date.context_today(self)
            first_day_of_month = today.replace(day=1)
            last_day_of_month = (first_day_of_month + timedelta(days=32)).replace(
                day=1
            ) - timedelta(days=1)

            payslip = self.env["hr.payslip"].create(
                {
                    "employee_id": employee.id,
                    "date_from": first_day_of_month,
                    "date_to": last_day_of_month,
                    "wage": employee.contract_id.wage if employee.contract_id else 0.0,
                }
            )
            payslip._compute_worked_hours()
            payslip._compute_total_salary()
            payslip._compute_additional_fields()
            _logger.info(
                f"Payslip generated for {employee.name} for the month starting {payslip.date_from}"
            )


class AttendanceTimesheetDetails(models.TransientModel):
    _name = "attendance.timesheet.details"
    _description = "Attendance and Timesheet Details"

    employee_id = fields.Many2one("hr.employee", string="Employee", readonly=True)
    date = fields.Date(string="Date", readonly=True)
    check_in = fields.Datetime(string="Check In", readonly=True)
    check_out = fields.Datetime(string="Check Out", readonly=True)
    worked_hours = fields.Float(string="Worked Hours", readonly=True)
    timesheet_html = fields.Html(
        string="Timesheet Details", compute="_compute_timesheet_html", readonly=True
    )
    approved = fields.Boolean(
        string="Approved", compute="_compute_approved", readonly=True
    )

    @api.depends("date", "employee_id")
    def _compute_timesheet_html(self):
        for record in self:
            timesheets = self.env["account.analytic.line"].search(
                [
                    ("date", "=", record.date),
                    ("employee_id", "=", record.employee_id.id),
                ]
            )
            if timesheets:
                html_content = "<table class='o_list_view table table-condensed'>"
                html_content += """
                <thead>
                    <tr>
                    <th>Date</th>
                    <th>Project</th>
                    <th>Task</th>
                    <th>Description</th>
                    <th>Hours Spent</th>
                    </tr>
                    </thead>
                    <tbody>
                """
                for timesheet in timesheets:
                    html_content += f"""
                    <tr>
                    <td>{timesheet.date}</td>
                    <td>{timesheet.project_id.name or ''}</td>
                    <td>{timesheet.task_id.name or ''}</td>
                    <td>{timesheet.name or ''}</td>
                    <td>{timesheet.unit_amount}</td>
                    </tr>
                    """
                html_content += "</tbody></table>"
            else:
                html_content = "<p>No timesheet records found for this date.</p>"
            record.timesheet_html = html_content

    @api.depends("employee_id", "check_in", "check_out")
    def _compute_approved(self):
        for record in self:
            attendance = self.env["hr.attendance"].search(
                [
                    ("employee_id", "=", record.employee_id.id),
                    ("check_in", "=", record.check_in),
                    ("check_out", "=", record.check_out),
                ],
                limit=1,
            )
            record.approved = attendance.approved if attendance else False

    def action_toggle_approval(self):
        """Toggle approval for the associated attendance record."""
        attendance = self.env["hr.attendance"].search(
            [
                ("employee_id", "=", self.employee_id.id),
                ("check_in", "=", self.check_in),
                ("check_out", "=", self.check_out),
            ],
            limit=1,
        )
        if attendance:
            attendance.toggle_approval()
        else:
            raise ValueError("No matching attendance record found.")


class AttendanceTimesheetLine(models.TransientModel):
    _name = "attendance.timesheet.line"
    _description = "Attendance Timesheet Line"

    details_id = fields.Many2one("attendance.timesheet.details", string="Details")
    date = fields.Date(string="Date")
    project_id = fields.Many2one("project.project", string="Project")
    task_id = fields.Many2one("project.task", string="Task")
    description = fields.Char(string="Description")
    hours_spent = fields.Float(string="Hours Spent")
