# from odoo import models, fields, api
# from datetime import timedelta, datetime


# class HrLeave(models.Model):
#     _inherit = "hr.leave"

#     # Trường số giờ làm việc
#     number_of_hours = fields.Float(
#         string="Number of Hours",
#         compute="_compute_number_of_hours",
#         store=True,
#         readonly=False,
#         help="Total working hours for the time off request.",
#     )

#     # Trường số ngày nghỉ
#     number_of_days = fields.Float(
#         string="Number of Days",
#         compute="_compute_number_of_days",
#         store=True,
#         readonly=False,
#         help="Total number of days for the time off request.",
#     )

#     @api.depends(
#         "request_date_from",
#         "request_date_to",
#         "holiday_status_id",
#         "employee_id",
#         "request_unit_half",
#     )
#     def _compute_number_of_hours(self):
#         """Tính toán số giờ làm việc cho yêu cầu nghỉ"""
#         for leave in self:
#             if leave.request_date_from and leave.request_date_to:
#                 work_schedule = leave.employee_id.resource_calendar_id
#                 date_from = fields.Datetime.to_datetime(leave.request_date_from)
#                 date_to = fields.Datetime.to_datetime(leave.request_date_to)

#                 work_hours = 0
#                 current_date = date_from
#                 while current_date <= date_to:
#                     # Kiểm tra nếu là ngày làm việc hoặc thứ 7
#                     if (
#                         self._is_working_day(work_schedule, current_date)
#                         or current_date.weekday() == 5
#                     ):  # Thứ 7
#                         if leave.request_unit_half:  # Nếu là Half Day
#                             work_hours += work_schedule.hours_per_day / 2
#                         else:
#                             work_hours += work_schedule.hours_per_day
#                     current_date += timedelta(days=1)

#                 leave.number_of_hours = work_hours
#             else:
#                 leave.number_of_hours = 0.0

#     @api.depends("number_of_hours", "holiday_status_id")
#     def _compute_number_of_days(self):
#         """Tính toán số ngày làm việc dựa trên số giờ"""
#         for leave in self:
#             if leave.number_of_hours:
#                 work_schedule = leave.employee_id.resource_calendar_id
#                 leave.number_of_days = leave.number_of_hours / (
#                     work_schedule.hours_per_day if work_schedule else 8
#                 )
#             else:
#                 leave.number_of_days = 0.0

#     @api.onchange(
#         "holiday_status_id", "request_date_from", "request_date_to", "request_unit_half"
#     )
#     def _onchange_request_dates(self):
#         """Cập nhật số ngày và số giờ khi thay đổi ngày hoặc loại nghỉ phép"""
#         self._compute_number_of_hours()
#         self._compute_number_of_days()

#     def _is_working_day(self, work_schedule, date):
#         """Kiểm tra xem ngày có phải ngày làm việc hay không"""
#         if not work_schedule or not work_schedule.attendance_ids:
#             return False

#         weekday = date.weekday()

#         # Kiểm tra xem ngày hiện tại có trong attendance_ids không
#         return any(
#             attendance.dayofweek == str(weekday)
#             for attendance in work_schedule.attendance_ids
#         )

#     def create(self, vals):
#         """Ghi đè hàm create để đảm bảo số ngày và giờ được tính toán chính xác"""
#         records = super(HrLeave, self).create(vals)
#         records._compute_number_of_hours()
#         records._compute_number_of_days()
#         return records

#     def write(self, vals):
#         """Ghi đè hàm write để đảm bảo số ngày và giờ được tính toán chính xác"""
#         result = super(HrLeave, self).write(vals)
#         self._compute_number_of_hours()
#         self._compute_number_of_days()
#         return result
