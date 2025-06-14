from odoo import models, fields, api
import logging

_logger = logging.getLogger(__name__)


class PayslipAttendance(models.Model):
    _name = "payslip.attendance"
    _description = "Payslip Attendance"

    payslip_id = fields.Many2one(
        "hr.payslip", string="Payslip", required=True, ondelete="cascade"
    )
    employee_id = fields.Many2one("hr.employee", string="Employee", required=True)
    attendance_date = fields.Date(string="Attendance Date", required=True)
    check_in = fields.Datetime(string="Check In")
    check_out = fields.Datetime(string="Check Out")
    worked_hours = fields.Float(
        string="Worked Hours", compute="_compute_worked_hours", store=True
    )
    approval_status = fields.Selection(
        [("yes", "Approved"), ("no", "Not Approved")],
        string="Approval Status",
        required=True,
        default="no",
    )

    @api.depends("check_in", "check_out")
    def _compute_worked_hours(self):
        for record in self:
            if record.check_in and record.check_out:
                duration = record.check_out - record.check_in
                record.worked_hours = duration.total_seconds() / 3600.0
            else:
                record.worked_hours = 0.0
    
    def write(self, vals):
        res = super().write(vals)
        if 'approval_status' in vals:
            for rec in self:
                if rec.employee_id:
                    rec.employee_id._compute_attendance_rate()
        return res




    @api.model
    def create_attendance_records(self, payslip_id, employee_id, attendance_data):
        """
        Method to create attendance records for a payslip.

        :param payslip_id: ID of the payslip.
        :param employee_id: ID of the employee.
        :param attendance_data: List of dictionaries with keys 'date', 'check_in', 'check_out', and 'approval_status'.
        :return: List of created attendance record IDs.
        """
        records = []
        for record in attendance_data:
            new_record = self.create(
                {
                    "payslip_id": payslip_id,
                    "employee_id": employee_id,
                    "attendance_date": record["date"],
                    "check_in": record.get("check_in"),
                    "check_out": record.get("check_out"),
                    "approval_status": record.get("approval_status", "no"),
                }
            )
            records.append(new_record.id)

        # Log all records in the payslip.attendance table
        all_records = self.search([])
        for rec in all_records:
            _logger.info(
                f"Payslip Attendance Record: Payslip ID: {rec.payslip_id.id}, Employee ID: {rec.employee_id.id}, "
                f"Attendance Date: {rec.attendance_date}, Check In: {rec.check_in}, Check Out: {rec.check_out}, "
                f"Worked Hours: {rec.worked_hours}, Approval Status: {rec.approval_status}"
            )

        return records

    @api.model
    def get_attendance_records(self, payslip_id):
        """
        Fetch all attendance records for a given payslip.

        :param payslip_id: ID of the payslip.
        :return: Recordset of attendance records.
        """
        return self.search([("payslip_id", "=", payslip_id)])
    @api.model
    def get_excess_leave_days(self, employee, date_from, date_to, allowed_leave_days=12):
        leave_model = self.env['hr.leave']
        leaves = leave_model.search([
            ('employee_id', '=', employee.id),
            ('request_date_from', '<=', date_to),
            ('request_date_to', '>=', date_from),
            ('state', '=', 'validate'),
            ('holiday_status_id.limit', '=', False),  # bỏ qua phép không giới hạn
        ])
        total_days = sum(leaves.mapped('number_of_days'))
        excess_days = max(0, total_days - allowed_leave_days)
        _logger.info(f"[EXCESS LEAVE] {employee.name}: nghỉ {total_days} ngày, vượt {excess_days} ngày")
        return excess_days





# # Example Usage:
# # Create attendance records for a payslip.
# # attendance_data = [
# #     {'date': '2023-12-01', 'check_in': '2023-12-01 08:30:00', 'check_out': '2023-12-01 17:30:00', 'approval_status': 'yes'},
# #     {'date': '2023-12-02', 'check_in': '2023-12-02 09:00:00', 'check_out': '2023-12-02 18:00:00', 'approval_status': 'no'}
# # ]
# # env['payslip.attendance'].create_attendance_records(payslip_id=1, employee_id=3, attendance_data=attendance_data)
