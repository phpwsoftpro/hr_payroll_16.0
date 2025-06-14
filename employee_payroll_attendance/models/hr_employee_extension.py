from odoo import models, fields, api
from datetime import date, timedelta
import logging
from dateutil.relativedelta import relativedelta

_logger = logging.getLogger(__name__)


class HrEmployee(models.Model):
    _inherit = "hr.employee"

    # --- Các trường ngày xét duyệt ---
    last_review_date = fields.Date(
        string="Last Review Date",
        help="Ngày xét duyệt gần nhất của nhân viên",
        store=True,
        readonly=False,
    )
    _next_review_date_manual = fields.Boolean(
        string="Next Review Edited Manually", default=False, store=True
    )

    next_review_date = fields.Date(
        string="Next Review Date",
        compute="_compute_next_review_date",
        inverse="_inverse_next_review_date",
        store=True,
        readonly=False,
    )

    review_date_delayed = fields.Date(
        string="Delayed Review Date",
        compute="_compute_delayed_review_date",
        store=True,
        help="Ngày xét duyệt thực tế sau khi tính trì hoãn do nghỉ phép vượt quá",
    )

    kpi_review_date = fields.Date(
        string="KPI Review Date",
        compute="_compute_kpi_review_date",
        store=True,
        readonly=True,
        help="Ngày đánh giá KPI = Delayed Review Date (ngày xét duyệt thực tế)",
    )

    review_date = fields.Date(string="Ngày xét duyệt lương")

    # --- Các trường KPI & Attendance ---
    kpi_score = fields.Float(string="KPI Score (%)")
    kpi_note = fields.Text(string="KPI Notes")

    total_unpaid_leave_days = fields.Float(
        string="Số ngày nghỉ không lương", store=True
    )

    attendance_rate = fields.Float(
        string="Tỷ lệ chuyên cần (%)", compute="_compute_attendance_rate", store=True
    )

    attendance_rate_review_cycle = fields.Float(
        string="Attendance Rate Review Cycle (%)",
        compute="_compute_attendance_rate_review_cycle",
        store=True,
    )

    kpi_review_date_invalid = fields.Boolean(
        string="Invalid KPI Review Date",
        compute="_compute_kpi_review_date_invalid",
        store=True,
    )

    payslip_ids = fields.One2many("hr.payslip", "employee_id", string="Payslips")
    delay_review = fields.Integer(
        string="Số tháng bị trì hoãn",
        compute="_compute_delayed_review_date",
        store=True,
    )
    total_unpaid_leave_days_review_cycle = fields.Integer(
        string="Unpaid Leave Days (Illegal)",
        compute="_compute_delayed_review_date",
        store=True,
    )
    kpi_score_snapshot = fields.Float(string="KPI Score Snapshot", store=True)

    review_date_invalid = fields.Boolean(
        string="Invalid Review Date",
        compute="_compute_review_date_invalid",
        store=True,
    )

    @api.depends("review_date_delayed")
    def _compute_review_date_invalid(self):
        today = fields.Date.today()
        for rec in self:
            rec.review_date_invalid = (
                rec.review_date_delayed and rec.review_date_delayed < today
            )

    @api.depends("last_review_date")
    def _compute_next_review_date(self):
        """Tính Next Review Date = Last Review Date + 1 năm"""
        for rec in self:
            if rec.last_review_date:
                rec.next_review_date = rec.last_review_date + relativedelta(years=1)
            else:
                rec.next_review_date = False

    @api.depends("last_review_date", "next_review_date")
    def _compute_delayed_review_date(self):
        """
        Tính Delayed Review Date = Next Review Date + số ngày nghỉ phép vượt quá 12 ngày
        Logic:
        1. Tính số ngày nghỉ không hợp pháp trong chu kỳ review
        2. Nếu > 12 ngày thì trì hoãn = (unpaid_days - 12) ngày
        3. Delayed Review Date = Next Review Date + số ngày trì hoãn
        """
        for emp in self:
            if not emp.last_review_date or not emp.next_review_date:
                emp.review_date_delayed = emp.next_review_date
                emp.total_unpaid_leave_days_review_cycle = 0
                emp.delay_review = 0
                continue

            # Tính số ngày nghỉ không hợp pháp trong chu kỳ review
            unpaid_days = emp._get_unpaid_leave_days(
                emp.last_review_date, emp.next_review_date
            )
            emp.total_unpaid_leave_days_review_cycle = unpaid_days

            # Tính số ngày trì hoãn (chỉ khi vượt quá 12 ngày)
            MAX_ALLOWED_LEAVE = 12
            excess_days = unpaid_days - MAX_ALLOWED_LEAVE
            emp.delay_review = int(excess_days / 30) if excess_days > 0 else 0

            # Tính Delayed Review Date
            if excess_days > 0:
                emp.review_date_delayed = emp.next_review_date + timedelta(
                    days=excess_days
                )
            else:
                emp.review_date_delayed = emp.next_review_date

            _logger.info(
                f"[👤] {emp.name} | Next: {emp.next_review_date} | Unpaid: {unpaid_days} | Delayed: {emp.review_date_delayed} | Delay months: {emp.delay_review}"
            )

    @api.depends("review_date_delayed")
    def _compute_kpi_review_date(self):
        """
        KPI Review Date = Delayed Review Date
        Đây là ngày thực tế để đánh giá KPI (đã tính trì hoãn)
        """
        for emp in self:
            emp.kpi_review_date = emp.review_date_delayed
            _logger.info(
                f"[KPI] {emp.name} | KPI Review Date: {emp.kpi_review_date} (from delayed: {emp.review_date_delayed})"
            )

    @api.depends("kpi_review_date")
    def _compute_kpi_review_date_invalid(self):
        """Kiểm tra KPI Review Date có quá hạn không"""
        today = fields.Date.today()
        for rec in self:
            rec.kpi_review_date_invalid = (
                rec.kpi_review_date and rec.kpi_review_date < today
            )

    def _inverse_next_review_date(self):
        for rec in self:
            rec._next_review_date_manual = bool(rec.next_review_date)

    def _get_unpaid_leave_days(self, start_date, end_date):
        """
        Tính số ngày nghỉ không hợp pháp trong khoảng thời gian
        """
        # Các loại nghỉ hợp pháp (code chuẩn hóa từ leave type)
        legal_codes = [
            "annual_leave",
            "sick_leave",
            "maternity",
            "marriage",
            "funeral",
            "military",
            "legal_obligation",
            "force_majeure",
        ]

        leaves = self.env["hr.leave"].search(
            [
                ("employee_id", "=", self.id),
                ("state", "=", "validate"),
                ("request_date_from", ">=", start_date),
                ("request_date_to", "<=", end_date),
            ]
        )

        unpaid = 0
        for leave in leaves:
            if leave.holiday_status_id.code not in legal_codes:
                days = (leave.request_date_to - leave.request_date_from).days + 1
                unpaid += days

        _logger.info(
            f"[📅] {self.name} | Period: {start_date} -> {end_date} | Unpaid leave days: {unpaid}"
        )
        return unpaid

    # --- Các compute method khác ---

    @api.depends("payslip_ids.attendance_line_ids.approved")
    def _compute_attendance_rate(self):
        for emp in self:
            approved_days = 0
            total_days = 0
            for payslip in emp.payslip_ids:
                approved_days += payslip.approved_working_days
                total_days += payslip.total_working_days
            emp.attendance_rate = (
                (approved_days / total_days * 100.0) if total_days else 0.0
            )

    @api.depends("last_review_date", "next_review_date")
    def _compute_attendance_rate_review_cycle(self):
        for emp in self:
            start_date = emp.last_review_date
            end_date = emp.next_review_date
            if not start_date or not end_date:
                emp.attendance_rate_review_cycle = 100.0
                continue

            total_working_days = 0
            current_date = start_date

            months_in_period = self._get_months_in_period(start_date, end_date)
            allowed_saturday_offs = len(months_in_period) * 2
            saturday_count = 0

            while current_date <= end_date:
                weekday = current_date.weekday()
                if weekday < 5:
                    total_working_days += 1
                elif weekday == 5:
                    saturday_count += 1
                    if saturday_count > allowed_saturday_offs:
                        total_working_days += 1
                current_date += timedelta(days=1)

            leaves = self.env["hr.leave"].search(
                [
                    ("employee_id", "=", emp.id),
                    ("request_date_from", "<=", end_date),
                    ("request_date_to", ">=", start_date),
                    ("state", "=", "validate"),
                ]
            )

            total_leave_days = 0
            for leave in leaves:
                leave_start = max(leave.request_date_from, start_date)
                leave_end = min(leave.request_date_to, end_date)
                if leave_start <= leave_end:
                    current = leave_start
                    while current <= leave_end:
                        weekday = current.weekday()
                        if weekday < 5:
                            total_leave_days += 1
                        elif weekday == 5:
                            saturday_in_leave = self._count_saturdays_before_date(
                                start_date, current
                            )
                            if saturday_in_leave > allowed_saturday_offs:
                                total_leave_days += 1
                        current += timedelta(days=1)

            actual_working_days = total_working_days - total_leave_days
            if total_working_days > 0:
                emp.attendance_rate_review_cycle = (
                    actual_working_days / total_working_days
                ) * 100
            else:
                emp.attendance_rate_review_cycle = 100.0

    def _get_months_in_period(self, date_from, date_to):
        months = []
        current = date_from.replace(day=1)
        while current <= date_to:
            months.append((current.year, current.month))
            if current.month == 12:
                current = current.replace(year=current.year + 1, month=1)
            else:
                current = current.replace(month=current.month + 1)
        return months

    def _count_saturdays_before_date(self, period_start, target_date):
        saturday_count = 0
        current = period_start
        while current <= target_date:
            if current.weekday() == 5:
                saturday_count += 1
            current += timedelta(days=1)
        return saturday_count

    # --- CRON tự động cập nhật (đã tối ưu) ---

    @api.model
    def cron_update_review_date_all_employees(self):
        """
        CRON job để cập nhật tự động - chỉ cần trigger recompute
        Không cần logic phức tạp vì đã có computed fields
        """
        employees = self.search([])
        _logger.info(
            f"[CRON] 🔄 Bắt đầu cập nhật review dates cho {len(employees)} nhân viên"
        )

        # Trigger recompute các trường computed
        employees._compute_delayed_review_date()
        employees._compute_kpi_review_date()

        _logger.info(f"[CRON ✅] Đã hoàn thành cập nhật review dates")

    # --- Legacy method (có thể xóa nếu không dùng) ---

    def update_review_date_for_excess_leaves(self):
        """
        Legacy method - không còn cần thiết vì logic đã được tích hợp vào computed fields
        Giữ lại để tương thích ngược
        """
        _logger.warning(
            f"[DEPRECATED] update_review_date_for_excess_leaves() không còn cần thiết. Sử dụng computed fields thay thế."
        )
        # Trigger recompute thay vì logic riêng
        self._compute_delayed_review_date()
        self._compute_kpi_review_date()
