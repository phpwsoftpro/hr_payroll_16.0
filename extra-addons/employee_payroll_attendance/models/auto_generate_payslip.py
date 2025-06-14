from datetime import timedelta
import logging
from odoo import models, fields, api, SUPERUSER_ID
from dateutil.relativedelta import relativedelta
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class HrAttendance(models.Model):
    _inherit = "hr.attendance"

    @api.model
    def create(self, vals):
        record = super().create(vals)

        if not record:
            return record

        today = fields.Date.today()
        first_day_current_month = today.replace(day=1)
        last_day_current_month = (
            first_day_current_month + relativedelta(months=1)
        ) - timedelta(days=1)

        employee = record.employee_id

        existing_payslip = (
            self.env["hr.payslip"]
            .with_user(SUPERUSER_ID)
            .search(
                [
                    ("employee_id", "=", employee.id),
                    ("date_from", "=", first_day_current_month),
                    ("date_to", "=", last_day_current_month),
                ],
                limit=1,
            )
        )

        if existing_payslip:
            if existing_payslip.status != "done":
                existing_payslip._auto_update_attendance_records()
                existing_payslip._onchange_salary_fields()
                existing_payslip._onchange_bonus_vnd()
                _logger.info(
                    f"Attendances updated for existing payslip {existing_payslip.id} (Employee: {employee.name})"
                )
            else:
                _logger.info(
                    f"Payslip {existing_payslip.id} already finalized. No update applied."
                )
            return record

        # Nếu chưa có payslip, thì thực hiện tạo mới từ tháng trước
        payslip_last_month = (
            self.env["hr.payslip"]
            .with_user(SUPERUSER_ID)
            .search(
                [
                    ("employee_id", "=", employee.id),
                    (
                        "date_from",
                        "=",
                        first_day_current_month - relativedelta(months=1),
                    ),
                    ("date_to", "=", first_day_current_month - timedelta(days=1)),
                ],
                limit=1,
            )
        )

        if payslip_last_month:
            try:
                new_payslip = payslip_last_month.copy(
                    {
                        "date_from": first_day_current_month,
                        "date_to": last_day_current_month,
                        "currency_rate_fallback": payslip_last_month.currency_rate_fallback,
                        "status": "draft",
                    }
                )
                new_payslip._auto_update_attendance_records()
                new_payslip._onchange_salary_fields()
                new_payslip._onchange_bonus_vnd()
                _logger.info(
                    f"Payslip duplicated successfully for Employee: {employee.name}"
                )
            except Exception as e:
                _logger.error(
                    f"Error duplicating payslip for Employee ID {employee.id}: {str(e)}"
                )
        else:
            # Create brand new payslip if last month payslip not found
            try:
                new_payslip = self.env["hr.payslip"].create(
                    {
                        "employee_id": employee.id,
                        "date_from": first_day_current_month,
                        "date_to": last_day_current_month,
                    }
                )
                new_payslip._auto_update_attendance_records()
                new_payslip._onchange_salary_fields()
                new_payslip._onchange_bonus_vnd()
                _logger.info(
                    f"New payslip created successfully for Employee: {employee.name}"
                )
            except Exception as e:
                _logger.error(
                    f"Error creating new payslip for Employee ID {employee.id}: {str(e)}"
                )

        return record
