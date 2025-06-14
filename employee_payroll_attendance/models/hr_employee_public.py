from odoo import models, fields

class HrEmployeePublic(models.Model):
    _inherit = 'hr.employee.public'

    last_review_date = fields.Date(
        related='employee_id.last_review_date',
        readonly=False,
        store=True,
        string="Ngày xét duyệt gần nhất"
    )

    next_review_date = fields.Date(
        related='employee_id.next_review_date',
        readonly=False,
        store=True,
        string="Ngày xét duyệt sau"
    )

    kpi_review_date = fields.Date(
        related='employee_id.kpi_review_date',
        readonly=False,
        store=True,
        string="Ngày xét duyệt KPI"
    )

    _next_review_date_manual = fields.Boolean(
        related='employee_id._next_review_date_manual',
        readonly=False,
        store=True
    )

    review_date_delayed = fields.Date(
        related='employee_id.review_date_delayed',
        readonly=False,
        store=True,
        string="Ngày xét duyệt sau khi bị trì hoãn"
    )

    delay_review = fields.Integer(
        related='employee_id.delay_review',
        readonly=False,
        store=True,
        string="Số tháng bị trì hoãn"
    )
    review_date_delayed = fields.Date(
        related='employee_id.review_date_delayed',
        readonly=False,
        store=True,
        string="Ngày xét duyệt sau khi bị trì hoãn"
    )

    delay_review = fields.Integer(
        related='employee_id.delay_review',
        readonly=False,
        store=True,
        string="Số tháng bị trì hoãn"
    )

    total_unpaid_leave_days_review_cycle = fields.Integer(
        related='employee_id.total_unpaid_leave_days_review_cycle',
        readonly=False,
        store=True,
        string="Số ngày nghỉ không hợp lệ"
    )
