from odoo import models, fields, api
from datetime import timedelta, datetime


class HrPayslip(models.Model):
    _inherit = "hr.payslip"

    @api.onchange("full_monthly_fix_price")
    def _onchange_full_monthly_fix_price(self):
        self._generate_attendance_for_full_month()

    def _generate_attendance_for_full_month(self):
        if self.full_monthly_fix_price and self.date_from and self.date_to:
            Attendance = self.env["hr.attendance"]
            existing_days = set(
                a.check_in.date() for a in self.attendance_ids if a.check_in
            )

            start_date = fields.Date.from_string(self.date_from)
            end_date = fields.Date.from_string(self.date_to)
            delta = end_date - start_date

            for i in range(delta.days + 1):
                current_day = start_date + timedelta(days=i)
                if current_day.weekday() >= 5:
                    continue
                if current_day not in existing_days:
                    Attendance.create(
                        {
                            "employee_id": self.employee_id.id,
                            "check_in": datetime.combine(
                                current_day, datetime.min.time()
                            )
                            + timedelta(hours=1),
                            "check_out": datetime.combine(
                                current_day, datetime.min.time()
                            )
                            + timedelta(hours=9),
                        }
                    )
