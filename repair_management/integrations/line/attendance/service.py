from __future__ import annotations

from collections.abc import Iterable

import frappe

from repair_management.integrations.line.attendance.auth import AttendanceAuthContext, as_integration_user
from repair_management.integrations.line.attendance.validators import (
    get_date_limits,
    get_eligible_employees,
    is_company_holiday,
    validate_attendance_date,
    validate_status,
)


def _existing_attendance(employee: str, attendance_date):
    rows = frappe.get_list(
        "Attendance",
        filters={
            "employee": employee,
            "attendance_date": attendance_date,
            "docstatus": ["<", 2],
        },
        fields=["name", "status", "docstatus"],
        order_by="modified desc",
        limit_page_length=1,
    )
    return rows[0] if rows else None


def _existing_attendance_map(employee_names: list[str], attendance_date) -> dict[str, dict]:
    if not employee_names:
        return {}

    rows = frappe.get_list(
        "Attendance",
        filters={
            "employee": ["in", employee_names],
            "attendance_date": attendance_date,
            "docstatus": ["<", 2],
        },
        fields=["name", "employee", "status", "docstatus", "modified"],
        order_by="modified desc",
        limit_page_length=0,
    )
    result = {}
    for row in rows:
        result.setdefault(row.employee, row)
    return result


def get_attendance_view(auth: AttendanceAuthContext, attendance_date) -> dict:
    attendance_date = validate_attendance_date(attendance_date)

    with as_integration_user(auth):
        if is_company_holiday(auth.default_company, attendance_date):
            return {
                "attendance_date": attendance_date.isoformat(),
                "holiday": True,
                "holiday_message": "วันนี้เป็นวันหยุด ไม่ต้อง Mark Attendance",
                "employees": [],
            }

        employees = get_eligible_employees(auth.default_company)
        existing = _existing_attendance_map([row.name for row in employees], attendance_date)

        rows = []
        for employee in employees:
            marked = existing.get(employee.name)
            rows.append(
                {
                    "employee": employee.name,
                    "employee_name": employee.employee_name or employee.name,
                    "existing": bool(marked),
                    "status": marked.status if marked else "Present",
                }
            )

    return {
        "attendance_date": attendance_date.isoformat(),
        "holiday": False,
        "employees": rows,
    }


def _selection_map(selections: Iterable[dict] | None) -> dict[str, str]:
    result = {}
    for row in selections or []:
        if not isinstance(row, dict):
            continue
        employee = row.get("employee")
        status = row.get("status")
        if not employee:
            continue
        result[str(employee)] = validate_status(status)
    return result


def _employee_lock(employee: str, attendance_date):
    lock_name = f"line-miniapp-attendance:{employee}:{attendance_date.isoformat()}"
    key = frappe.cache.make_key(lock_name)
    return frappe.cache.lock(key, timeout=60, blocking_timeout=15)


def _create_and_submit(employee, attendance_date, status: str) -> str:
    attendance = frappe.get_doc(
        {
            "doctype": "Attendance",
            "employee": employee.name,
            "attendance_date": attendance_date,
            "status": status,
            "company": employee.company,
            "shift": employee.default_shift or None,
        }
    )
    attendance.flags.line_mark_attendance_status = status

    previous_mute = getattr(frappe.flags, "mute_messages", False)
    frappe.flags.mute_messages = True
    try:
        attendance.insert()
        attendance.submit()
    finally:
        frappe.flags.mute_messages = previous_mute

    return attendance.name


def submit_attendance(
    auth: AttendanceAuthContext,
    attendance_date,
    selections: Iterable[dict] | None,
) -> dict:
    attendance_date = validate_attendance_date(attendance_date)
    selected = _selection_map(selections)
    errors = []
    created = []

    with as_integration_user(auth):
        if is_company_holiday(auth.default_company, attendance_date):
            return {
                "attendance_date": attendance_date.isoformat(),
                "holiday": True,
                "errors": [],
            }

        # Re-query at submit time. Anything no longer Active + Full-time + in
        # the default company simply falls out of the eligible set and is skipped.
        employees = get_eligible_employees(auth.default_company)

        for employee in employees:
            status = selected.get(employee.name, "Present")
            try:
                status = validate_status(status)
                frappe.db.savepoint("line_attendance_employee")

                with _employee_lock(employee.name, attendance_date):
                    # Create-only: a Draft or Submitted Attendance always wins.
                    if _existing_attendance(employee.name, attendance_date):
                        continue

                    attendance_name = _create_and_submit(employee, attendance_date, status)
                    frappe.db.commit()  # successful employees must survive later per-row failures
                    created.append(attendance_name)
            except Exception:
                frappe.db.rollback(save_point="line_attendance_employee")
                frappe.log_error(
                    title="LINE MINI App Attendance",
                    message=frappe.get_traceback(with_context=True),
                )
                errors.append(
                    {
                        "employee": employee.name,
                        "employee_name": employee.employee_name or employee.name,
                        "message": "บันทึกไม่สำเร็จ",
                    }
                )

    return {
        "attendance_date": attendance_date.isoformat(),
        "holiday": False,
        "created": created,
        "errors": errors,
    }


def bootstrap_data() -> dict:
    minimum, today, maximum = get_date_limits()
    return {
        "today": today.isoformat(),
        "min_date": minimum.isoformat(),
        "max_date": maximum.isoformat(),
    }
