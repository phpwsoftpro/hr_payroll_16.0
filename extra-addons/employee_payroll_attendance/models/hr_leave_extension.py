from odoo import models, fields

class HrLeave(models.Model):
    _inherit = 'hr.leave'

    is_legal_leave = fields.Boolean(string="Is Legal Leave", default=True)
