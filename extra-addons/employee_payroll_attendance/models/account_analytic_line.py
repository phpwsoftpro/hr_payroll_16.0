from odoo import models, fields, api, _
from odoo.exceptions import ValidationError
from datetime import timedelta


class AccountAnalyticLine(models.Model):
    _inherit = "account.analytic.line"

    # Trường 'date' mặc định là ngày hôm nay
    date = fields.Date(
        string="Date",
        default=lambda self: fields.Date.context_today(
            self
        ),  # Luôn mặc định là ngày hôm nay
    )

    employee_id = fields.Many2one(
        "hr.employee",
        string="Employee",
        required=True,  # Đảm bảo luôn có nhân viên trong bản ghi
    )

    @api.onchange("date", "unit_amount")
    def _onchange_date_or_unit_amount(self):
        """
        Kiểm tra nếu người dùng chọn ngày không phải hôm nay hoặc hôm qua,
        hiển thị cảnh báo và buộc reset giá trị về hôm nay.
        Đồng thời kiểm tra tổng số giờ không được vượt quá 12h trong một ngày, theo từng nhân viên.
        """
        # Kiểm tra giá trị ngày
        if self.date:
            today_date = fields.Date.context_today(self)
            yesterday_date = today_date - timedelta(days=1)
            # Nếu ngày không phải hôm qua hoặc hôm nay
            if self.date not in [today_date, yesterday_date]:
                # Kiểm tra nếu người dùng không phải Admin
                if not self._is_timesheet_admin():
                    # Đặt lại ngày về hôm nay
                    self.update({"date": today_date})  # Reset giá trị
                    return {
                        "warning": {
                            "title": _("Invalid Date"),
                            "message": _(
                                "You can only select today's date or yesterday's date. The date has been reset to today."
                            ),
                        }
                    }

        # Kiểm tra tổng số giờ trong ngày (theo từng nhân viên)
        if self.date and self.unit_amount > 0 and self.employee_id:
            # Lọc các bản ghi cùng ngày và cùng nhân viên
            domain = [
                ("date", "=", self.date),
                ("employee_id", "=", self.employee_id.id),
            ]
            if self.id:  # Tránh tính trùng chính bản ghi hiện tại
                domain.append(("id", "!=", self.id))

            # Tính tổng số giờ đã nhập
            total_hours = (
                sum(self.search(domain).mapped("unit_amount")) + self.unit_amount
            )

            if total_hours > 12:
                self.update({"unit_amount": 0})  # Reset lại giờ của bản ghi hiện tại
                return {
                    "warning": {
                        "title": _("Exceeding Daily Hours"),
                        "message": _(
                            f"The total hours for {self.date} exceed 12 hours. The value has been reset."
                        ),
                    }
                }

    def _is_timesheet_admin(self):
        """
        Kiểm tra nếu người dùng thuộc nhóm Admin của Timesheets hoặc Quản trị viên.
        """
        return self.env.user.has_group(
            "hr_timesheet.group_timesheet_manager"
        ) or self.env.user.has_group("base.group_system")
