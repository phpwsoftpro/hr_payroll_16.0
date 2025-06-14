from odoo import models, fields, api


class AccountMoveLine(models.Model):
    _inherit = "account.move.line"

    is_bank_fee = fields.Boolean(string="Bank Fee Line", default=False)
    is_discount = fields.Boolean(string="Discount Line", default=False)


class AccountMove(models.Model):
    _inherit = "account.move"

    discount = fields.Monetary(
        string="Discount",
        currency_field="currency_id",
        default=0.0,
        store=True,
        copy=True,  # Make sure the value is copied when duplicating
    )

    bank_fee = fields.Monetary(
        string="Bank Fee",
        currency_field="currency_id",
        default=0.0,
        store=True,
        copy=True,
    )
    # Subtotal (Tổng phụ)
    subtotal = fields.Monetary(
        string="Subtotal",
        compute="_compute_subtotal",
        store=True,
        readonly=True,
    )

    # Thuế
    tax_rate = fields.Monetary(
        string="Tax Rate",
        compute="_compute_tax_rate",
        store=True,
        currency_field="currency_id",
    )

    # Tổng tiền chưa có thuế
    amount_untaxed = fields.Monetary(
        string="Amount Untaxed",
        compute="_compute_amount_untaxed",
        store=True,
        currency_field="currency_id",
    )

    invoice_line_ids = fields.One2many(
        "account.move.line",
        "move_id",
        domain=[
            ("is_bank_fee", "=", False),
            ("is_discount", "=", False),
        ],  # Ẩn Bank Fee khỏi UI
        string="Invoice Lines",
    )

    # Tính Subtotal từ các dòng hóa đơn
    @api.depends("invoice_line_ids.price_subtotal")
    def _compute_subtotal(self):
        for move in self:
            move.subtotal = sum(
                line.price_subtotal or 0.0 for line in move.invoice_line_ids
            )

    # Tính tổng tiền chưa có thuế (thực ra có thể dùng luôn subtotal)
    @api.depends("invoice_line_ids.price_subtotal")
    def _compute_amount_untaxed(self):
        for move in self:
            move.amount_untaxed = move.subtotal

    # Tính tổng thuế dựa trên dòng hóa đơn
    @api.depends("subtotal", "invoice_line_ids.tax_ids")
    def _compute_tax_rate(self):
        for move in self:
            move.tax_rate = (
                sum(
                    line.price_subtotal * sum(tax.amount / 100 for tax in line.tax_ids)
                    for line in move.invoice_line_ids
                    if line.tax_ids
                )
                if move.invoice_line_ids
                else 0.0
            )

    @api.depends("amount_total", "bank_fee", "discount", "payment_state")
    def _compute_amount_residual(self):
        for move in self:
            if self.env.context.get("prevent_write"):
                continue  # 🚀 Tránh vòng lặp vô hạn

            paid_amount = sum(move.payment_ids.mapped("amount"))
            move.amount_residual = (
                (move.amount_total - paid_amount) + move.bank_fee - move.discount
            )

    @api.model_create_multi
    def create(self, vals_list):
        records = super(AccountMove, self).create(vals_list)
        for record in records:
            account_id = record.journal_id.default_account_id.id
            if not account_id:
                raise ValueError(
                    "Không tìm thấy tài khoản kế toán hợp lệ cho Bank Fee/Discount."
                )

            # 🚀 Tạo Bank Fee nếu có
            if record.bank_fee > 0:
                self.env["account.move.line"].create(
                    {
                        "move_id": record.id,
                        "name": "Bank Fee",
                        "quantity": 1,
                        "price_unit": record.bank_fee,
                        "account_id": account_id,
                        "credit": record.bank_fee,
                        "debit": 0.00,
                        "partner_id": record.partner_id.id,
                        "company_id": record.company_id.id,
                        "currency_id": record.currency_id.id,
                        "date": record.invoice_date,
                        "tax_ids": [(6, 0, [])],  # Không áp thuế
                        "is_bank_fee": True,
                    }
                )

            # 🚀 Tạo Discount nếu có
            if record.discount > 0:
                self.env["account.move.line"].create(
                    {
                        "move_id": record.id,
                        "name": "Discount",
                        "quantity": 1,
                        "price_unit": -record.discount,  # Chiết khấu là giá trị âm
                        "account_id": account_id,
                        "credit": 0.00,
                        "debit": record.discount,
                        "partner_id": record.partner_id.id,
                        "company_id": record.company_id.id,
                        "currency_id": record.currency_id.id,
                        "date": record.invoice_date,
                        "tax_ids": [(6, 0, [])],  # Không áp thuế
                        "is_discount": True,
                    }
                )

        return records

    def write(self, vals):
        res = super(AccountMove, self).write(vals)
        for record in self:
            account_id = record.journal_id.default_account_id.id
            if not account_id:
                raise ValueError(
                    "Không tìm thấy tài khoản kế toán hợp lệ cho Bank Fee/Discount."
                )

            # 🚀 Cập nhật Bank Fee nếu có thay đổi
            if "bank_fee" in vals:
                existing_fee_line = record.line_ids.filtered(lambda l: l.is_bank_fee)
                if existing_fee_line:
                    existing_fee_line.unlink()

                self.env["account.move.line"].create(
                    {
                        "move_id": record.id,
                        "name": "Bank Fee",
                        "quantity": 1,
                        "price_unit": vals["bank_fee"],
                        "account_id": account_id,
                        "credit": vals["bank_fee"],
                        "debit": 0.00,
                        "tax_ids": [(5, 0, 0)],  # Không áp thuế
                        "partner_id": record.partner_id.id,
                        "company_id": record.company_id.id,
                        "currency_id": record.currency_id.id,
                        "date": record.invoice_date,
                        "is_bank_fee": True,
                    }
                )

            # 🚀 Cập nhật Discount nếu có thay đổi
            if "discount" in vals:
                existing_discount_line = record.line_ids.filtered(
                    lambda l: l.is_discount
                )
                if existing_discount_line:
                    existing_discount_line.unlink()

                self.env["account.move.line"].create(
                    {
                        "move_id": record.id,
                        "name": "Discount",
                        "quantity": 1,
                        "price_unit": -vals["discount"],  # Chiết khấu là giá trị âm
                        "account_id": account_id,
                        "credit": 0.00,
                        "debit": vals["discount"],
                        "tax_ids": [(5, 0, 0)],  # Không áp thuế
                        "partner_id": record.partner_id.id,
                        "company_id": record.company_id.id,
                        "currency_id": record.currency_id.id,
                        "date": record.invoice_date,
                        "is_discount": True,
                    }
                )

            # 🚀 Cập nhật số dư nhưng tránh lặp vô hạn
            record.with_context(prevent_write=True)._compute_amount_residual()

        return res

    def action_view_invoice_lines(self):
        action = super().action_view_invoice_lines()
        if action.get("domain"):
            action["domain"].append(("is_bank_fee", "=", False))
        else:
            action["domain"] = [("is_bank_fee", "=", False)]
        return action
