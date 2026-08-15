from __future__ import annotations

import frappe

from repair_management.integrations.line.attendance.auth import authenticate
from repair_management.integrations.line.attendance.service import (
    bootstrap_data,
    get_attendance_view,
    submit_attendance as submit_attendance_service,
)


@frappe.whitelist(allow_guest=True)
def bootstrap(id_token: str, channel_name: str):
    authenticate(id_token, channel_name)
    return bootstrap_data()


@frappe.whitelist(allow_guest=True)
def get_attendance(id_token: str, channel_name: str, attendance_date: str):
    auth = authenticate(id_token, channel_name)
    return get_attendance_view(auth, attendance_date)


@frappe.whitelist(allow_guest=True)
def submit_attendance(
    id_token: str,
    channel_name: str,
    attendance_date: str,
    selections=None,
):
    auth = authenticate(id_token, channel_name)
    if isinstance(selections, str):
        selections = frappe.parse_json(selections)
    if selections is None:
        selections = []
    if not isinstance(selections, list):
        frappe.throw("Invalid attendance selection payload.", frappe.ValidationError)

    return submit_attendance_service(auth, attendance_date, selections)
