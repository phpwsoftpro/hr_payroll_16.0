{
    "name": "Employee Payroll Based on Attendance Approval",
    "version": "16.0.1.0.0",
    "category": "Human Resources",
    "summary": "Calculate payroll based on approved attendance records",
    "description": "<p>This module integrates attendance approval into payroll calculation in Odoo.</p>"
    "<p>It enhances accuracy in salary computation by basing it on verified employee presence.</p>"
    "<ul>"
    "<li>Includes visual reporting tools</li>"
    "<li>Supports weekend work scheduling</li>"
    "<li>Fully integrated with Odoo HR & Payroll apps</li>"
    "</ul>",
    "author": "WSOFT  PRO Co. Ltd.",
    "maintainer": "WSOFT PRO Co. Ltd.",
    "license": "LGPL-3",
    "depends": [
        "hr_attendance",
        "sale_timesheet",
        "web",
        "base",
        "hr_timesheet",
        "sale_management",
        "resource",
        "hr",
        "hr_holidays",
    ],
    "assets": {
        "web.assets_backend": [
            "employee_payroll_attendance/static/src/css/custom_style.css",
            "employee_payroll_attendance/static/src/css/tree_view_sticky.css",
            "employee_payroll_attendance/static/src/js/custom_timeoff_dashboard.js",
        ]
    },
    "data": [
        "security/ir.model.access.csv",
        "views/hr_attendance_payroll_views.xml",
        "views/hr_payslip_views.xml",
        "views/hr_employee_payslip_views.xml",
        "views/generate_salary_wizard_views.xml",
        "views/account_analytic_line_views.xml",
        "views/custom_report_layout.xml",
        "views/hr_payslip_views_update.xml",
        "views/menu_reporting.xml",
        "views/custom_module_sale.xml",
        "views/work_saturday_schedule_view.xml",
    ],
    "installable": True,
    "application": False,
}
