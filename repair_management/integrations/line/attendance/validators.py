from __future__ import annotations

from datetime import date
from zoneinfo import ZoneInfo

import frappe
from frappe.utils import add_days, add_months, getdate, now_datetime

BANGKOK_TZ = ZoneInfo("Asia/Bangkok")
ALLOWED_STATUSES = {"Present", "Absent"}


def bangkok_today() -> date:
    current = now_datetime()
    if current.tzinfo is None:
        current = current.replace(tzinfo=ZoneInfo("UTC"))
    return current.astimezone(BANGKOK_TZ).date()


def get_date_limits() -> tuple[date, date, date]:
    today = bangkok_today()
    minimum = getdate(add_months(today, -1))
    maximum = getdate(add_days(today, 7))
    return minimum, today, maximum


def validate_attendance_date(value) -> date:
    attendance_date = getdate(value)
    minimum, _today, maximum = get_date_limits()
    if attendance_date < minimum or attendance_date > maximum:
        frappe.throw(
            f"วันที่ต้องอยู่ระหว่าง {minimum.isoformat()} และ {maximum.isoformat()}",
            frappe.ValidationError,
        )
    return attendance_date


def get_company_holiday_list(company: str) -> str | None:
    company_doc = frappe.get_doc("Company", company)
    company_doc.check_permission("read")
    return company_doc.default_holiday_list or None


def is_company_holiday(company: str, attendance_date: date) -> bool:
    holiday_list = get_company_holiday_list(company)
    if not holiday_list:
        return False

    holiday_doc = frappe.get_doc("Holiday List", holiday_list)
    holiday_doc.check_permission("read")
    target = getdate(attendance_date)
    return any(getdate(row.holiday_date) == target for row in holiday_doc.holidays)


def get_eligible_employees(company: str) -> list[dict]:
    return frappe.get_list(
        "Employee",
        filters={
            "company": company,
            "status": "Active",
            "employment_type": "Full-time",
        },
        fields=["name", "employee_name", "company", "default_shift"],
        order_by="employee_name asc, name asc",
        limit_page_length=0,
    )


def validate_status(status: str) -> str:
    if status not in ALLOWED_STATUSES:
        frappe.throw("Attendance status is not allowed.", frappe.ValidationError)
    return status
