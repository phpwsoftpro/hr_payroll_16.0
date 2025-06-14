import requests
import base64
import io
import pandas as pd
import logging
from odoo import models, fields, api
from odoo.exceptions import UserError
from datetime import datetime

_logger = logging.getLogger(__name__)


class HrPayslipUpdateRateWizard(models.TransientModel):
    _name = "hr.payslip.update.rate.wizard"
    _description = "Update Rate Fallback Wizard"

    currency_rate_fallback = fields.Float(string="USD Buy Cash Rate")
    chosen_date = fields.Date(string="Choose Date", default=fields.Date.context_today)

    @api.model
    def default_get(self, fields_list):
        """Fetch the exchange rate when the wizard is opened"""
        defaults = super().default_get(fields_list)
        today = fields.Date.context_today(self)
        defaults["currency_rate_fallback"] = self.fetch_usd_exchange_rate(
            today.strftime("%Y-%m-%d")
        )
        return defaults

    def fetch_usd_exchange_rate(self, date):
        """Fetch USD exchange rate (Buy Cash) from Vietcombank API for a chosen date"""
        base_url = (
            f"https://www.vietcombank.com.vn/api/exchangerates/exportexcel?date={date}"
        )
        headers = {"User-Agent": "Mozilla/5.0"}

        try:
            _logger.info(f"Fetching exchange rate from URL: {base_url}")
            response = requests.get(base_url, headers=headers, timeout=10)

            if response.status_code != 200:
                _logger.error(
                    f"Failed to fetch exchange rate, status code: {response.status_code}"
                )
                return 0.0

            response_json = response.json()
            _logger.info(f"API Response JSON keys: {response_json.keys()}")

            base64_data = response_json.get("Data")
            if not base64_data:
                _logger.error("No 'Data' field found in API response.")
                return 0.0

            decoded_content = base64.b64decode(base64_data)

            with open("/tmp/exchange_rate.xlsx", "wb") as f:
                f.write(decoded_content)
            _logger.info("Saved Excel file to /tmp/exchange_rate.xlsx")

            excel_data = io.BytesIO(decoded_content)
            df = pd.read_excel(excel_data, engine="openpyxl", dtype=str)

            if df.shape[1] < 5:
                _logger.error("Unexpected column structure in exchange rate file.")
                return 0.0

            df.columns = [
                "Currency Code",
                "Currency Name",
                "Buy Cash",
                "Buy Transfer",
                "Sell",
            ]
            df = df.dropna(subset=["Currency Code"])

            usd_row = df[df["Currency Code"].str.contains("USD", na=False, case=False)]
            if usd_row.empty:
                _logger.warning("USD exchange rate not found.")
                return 0.0

            rate_value = usd_row.iloc[0]["Buy Cash"]
            _logger.info(f"Raw Buy Cash rate value: {rate_value}")

            try:
                cleaned_rate = float(str(rate_value).replace(",", ""))
                _logger.info(f"Fetched USD exchange rate: {cleaned_rate}")
                return cleaned_rate
            except ValueError as e:
                _logger.error(f"Error converting exchange rate: {e}")
                return 0.0

        except Exception as e:
            _logger.error(f"Error processing exchange rate data: {e}")
            return 0.0

    def action_choose_date(self):
        """Fetch exchange rate for the chosen date and update the wizard"""
        if not self.chosen_date:
            raise UserError("Please select a date to fetch the exchange rate.")

        new_rate = self.fetch_usd_exchange_rate(self.chosen_date.strftime("%Y-%m-%d"))

        if new_rate <= 0:
            raise UserError(
                "Failed to fetch a valid exchange rate for the chosen date."
            )

        self.write({"currency_rate_fallback": new_rate})
        _logger.info(
            f"Updated exchange rate in wizard for {self.chosen_date}: {new_rate}"
        )

        return {
            "type": "ir.actions.act_window",
            "res_model": "hr.payslip.update.rate.wizard",
            "view_mode": "form",
            "res_id": self.id,
            "target": "new",
            "context": dict(self.env.context),
        }

    def action_apply_to_payslips(self):
        """Lấy giá trị currency_rate_fallback từ wizard và áp dụng cho các payslip đã chọn,
        giữ nguyên các giá trị khi các cờ True và tính toán lại các giá trị còn lại.
        """
        self.ensure_one()

        active_ids = self.env.context.get("active_ids", [])
        if not active_ids:
            raise UserError("No payslips selected to update.")

        if self.currency_rate_fallback <= 0:
            raise UserError("No valid exchange rate value found in wizard.")

        payslips = self.env["hr.payslip"].browse(active_ids)
        if not payslips:
            raise UserError("No Payslip records found.")

        for payslip in payslips:
            update_values = {"currency_rate_fallback": self.currency_rate_fallback}

            if payslip.include_saturdays or payslip.dev_inhouse:
                # Giữ nguyên monthly_wage_vnd, tính lại wage
                update_values.update(
                    {
                        "rate_lock_field": "monthly_wage_vnd",
                        # "wage": payslip.monthly_wage_vnd / self.currency_rate_fallback,
                    }
                )
            elif payslip.is_hourly_vnd:
                # Giữ nguyên hourly_rate_vnd
                update_values.update(
                    {
                        "rate_lock_field": "hourly_rate_vnd",
                    }
                )
            elif payslip.is_hourly_usd:
                # Giữ nguyên hourly_rate (USD), tính lại monthly_wage_vnd
                update_values.update(
                    {
                        "rate_lock_field": "hourly_rate",
                        # "monthly_wage_vnd": payslip.hourly_rate
                        # * payslip.worked_hours
                        # * self.currency_rate_fallback,
                    }
                )
            else:
                # Giữ nguyên wage (USD), tính lại monthly_wage_vnd
                update_values.update(
                    {
                        "rate_lock_field": "wage",
                        # "monthly_wage_vnd": payslip.wage * self.currency_rate_fallback,
                    }
                )

            payslip.sudo().write(update_values)

        _logger.info(
            f"Applied exchange rate {self.currency_rate_fallback} to Payslips: {active_ids}"
        )

        payslips._recalculate_total_salary()
        payslips._onchange_salary_fields()
        payslips._onchange_bonus_vnd()

        return {"type": "ir.actions.act_window_close"}
