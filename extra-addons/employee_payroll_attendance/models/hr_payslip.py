from odoo import models, fields, api, SUPERUSER_ID
import logging
from dateutil.relativedelta import relativedelta
from odoo.exceptions import UserError
from datetime import date, timedelta , datetime
import requests
import warnings
import pandas as pd
import io
import base64

_logger = logging.getLogger(__name__)


class HrPayslip(models.Model):
    _inherit = "hr.payslip"

    worked_hours = fields.Float(string="Total Worked Hours", readonly=True)
    attendance_line_ids = fields.One2many(
        "hr.payslip.attendance", "payslip_id", string="Attendance Records", copy=False
    )
    approved_by = fields.Many2one("res.users", string="Approved By", readonly=True)
    kpi_bonus = fields.Float(string="KPI Bonus", store=True)
    attendance_bonus = fields.Float(string="Attendance Bonus", compute="_compute_bonus_salary", store=True)
    base_salary_with_bonus = fields.Float(string="Base Salary + Bonus", compute="_compute_bonus_salary", store=True)
    kpi_score_snapshot = fields.Float(string="KPI Score (Snapshot)", store=True)
    last_review_date = fields.Date(related="employee_id.last_review_date", store=True)
    next_review_date = fields.Date(related="employee_id.next_review_date", store=True)
    kpi_score = fields.Float(related='employee_id.kpi_score', string='KPI Score', store=True, readonly=False)
    attendance_rate = fields.Float(string="Attendance Rate (%)", compute="_compute_attendance_rate", store=True)
    salary_raise_factor = fields.Float(string="Salary Raise Factor",store=True)
    review_date = fields.Date(string="Review Date", compute="_compute_review_date", store=True)
    excess_leave_days = fields.Float(string="Excess Leave Days", readonly=True)
    review_date_delayed = fields.Date(string="Delayed Review Date",compute="_compute_delayed_review_date",store=True)
    delay_review = fields.Integer(string="Số tháng bị trì hoãn",compute="_compute_delay_review",store=True)
    total_unpaid_leave_days_review_cycle = fields.Integer(string="Unpaid Leave Days (Illegal)",compute="_compute_total_unpaid_leave_days_review_cycle",store=True)
    attendance_rate_snapshot = fields.Float(string="Attendance Rate Snapshot (%)", store=True)
    @api.depends("date_from")
    def _compute_review_date(self):
        for payslip in self:
            if payslip.date_from:
                payslip.review_date = payslip.date_from.replace(day=1)
    @api.model
    def create(self, vals):
        # Gán snapshot nếu chưa có
        if vals.get('employee_id') and not vals.get('kpi_score_snapshot'):
            employee = self.env['hr.employee'].browse(vals['employee_id'])
            vals['kpi_score_snapshot'] = employee.kpi_score or 0.0

        record = super(HrPayslip, self).create(vals)

        # Đồng bộ attendance
        if not self.env.context.get("skip_attendance_sync"):
            record._sync_attendance_records()

        # Reset approval
        for line in record.attendance_line_ids:
            line.approved = False
            line.last_approver_payslip_id = False
            line.approved_by = False

        # Tính attendance_rate_snapshot sau khi tạo record
        record._compute_attendance_rate()  # Tính attendance rate trước
        record.attendance_rate_snapshot = record.attendance_rate  # Lưu snapshot

        # Trigger tính toán KPI bonus cho record mới
     
        record._compute_bonus_salary()

        return record
    @api.depends('employee_id.next_review_date', 'delay_review')
    def _compute_delayed_review_date(self):
        for rec in self:
            if rec.employee_id.next_review_date and rec.delay_review:
                rec.review_date_delayed = rec.employee_id.next_review_date + relativedelta(months=rec.delay_review)
            else:
                rec.review_date_delayed = rec.employee_id.next_review_date

    @api.depends('total_unpaid_leave_days_review_cycle')
    def _compute_delay_review(self):
        for rec in self:
            rec.delay_review = 0
            if rec.total_unpaid_leave_days_review_cycle:
                # Ví dụ: 3 ngày nghỉ phép vượt = +1 tháng, 6 = +2 tháng, ...
                rec.delay_review = rec.total_unpaid_leave_days_review_cycle // 3

    @api.depends('employee_id')
    def _compute_total_unpaid_leave_days_review_cycle(self):
        for rec in self:
            rec.total_unpaid_leave_days_review_cycle = 0
            if rec.employee_id.last_review_date and rec.employee_id.next_review_date:
                leaves = self.env['hr.leave'].search([
                    ('employee_id', '=', rec.employee_id.id),
                    ('request_date_from', '>=', rec.employee_id.last_review_date),
                    ('request_date_to', '<=', rec.employee_id.next_review_date),
                    ('holiday_status_id.unpaid', '=', True),
                    ('is_legal_leave', '=', False),  # custom field if needed
                    ('state', '=', 'validate'),
                ])
                total = sum(l.number_of_days for l in leaves)
                rec.total_unpaid_leave_days_review_cycle = int(total)
    @api.depends('employee_id', 'date_from', 'date_to')
    def _compute_attendance_rate(self):

        for rec in self:
            if not rec.employee_id or not rec.date_from or not rec.date_to:
                rec.attendance_rate = 100.0
                continue

            # Tính số ngày làm việc chuẩn theo chính sách công ty
            total_working_days = 0
            current_date = rec.date_from
            
            # Đếm các tháng trong kỳ để tính số thứ 7 được nghỉ
            months_in_period = self._get_months_in_period(rec.date_from, rec.date_to)
            allowed_saturday_offs = len(months_in_period) * 2  # 2 thứ 7/tháng
            
            saturday_count = 0
            
            while current_date <= rec.date_to:
                weekday = current_date.weekday()
                
                if weekday < 5:  # Thứ 2-6: ngày làm việc bình thường
                    total_working_days += 1
                elif weekday == 5:  # Thứ 7
                    saturday_count += 1
                    # Chỉ tính thứ 7 vượt quá hạn mức là ngày làm việc
                    if saturday_count > allowed_saturday_offs:
                        total_working_days += 1
                # Chủ nhật (weekday == 6): luôn được nghỉ, không tính vào ngày làm việc
                
                current_date += timedelta(days=1)

            # Lấy tổng số ngày nghỉ phép đã được duyệt trong kỳ
            leave_model = self.env['hr.leave']
            leaves = leave_model.search([
                ('employee_id', '=', rec.employee_id.id),
                ('request_date_from', '<=', rec.date_to),
                ('request_date_to', '>=', rec.date_from),
                ('state', '=', 'validate'),
            ])

            # Tính số ngày nghỉ thực tế trong khoảng thời gian payslip
            total_leave_days = 0
            for leave in leaves:
                # Tính overlap giữa leave và payslip period
                leave_start = max(leave.request_date_from, rec.date_from)
                leave_end = min(leave.request_date_to, rec.date_to)
                
                if leave_start <= leave_end:
                    current = leave_start
                    while current <= leave_end:
                        weekday = current.weekday()
                        
                        # Chỉ tính ngày nghỉ nếu rơi vào ngày làm việc theo chính sách
                        if weekday < 5:  # Thứ 2-6
                            total_leave_days += 1
                        elif weekday == 5:  # Thứ 7
                            # Tính thứ 7 nghỉ nếu vượt quá hạn mức
                            saturday_in_leave = self._count_saturdays_before_date(
                                rec.date_from, current, allowed_saturday_offs
                            )
                            if saturday_in_leave > allowed_saturday_offs:
                                total_leave_days += 1
                        
                        current += timedelta(days=1)

            # Tính số ngày làm việc thực tế
            actual_working_days = total_working_days - total_leave_days

            # Tính tỷ lệ chuyên cần
            if total_working_days > 0:
                rec.attendance_rate = (actual_working_days / total_working_days) * 100
            else:
                rec.attendance_rate = 100.0

            _logger.info(f"[ATTENDANCE RATE] {rec.employee_id.name}: "
                    f"{total_working_days} ngày chuẩn (bao gồm {saturday_count - allowed_saturday_offs} thứ 7 vượt hạn mức), "
                    f"{total_leave_days} ngày nghỉ, tỷ lệ = {rec.attendance_rate:.2f}%")

    def _get_months_in_period(self, date_from, date_to):
        """Lấy danh sách các tháng trong kỳ đánh giá"""
        months = []
        current = date_from.replace(day=1)
        
        while current <= date_to:
            months.append((current.year, current.month))
            # Chuyển sang tháng tiếp theo
            if current.month == 12:
                current = current.replace(year=current.year + 1, month=1)
            else:
                current = current.replace(month=current.month + 1)
        
        return months

    def _count_saturdays_before_date(self, period_start, target_date, allowed_saturdays):
        """Đếm số thứ 7 từ đầu kỳ đến ngày chỉ định để xác định thứ 7 có được nghỉ không"""
        saturday_count = 0
        current = period_start
        
        while current <= target_date:
            if current.weekday() == 5:  # Thứ 7
                saturday_count += 1
            current += timedelta(days=1)
        
        return saturday_count


    @api.depends('employee_id', 'employee_id.last_review_date', 'employee_id.next_review_date',
             'kpi_score', 'employee_id.attendance_rate_review_cycle', 'date_from')
    def _compute_bonus_salary(self):
        for payslip in self:
            employee = payslip.employee_id
            payslip.salary_raise_factor = 0.0
            payslip.attendance_bonus = 0.0

            if not employee or not employee.last_review_date or not employee.next_review_date or not payslip.date_from:
                continue

            # Chỉ tính thưởng sau khi kết thúc next_review_date
            if payslip.date_from <= employee.next_review_date:
                _logger.info(f"[BONUS SKIP] {employee.name}: Chưa đến kỳ tính thưởng. Current: {payslip.date_from}, Next review: {employee.next_review_date}")
                continue


            # Sử dụng kpi_score thay vì kpi_score_snapshot
            attendance_rate = employee.attendance_rate_review_cycle or 0.0
            kpi_score = payslip.kpi_score or 0.0

            # Xác định mức thưởng tối đa
            max_bonus = 1_000_000  # 1 triệu VND
            factor = 0.0

            # Áp dụng công thức theo bảng
            if 90 <= attendance_rate <= 93.33 and kpi_score >= 85:
                factor = 0.6
            elif 93.34 <= attendance_rate <= 95.22 and kpi_score > 85:
                factor = 0.8
            elif 95.23 <= attendance_rate <= 100.0 and kpi_score >= 90:
                factor = 1.0

            payslip.salary_raise_factor = factor
            payslip.attendance_bonus = max_bonus * factor

        
            _logger.info(f"[BONUS CALCULATION] {employee.name}: Chuyên cần {attendance_rate}%, KPI {kpi_score}%, Factor {factor}, Bonus {payslip.attendance_bonus}")
            
            try:    
                # Initialize hourly_rate variable properly
                hourly_rate = 0.0
                
                # Determine the hourly rate based on payslip type
                if payslip.is_hourly_usd:
                    hourly_rate = payslip.hourly_rate or 0.0
                elif payslip.is_hourly_vnd:
                    hourly_rate = payslip.hourly_rate_vnd or 0.0
                elif payslip.wage:
                    # Calculate hourly rate from monthly wage (assuming standard working hours)
                    # Standard: 8 hours/day * 22 working days/month = 176 hours/month
                    standard_monthly_hours = 176
                    hourly_rate = payslip.wage / standard_monthly_hours if standard_monthly_hours > 0 else 0.0
                
                # Log thông tin (an toàn vì hourly_rate đã được định nghĩa)
                _logger.info(
                    f"Payslip ID: {payslip.id}, "
                    f"Hourly rate: {hourly_rate}, "
                    f"Probation percentage: {getattr(payslip, 'probation_percentage', 0)}%"
                )
                
                # Tính total salary
                if hasattr(payslip, 'is_hourly_usd') and payslip.is_hourly_usd:
                    # Hourly USD employee
                    worked_hours = payslip.worked_hours or 0.0
                    base_salary = hourly_rate * worked_hours
                    
                    # Apply probation percentage if applicable
                    if hasattr(payslip, 'probation_percentage') and payslip.probation_percentage:
                        base_salary = base_salary * (payslip.probation_percentage / 100.0)
                    
                    # Apply currency conversion if needed
                    if hasattr(payslip, 'currency_rate_fallback') and payslip.currency_rate_fallback:
                        payslip.total_salary = base_salary * payslip.currency_rate_fallback
                    else:
                        payslip.total_salary = base_salary
                        
                elif hasattr(payslip, 'is_hourly_vnd') and payslip.is_hourly_vnd:
                    # Hourly VND employee
                    worked_hours = payslip.worked_hours or 0.0
                    base_salary = hourly_rate * worked_hours
                    
                    # Apply probation percentage if applicable
                    if hasattr(payslip, 'probation_percentage') and payslip.probation_percentage:
                        base_salary = base_salary * (payslip.probation_percentage / 100.0)
                    
                    payslip.total_salary = base_salary
                    
                else:
                    # Monthly salary employees
                    base_salary = payslip.monthly_wage_vnd or payslip.wage or 0.0
                    
                    # Apply probation percentage if applicable
                    if hasattr(payslip, 'probation_percentage') and payslip.probation_percentage:
                        base_salary = base_salary * (payslip.probation_percentage / 100.0)
                    
                    payslip.total_salary = base_salary
                    
                # Thêm bonuses vào total salary
                payslip.total_salary += payslip.attendance_bonus
                payslip.base_salary_with_bonus = payslip.total_salary
                    
            except Exception as e:
                _logger.error(f"Error computing total salary for payslip {payslip.id}: {str(e)}")
                if hasattr(payslip, 'total_salary'):
                    payslip.total_salary = 0.0


    def action_payslip_done(self):
        res = super().action_payslip_done()
        for payslip in self:
            if payslip.employee_id and payslip.next_review_date:
                payslip.employee_id.next_review_date = payslip.next_review_date
        return res

    def _compute_total_worked_hours(self):
        """
        Calculate total worked hours from approved attendance records.
        """
        for payslip in self:
            total_hours = sum(
                line.worked_hours
                for line in payslip.attendance_line_ids
                if line.approved
            )
            payslip.worked_hours = total_hours

    @api.onchange("employee_id", "date_from", "date_to")
    def _onchange_attendance_records(self):
        if not self.employee_id or not self.date_from or not self.date_to:
            return  # Do nothing if any of the fields are missing

        # Get attendance records that match the employee and date range
        attendances = self.env["hr.attendance"].search(
            [
                ("employee_id", "=", self.employee_id.id),
                ("check_in", ">=", self.date_from),
                ("check_out", "<=", self.date_to),
            ]
        )

        # Find the IDs of attendance records that already exist
        existing_attendance_ids = set(
            self.attendance_line_ids.mapped("attendance_id.id")
        )

        # Remove any records that are no longer in the date range
        self.attendance_line_ids = self.attendance_line_ids.filtered(
            lambda line: line.attendance_id.id in attendances.mapped("id")
        )

        # Add new records
        for attendance in attendances:
            if attendance.id not in existing_attendance_ids:
                self.attendance_line_ids = [
                    (
                        0,
                        0,
                        {
                            "attendance_id": attendance.id,
                            "check_in": attendance.check_in,
                            "check_out": attendance.check_out,
                            "worked_hours": attendance.worked_hours,
                            "approved": False,
                        },
                    )
                ]

    def _auto_update_attendance_records(self):
        for payslip in self:
            _logger.info(
                f"Starting _auto_update_attendance_records for Payslip ID {payslip.id}"
            )

            existing_attendance_ids = payslip.attendance_line_ids.mapped(
                "attendance_id.id"
            )

            attendances = (
                self.env["hr.attendance"]
                .with_user(SUPERUSER_ID)
                .search(
                    [
                        ("employee_id", "=", payslip.employee_id.id),
                        ("check_in", ">=", payslip.date_from),
                        ("check_out", "<=", payslip.date_to),
                    ]
                )
            )

            if attendances:
                _logger.info(
                    f"Attendances found for Payslip ID {payslip.id}: {attendances.ids}"
                )
            else:
                _logger.info(f"No attendances found for Payslip ID {payslip.id}")

            new_attendance_lines = [
                (
                    0,
                    0,
                    {
                        "attendance_id": attendance.id,
                        "check_in": attendance.check_in,
                        "check_out": attendance.check_out,
                        "worked_hours": attendance.worked_hours,
                        "approved": False,
                    },
                )
                for attendance in attendances
                if attendance.id not in existing_attendance_ids
            ]

            if new_attendance_lines:
                payslip.write({"attendance_line_ids": new_attendance_lines})

    def _sync_attendance_records(self):
        """
        Sync attendance records with payslip without creating duplicates.
        Avoid syncing 'approved' status from other payslips.
        """
        for payslip in self:
            if not payslip.employee_id or not payslip.date_from or not payslip.date_to:
                continue  # Skip if any required fields are missing

            # Get attendance records that match the employee and date range
            attendances = (
                self.env["hr.attendance"]
                .with_user(SUPERUSER_ID)
                .search(
                    [
                        ("employee_id", "=", payslip.employee_id.id),
                        ("check_in", ">=", payslip.date_from),
                        ("check_out", "<=", payslip.date_to),
                    ]
                )
            )

            # Remove any records that are no longer in the date range
            payslip.attendance_line_ids.filtered(
                lambda line: line.attendance_id.id not in attendances.mapped("id")
            ).unlink()

            # Add new attendance records without syncing 'approved' status
            existing_attendance_ids = set(
                payslip.attendance_line_ids.mapped("attendance_id.id")
            )
            for attendance in attendances:
                if attendance.id not in existing_attendance_ids:
                    payslip.attendance_line_ids = [
                        (
                            0,
                            0,
                            {
                                "attendance_id": attendance.id,
                                "check_in": attendance.check_in,
                                "check_out": attendance.check_out,
                                "worked_hours": attendance.worked_hours,
                                "approved": False,  # Do not sync approved status
                                "last_approver_payslip_id": False,  # Reset last approver
                            },
                        )
                    ]

    @api.model
    def create(self, vals):
        # Gán snapshot nếu chưa có
        if vals.get('employee_id') and not vals.get('kpi_score_snapshot'):
            employee = self.env['hr.employee'].browse(vals['employee_id'])
            vals['kpi_score_snapshot'] = employee.kpi_score or 0.0

        record = super(HrPayslip, self).create(vals)

        # Đồng bộ attendance
        if not self.env.context.get("skip_attendance_sync"):
            record._sync_attendance_records()

        # Reset approval
        for line in record.attendance_line_ids:
            line.approved = False
            line.last_approver_payslip_id = False
            line.approved_by = False

        # Trigger tính toán KPI bonus cho record mới
  
        record._compute_bonus_salary()

        return record

    def write(self, vals):
        res = super(HrPayslip, self).write(vals)
        
        # Nếu có thay đổi liên quan đến KPI hoặc wage, recompute
        kpi_related_fields = ['kpi_score_snapshot', 'wage', 'date_from', 'date_to', 
                            'approved_working_days', 'total_working_days']
        if any(field in vals for field in kpi_related_fields):
          
            self._compute_bonus_salary()
            
        if any(key in vals for key in ["employee_id", "date_from", "date_to"]):
            self._sync_attendance_records()
        return res

    # Thêm method onchange để cập nhật khi thay đổi employee
    @api.onchange('employee_id')
    def _onchange_employee_id(self):
        """Cập nhật thông tin KPI và attendance rate khi thay đổi employee"""
        if self.employee_id:
            self.kpi_score_snapshot = self.employee_id.kpi_score or 0.0
            self.last_review_date = self.employee_id.last_review_date
            self.next_review_date = self.employee_id.next_review_date
            
            # Tính và lưu attendance rate snapshot
            if hasattr(self, '_compute_attendance_rate'):
                self._compute_attendance_rate()

            self.attendance_rate_snapshot = self.attendance_rate
            
          
            self._compute_bonus_salary()


    @api.onchange('employee_id')
    def _onchange_employee_kpi_snapshot(self):
        if self.employee_id:
            self.kpi_score_snapshot = self.employee_id.kpi_score

    def action_duplicate_payslips(self):
        """
        Duplicate payslips with new start and end dates one month after the current payslip.
        """
        for payslip in self:
            # Lấy tất cả Attendance Records thuộc khoảng thời gian của Payslip
            attendances = self.env["hr.attendance"].search(
                [
                    ("employee_id", "=", payslip.employee_id.id),
                    ("check_in", ">=", payslip.date_from),
                    ("check_out", "<=", payslip.date_to),
                ]
            )

            # Tìm các Attendance mới chưa được thêm vào Payslip
            existing_attendance_ids = payslip.attendance_line_ids.mapped(
                "attendance_id.id"
            )
            new_attendances = attendances.filtered(
                lambda a: a.id not in existing_attendance_ids
            )

            # Thêm các Attendance mới vào Payslip
            payslip.attendance_line_ids = [
                (
                    0,
                    0,
                    {
                        "attendance_id": attendance.id,
                        "check_in": attendance.check_in,
                        "check_out": attendance.check_out,
                        "worked_hours": attendance.worked_hours,
                        "approved": False,
                    },
                )
                for attendance in new_attendances
            ]

    def action_approve_attendance(self):
        """
        Approve all attendance records in the selected payslip.
        """
        _logger.info("Action Approve Attendance started for Payslip IDs: %s", self.ids)
        for payslip in self:
            for line in payslip.attendance_line_ids:
                if not line.approved:
                    line.approved = True  # Update approved status
                    _logger.info(
                        "Approved Attendance ID: %s for Payslip ID: %s",
                        line.attendance_id.id,
                        payslip.id,
                    )

                    # Find other payslip lines that contain the same attendance
                    other_payslip_lines = self.env["hr.payslip.attendance"].search(
                        [
                            ("attendance_id", "=", line.attendance_id.id),
                            ("payslip_id", "!=", payslip.id),
                        ]
                    )

                    # Disable editing for this attendance record in other payslips
                    other_payslip_lines.write({"approved": True})

            # Recompute total worked hours after approval
            payslip._compute_total_worked_hours()
            payslip.compute_meal_allowance()
            _logger.info("Recomputed total worked hours for Payslip ID: %s", payslip.id)
        _logger.info(
            "Action Approve Attendance completed for Payslip IDs: %s", self.ids
        )

    @api.depends("attendance_line_ids.approved", "attendance_line_ids.worked_hours")
    def compute_meal_allowance(self):
        """
        Tính tiền ăn (meal_allowance_vnd) cho payslip dựa trên trạng thái approved của các bản ghi attendance.
        Điều kiện:
        - include_saturdays phải là True.
        - Tổng số giờ làm trong một ngày >= 8 giờ thì cộng 30,000 VND.
        """
        for payslip in self:
            # Nếu không tính thứ 7, giữ nguyên tiền ăn = 0
            if not payslip.include_saturdays:
                payslip.meal_allowance_vnd = 0
                payslip.write({"meal_allowance_vnd": 0})
                continue  # Bỏ qua các bước tiếp theo

            total_meal_allowance = 0  # Biến lưu tổng tiền ăn

            # Lọc các bản ghi attendance đã được approve
            approved_attendances = payslip.attendance_line_ids.filtered(
                lambda a: a.approved
            )

            # Nhóm theo ngày để tính tổng số giờ làm của mỗi ngày
            attendance_by_date = {}
            for record in approved_attendances:
                attendance_date = record.attendance_id.check_in.date()
                if attendance_date not in attendance_by_date:
                    attendance_by_date[attendance_date] = 0
                attendance_by_date[attendance_date] += record.worked_hours

            # Tính tiền ăn: nếu tổng giờ làm >= 8h trong ngày => +30,000 VND
            for date, total_hours in attendance_by_date.items():
                if total_hours >= 8:
                    total_meal_allowance += (
                        30000  # Cộng thêm 30,000 VND cho mỗi ngày đủ điều kiện
                    )

            # Gán lại giá trị vào payslip
            payslip.meal_allowance_vnd = total_meal_allowance
            payslip.write({"meal_allowance_vnd": total_meal_allowance})

            _logger.info(
                f"Updated meal allowance for Payslip {payslip.id}: {total_meal_allowance} VND"
            )


class HrPayslipAttendance(models.Model):
    _name = "hr.payslip.attendance"
    _description = "Payslip Attendance"

    _logger = logging.getLogger(__name__)

    payslip_id = fields.Many2one(
        "hr.payslip", string="Payslip", ondelete="cascade", required=True
    )
    attendance_id = fields.Many2one(
        "hr.attendance", string="Attendance Record", required=True
    )
    check_in = fields.Datetime(
        string="Check In", related="attendance_id.check_in", readonly=True, store=True
    )
    check_out = fields.Datetime(
        string="Check Out", related="attendance_id.check_out", readonly=True
    )
    worked_hours = fields.Float(
        string="Worked Hours", related="attendance_id.worked_hours", readonly=True
    )
    approved_by = fields.Many2one("res.users", string="Approved By", readonly=True)
    approved = fields.Boolean(string="Approved", default=False)
    employee_id = fields.Many2one(
        "hr.employee",
        string="Employee",
        related="attendance_id.employee_id",
        store=True,
    )
    last_approver_payslip_id = fields.Many2one(
        "hr.payslip",
        string="Last Approver Payslip",
        help="The last payslip that approved this attendance record.",
    )

    def toggle_approval(self):
        """
        Toggle the approval status of an attendance record in the current payslip.
        Prevent approval if already approved in another payslip.
        """
        for record in self:
            payslip = record.payslip_id

            # ❗ Chặn duyệt nếu attendance đã được approved trong payslip khác
            if not record.approved:
                other_lines = self.env["hr.payslip.attendance"].search(
                    [
                        ("attendance_id", "=", record.attendance_id.id),
                        ("payslip_id", "!=", record.payslip_id.id),
                        ("approved", "=", True),
                    ],
                    limit=1,
                )

                if other_lines:
                    raise UserError(
                        f"Attendance này đã được duyệt trong bảng lương khác (Payslip ID: {other_lines.payslip_id.id})."
                    )

            # ❄️ Logic tiếp theo giữ nguyên như bạn đang có:
            if not payslip.include_saturdays:
                record.approved = not record.approved
                record.approved_by = self.env.user.id if record.approved else False
                record.last_approver_payslip_id = payslip if record.approved else False
                return

            attendance_date = record.attendance_id.check_in.date()

            same_day_attendances = payslip.attendance_line_ids.filtered(
                lambda a: a.attendance_id.check_in.date() == attendance_date
            )

            previous_total_hours = sum(
                att.worked_hours for att in same_day_attendances if att.approved
            )

            if record.approved:
                record.approved = False
                record.approved_by = False
                record.last_approver_payslip_id = False

                new_total_hours = previous_total_hours - record.worked_hours

                if previous_total_hours >= 8 and new_total_hours < 8:
                    payslip.meal_allowance_vnd -= 30000
                    payslip.write({"meal_allowance_vnd": payslip.meal_allowance_vnd})
                    payslip._onchange_bonus_vnd()
            else:
                record.approved = True
                record.last_approver_payslip_id = payslip
                record.approved_by = self.env.user.id

                new_total_hours = previous_total_hours + record.worked_hours

                if previous_total_hours < 8 and new_total_hours >= 8:
                    payslip.meal_allowance_vnd += 30000
                    payslip.write({"meal_allowance_vnd": payslip.meal_allowance_vnd})
                    payslip._onchange_bonus_vnd()

            payslip._compute_total_worked_hours()
            self._sync_approval_status_within_payslip(record)
            self._recompute_related_payslips(record)

    def _sync_approval_status_within_payslip(self, record):
        """
        Synchronize the approval status across all related payslip lines
        for the attendance record within the same payslip.
        """
        related_lines = self.env["hr.payslip.attendance"].search(
            [
                ("attendance_id", "=", record.attendance_id.id),
                (
                    "payslip_id",
                    "=",
                    record.payslip_id.id,
                ),  # Only sync within the same payslip
            ]
        )
        for line in related_lines:
            line.approved = record.approved
            line.last_approver_payslip_id = record.last_approver_payslip_id
            line.approved_by = record.approved_by

    def _recompute_related_payslips(self, record):
        """
        Recompute the total worked hours for all payslips related to the attendance record.
        """
        related_payslips = self.env["hr.payslip"].search(
            [("attendance_line_ids.attendance_id", "=", record.attendance_id.id)]
        )
        for payslip in related_payslips:
            payslip._compute_total_worked_hours()

    def action_view_details(self):
        """
        Open a popup to show the timesheet details related to the selected attendance.
        """
        self.ensure_one()

        # Refresh the current record to ensure the latest status
        self.refresh()

        return {
            "type": "ir.actions.act_window",
            "name": "Attendance and Timesheet Details",
            "view_mode": "form",
            "res_model": "attendance.timesheet.details",
            "target": "new",
            "context": {
                "default_employee_id": self.attendance_id.employee_id.id,
                "default_date": self.attendance_id.check_in.date(),
                "default_check_in": self.attendance_id.check_in,
                "default_check_out": self.attendance_id.check_out,
                "default_worked_hours": self.attendance_id.worked_hours,
                "default_approved": self.approved,  # Ensure the approved status is updated
            },
        }

    def write(self, vals):
        """
        Khi trạng thái `approved` của một bản ghi attendance thay đổi,
        tự động cập nhật lại tiền ăn của payslip chứa nó.
        """
        res = super().write(vals)

        # Nếu có thay đổi trạng thái approved, cập nhật meal allowance
        if "approved" in vals:
            payslips = self.mapped("payslip_id")
            if payslips:
                _logger.info(
                    "Recomputing meal allowance for Payslips: %s", payslips.ids
                )
                payslips.compute_meal_allowance()

        return res


class HrAttendance(models.Model):
    _inherit = "hr.attendance"

    def toggle_approval(self):
        """Toggle approval status for attendance."""
        for record in self:
            record.approved = not record.approved

    @api.model
    def _round_time(self, time):
        """Làm tròn thời gian tới phút gần nhất"""
        return (time + timedelta(seconds=30)).replace(second=0, microsecond=0)

    @api.model_create_multi
    def create(self, vals_list):
        """Làm tròn thời gian khi tạo mới và tự động đồng bộ với Payslip"""
        # Làm tròn thời gian cho tất cả records
        for vals in vals_list:
            if "check_in" in vals and vals["check_in"]:
                vals["check_in"] = self._round_time(
                    fields.Datetime.from_string(vals["check_in"])
                )
            if "check_out" in vals and vals["check_out"]:
                vals["check_out"] = self._round_time(
                    fields.Datetime.from_string(vals["check_out"])
                )

        # Tạo attendance records
        attendances = super().create(vals_list)

        # Cập nhật payslip cho mỗi attendance
        for attendance in attendances:
            if attendance.check_out:  # Chỉ cập nhật khi đã check out
                payslips = self.env["hr.payslip"].search(
                    [
                        ("employee_id", "=", attendance.employee_id.id),
                        ("date_from", "<=", attendance.check_in),
                        ("date_to", ">=", attendance.check_out),
                    ]
                )
                if payslips:
                    payslips._auto_update_attendance_records()

        return attendances

    def write(self, vals):
        """Làm tròn thời gian khi cập nhật và đồng bộ với Payslip"""
        # Làm tròn thời gian
        if "check_in" in vals and vals["check_in"]:
            vals["check_in"] = self._round_time(
                fields.Datetime.from_string(vals["check_in"])
            )
        if "check_out" in vals and vals["check_out"]:
            vals["check_out"] = self._round_time(
                fields.Datetime.from_string(vals["check_out"])
            )

        # Thực hiện cập nhật
        result = super().write(vals)

        # Cập nhật payslip nếu có thay đổi check_in hoặc check_out
        if "check_in" in vals or "check_out" in vals:
            for attendance in self:
                if attendance.check_out:  # Chỉ cập nhật khi đã check out
                    payslips = self.env["hr.payslip"].search(
                        [
                            ("employee_id", "=", attendance.employee_id.id),
                            ("date_from", "<=", attendance.check_in),
                            ("date_to", ">=", attendance.check_out),
                        ]
                    )
                    if payslips:
                        payslips._auto_update_attendance_records()

        return result


class HrPayslipDuplicateWizard(models.TransientModel):
    _name = "hr.payslip.duplicate.wizard"
    _description = "Wizard for duplicating payslip"

    currency_rate_fallback = fields.Float(
        string="Currency Rate Fallback", required=True
    )

    def action_duplicate_payslips(self):
        active_ids = self.env.context.get("active_ids", [])
        if not active_ids:
            raise UserError("No payslips selected to duplicate.")

        for payslip in self.env["hr.payslip"].browse(active_ids):
            _logger.info(
                f"Processing Payslip ID: {payslip.id}, Employee: {payslip.employee_id.name}"
            )

            new_start_date = payslip.date_from + relativedelta(months=1)
            new_end_date = (new_start_date + relativedelta(months=1)) - timedelta(
                days=1
            )

            _logger.info(f"New Payslip Period: {new_start_date} to {new_end_date}")

            existing_payslip = self.env["hr.payslip"].search(
                [
                    ("employee_id", "=", payslip.employee_id.id),
                    ("date_from", "=", new_start_date),
                    ("date_to", "=", new_end_date),
                ],
                limit=1,
            )
            if existing_payslip:
                _logger.warning(
                    f"Payslip already exists for {payslip.employee_id.name} from {new_start_date} to {new_end_date}"
                )
                raise UserError(
                    (
                        f"Payslip already exists for employee {payslip.employee_id.name} "
                        f"from {new_start_date} to {new_end_date}. Unable to duplicate!"
                    )
                )

            _logger.info(f"include_saturdays: {payslip.include_saturdays}")
            _logger.info(f"is_hourly_vnd: {payslip.is_hourly_vnd}")
            _logger.info(f"is_hourly_usd: {payslip.is_hourly_usd}")
            _logger.info(f"Current monthly_wage_vnd: {payslip.monthly_wage_vnd}")
            _logger.info(f"Current wage (USD): {payslip.wage}")

            if payslip.include_saturdays is True or payslip.dev_inhouse is True:
                copy_values = {
                    "date_from": new_start_date,
                    "date_to": new_end_date,
                    "currency_rate_fallback": self.currency_rate_fallback,
                    "status": "draft",
                    "monthly_wage_vnd": payslip.monthly_wage_vnd,
                    "rate_lock_field": "monthly_wage_vnd",
                    "meal_allowance_vnd": 0,
                    "kpi_bonus_vnd": 0,
                    "other_bonus_vnd": 0,
                }
            elif payslip.is_hourly_vnd is True:
                copy_values = {
                    "date_from": new_start_date,
                    "date_to": new_end_date,
                    "currency_rate_fallback": self.currency_rate_fallback,
                    "status": "draft",
                    "rate_lock_field": "hourly_rate_vnd",
                    "hourly_rate_vnd": payslip.hourly_rate_vnd,
                    "meal_allowance_vnd": 0,
                    "kpi_bonus_vnd": 0,
                    "other_bonus_vnd": 0,
                }
            elif payslip.is_hourly_usd is True:
                copy_values = {
                    "date_from": new_start_date,
                    "date_to": new_end_date,
                    "currency_rate_fallback": self.currency_rate_fallback,
                    "status": "draft",
                    "rate_lock_field": "hourly_rate",
                    "hourly_rate": payslip.hourly_rate,
                    "meal_allowance_vnd": 0,
                    "kpi_bonus_vnd": 0,
                    "other_bonus_vnd": 0,
                }
            else:
                copy_values = {
                    "date_from": new_start_date,
                    "date_to": new_end_date,
                    "currency_rate_fallback": self.currency_rate_fallback,
                    "status": "draft",
                    "rate_lock_field": "wage",
                    "wage": payslip.wage,
                    "meal_allowance_vnd": 0,
                    "kpi_bonus_vnd": 0,
                    "other_bonus_vnd": 0,
                }

            _logger.info(f"Copy Values: {copy_values}")

            new_payslip = payslip.copy(copy_values)
            _logger.info(f"New Payslip Created: {new_payslip.id}")

            if new_payslip.attendance_line_ids:
                new_payslip.attendance_line_ids.unlink()

            attendances = self.env["hr.attendance"].search(
                [
                    ("employee_id", "=", payslip.employee_id.id),
                    ("check_in", ">=", new_start_date),
                    ("check_out", "<=", new_end_date),
                ]
            )

            new_payslip.attendance_line_ids = [
                (
                    0,
                    0,
                    {
                        "attendance_id": attendance.id,
                        "check_in": attendance.check_in,
                        "check_out": attendance.check_out,
                        "worked_hours": attendance.worked_hours,
                        "approved": False,
                    },
                )
                for attendance in attendances
            ]

            _logger.info(f"Updated Attendance Records for Payslip ID {new_payslip.id}")

            new_payslip._onchange_salary_fields()
            new_payslip._auto_update_attendance_records()
            new_payslip._onchange_bonus_vnd()

            _logger.info(
                f"Final monthly_wage_vnd for New Payslip ID {new_payslip.id}: {new_payslip.monthly_wage_vnd}"
            )
            if new_payslip.full_monthly_fix_price:
                new_payslip._generate_attendance_for_full_month()

        return new_payslip

   
