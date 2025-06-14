# -*- coding: utf-8 -*-
from odoo import models, fields, api
from odoo.exceptions import ValidationError
import calendar

class WorkSaturdaySchedule(models.Model):
    _name = 'work.saturday.schedule'
    _description = 'Saturday Off Schedule'

    name = fields.Char(string="Description", required=True)
    saturday_type = fields.Selection([
        ('alternate', 'Alternate Saturday'),
        ('custom',    'Custom Saturday'),
    ], string="Schedule Type", required=True, default='custom')

    month = fields.Selection(
        [(str(i), f"{i:02d}") for i in range(1, 13)],
        string="Month", required=True,
        default=lambda self: str(fields.Date.today().month),
    )
    # Mới: tính xem tháng có 5 Thứ 7 hay không
    month_has_5 = fields.Boolean(
        string="Has 5 Saturdays",
        compute='_compute_month_info',
        store=False,
    )

    # Mới: hai dropdown pattern, chỉ hiện 1 tuỳ theo month_has_5
    week_pattern_4 = fields.Selection([
        ('1_3',   'Week 1 & 3'),
        ('2_4',   'Week 2 & 4'),
    ], string="Pattern (4-week)")
    week_pattern_5 = fields.Selection([
        ('1_3_5', 'Week 1, 3 & 5'),
        ('2_4_5', 'Week 2, 4 & 5'),
        ('1_2_4', 'Week 1, 2 & 4'),
    ], string="Pattern (5-week)")

    # Giữ lại để compute, readonly
    week_pattern = fields.Selection([
        ('1_3',   'Week 1 & 3'),
        ('2_4',   'Week 2 & 4'),
        ('1_3_5', 'Week 1, 3 & 5'),
        ('2_4_5', 'Week 2, 4 & 5'),
        ('1_2_4', 'Week 1, 2 & 4'),
    ], string="Effective Pattern", readonly=True)

    computed_alternate_days = fields.Char(
        string="Computed Saturdays",
        compute="_compute_alternate_days",
        readonly=True,
    )

    day_off = fields.Date(string="Day Off")
    makeup_day = fields.Date(string="Make-up Day")               # for custom
    makeup_day_alternate = fields.Date(string="Make-up Day (Alternate)")  # for work-Saturdays

    apply_all_employees = fields.Boolean(
        string="Apply to All Employees In-house", default=True)
    employee_ids = fields.Many2many(
        'hr.employee', string="Employees", domain="[('active','=',True)]")

    # ---------------------------------------------------
    @api.depends('month')
    def _compute_month_info(self):
        for rec in self:
            year = fields.Date.today().year
            sats = [
                d for d in calendar.Calendar().itermonthdates(year, int(rec.month))
                if d.weekday() == 5 and d.month == int(rec.month)
            ]
            rec.month_has_5 = len(sats) >= 5

    @api.depends('month', 'week_pattern_4', 'week_pattern_5',
                 'month_has_5', 'saturday_type')
    def _compute_alternate_days(self):
        idx_map = {
            '1_3':   [0,2],
            '2_4':   [1,3],
            '1_3_5': [0,2,4],
            '2_4_5': [1,3,4],
            '1_2_4': [0,1,3],
        }
        for rec in self:
            rec.computed_alternate_days = ''
            if rec.saturday_type != 'alternate' or not rec.month:
                continue
            year = fields.Date.today().year
            sats = [
                d for d in calendar.Calendar().itermonthdates(year, int(rec.month))
                if d.weekday() == 5 and d.month == int(rec.month)
            ]
            # chọn pattern dựa trên số Thứ 7
            patt = rec.week_pattern_5 if rec.month_has_5 else rec.week_pattern_4
            rec.week_pattern = patt
            days = [sats[i] for i in idx_map.get(patt, []) if i < len(sats)]
            rec.computed_alternate_days = ', '.join(d.strftime("%d/%m/%Y") for d in days)

    # ---------------------------------------------------
    @api.onchange('saturday_type')
    def _onchange_type(self):
        if self.saturday_type == 'custom':
            # clear alternate fields
            self.week_pattern_4 = False
            self.week_pattern_5 = False
            self.computed_alternate_days = False
        else:
            # clear custom fields
            self.day_off = False
            self.makeup_day = False

    @api.constrains('day_off')
    def _check_day_off(self):
        for rec in self:
            if rec.day_off and rec.day_off.weekday() != 5:
                raise ValidationError("⚠️ Day Off must be a Saturday!")

    # ---------------------------------------------------
    @api.model
    def create(self, vals):
        # --- Nếu alternate: sinh off-days và work-days như cũ ---
        if vals.get('saturday_type') == 'alternate':
            year = fields.Date.today().year
            m = int(vals['month'])
            sats = [
                d for d in calendar.Calendar().itermonthdates(year, m)
                if d.weekday() == 5 and d.month == m
            ]
            # chọn pattern
            usep = vals.get('week_pattern_5') if len(sats) >= 5 else vals.get('week_pattern_4')
            vals['week_pattern'] = usep
            idx_map = {
                '1_3':   [0,2], '2_4':   [1,3],
                '1_3_5': [0,2,4], '2_4_5': [1,3,4],
                '1_2_4': [0,1,3],
            }
            offs  = [sats[i] for i in idx_map.get(usep, []) if i < len(sats)]
            works = [d for d in sats if d not in offs]
            # xoá trùng
            if offs+works:
                self.search([
                    '|', ('day_off','in',offs+works),
                         ('makeup_day_alternate','in',offs+works),
                ]).unlink()
            recs = []
            # tạo off-day
            for off in offs:
                recs.append(super().create({
                    **vals,
                    'saturday_type': 'custom',
                    'day_off': off,
                    'makeup_day': False,
                    'makeup_day_alternate': False,
                }))
            # tạo work-day
            for wk in works:
                recs.append(super().create({
                    **vals,
                    'saturday_type': 'custom',
                    'day_off': False,
                    'makeup_day': False,
                    'makeup_day_alternate': wk,
                }))
            return recs and recs[0] or super().create(vals)

        # --- Nếu custom: giữ nguyên logic cũ ---
        if vals.get('saturday_type') == 'custom':
            dates = []
            for fld in ('day_off','makeup_day'):
                if vals.get(fld):
                    d = vals[fld]
                    if isinstance(d, str):
                        d = fields.Date.from_string(d)
                    dates.append(d)
            if dates:
                self.search([
                    '|', ('day_off','in',dates), ('makeup_day','in',dates),
                ]).unlink()
            return super().create(vals)

        return super().create(vals)

    def write(self, vals):
        # giữ nguyên logic write cũ của bạn
        if vals.get('saturday_type') == 'alternate' \
           or 'week_pattern_alternate' in vals \
           or ('month' in vals and self.saturday_type == 'alternate'):
            self.unlink()
            return self.create({
                **{f: getattr(self, f) for f in [
                    'name','saturday_type','month','week_pattern_alternate','apply_all_employees'
                ]},
                'employee_ids': [(6,0,self.employee_ids.ids)]
            })
        if 'day_off' in vals or 'makeup_day' in vals:
            dates = []
            for fld in ('day_off','makeup_day'):
                if fld in vals:
                    d = vals[fld]
                    if isinstance(d, str):
                        d = fields.Date.from_string(d)
                    dates.append(d)
            if dates:
                self.search([
                    ('id','not in', self.ids),
                    '|', ('day_off','in',dates), ('makeup_day','in',dates),
                ]).unlink()
        return super().write(vals)

    def unlink(self):
        return super().unlink()
