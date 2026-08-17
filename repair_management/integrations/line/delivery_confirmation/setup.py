from __future__ import annotations

from contextlib import contextmanager

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


POD_ROLE = "LINE POD Integration"


@contextmanager
def _as_administrator():
    original = getattr(getattr(frappe, "session", None), "user", None) or "Guest"
    frappe.set_user("Administrator")
    try:
        yield
    finally:
        frappe.set_user(original)


def _ensure_role():
    if not frappe.db.exists("Role", POD_ROLE):
        frappe.get_doc({"doctype": "Role", "role_name": POD_ROLE}).insert()


def _integration_users() -> list[str]:
    users = []
    if frappe.db.exists("DocType", "LINE Channel"):
        meta = frappe.get_meta("LINE Channel")
        if meta.has_field("integration_user"):
            users.extend(
                row.integration_user
                for row in frappe.get_all(
                    "LINE Channel",
                    filters={"integration_user": ["is", "set"]},
                    fields=["integration_user"],
                    limit_page_length=0,
                )
                if row.integration_user
            )
    if frappe.db.exists("DocType", "LINE Sales Order Settings"):
        meta = frappe.get_meta("LINE Sales Order Settings")
        if meta.has_field("integration_user") and meta.issingle:
            value = frappe.db.get_single_value("LINE Sales Order Settings", "integration_user")
            if value:
                users.append(value)
    return list(dict.fromkeys(users))


def _grant_role_to_integration_users():
    granted = []
    for user_name in _integration_users():
        if not frappe.db.exists("User", user_name):
            continue
        user = frappe.get_doc("User", user_name)
        if POD_ROLE not in frappe.get_roles(user.name):
            user.add_roles(POD_ROLE)
        granted.append(user_name)
    return granted


def prepare():
    """Create the POD runtime role before migrate syncs DocType permissions."""
    with _as_administrator():
        _ensure_role()
        users = _grant_role_to_integration_users()
    return {"ok": True, "role": POD_ROLE, "integration_users": users}


def apply():
    with _as_administrator():
        create_custom_fields(
            {
            "LINE Recipient": [
                {
                    "fieldname": "allow_delivery_confirm",
                    "label": "Allow Delivery Confirm",
                    "fieldtype": "Check",
                    "insert_after": "allow_mark_attendance"
                    if frappe.get_meta("LINE Recipient").has_field("allow_mark_attendance")
                    else "enabled",
                    "default": "0",
                }
            ]
            },
            update=True,
        )
        _ensure_role()
        users = _grant_role_to_integration_users()
        frappe.clear_cache(doctype="LINE Recipient")
        frappe.clear_cache(doctype="Delivery Confirmation")
    return {
        "ok": True,
        "field": "LINE Recipient.allow_delivery_confirm",
        "role": POD_ROLE,
        "integration_users": users,
    }


def check():
    confirmation_meta = (
        frappe.get_meta("Delivery Confirmation")
        if frappe.db.exists("DocType", "Delivery Confirmation")
        else None
    )
    users = _integration_users()
    result = {
        "delivery_confirmation_doctype": bool(confirmation_meta),
        "recipient_allow_field": frappe.get_meta("LINE Recipient").has_field("allow_delivery_confirm"),
        "chat_notification_fields": bool(
            confirmation_meta
            and all(
                confirmation_meta.has_field(field)
                for field in (
                    "chat_notification_status",
                    "chat_notification_error",
                    "chat_notified_at",
                )
            )
        ),
        "pod_role": bool(frappe.db.exists("Role", POD_ROLE)),
        "integration_users": users,
        "integration_users_with_pod_role": [
            user for user in users
            if frappe.db.exists("User", user) and POD_ROLE in frappe.get_roles(user)
        ],
        "line_channel": bool(frappe.db.exists("DocType", "LINE Channel")),
    }
    if result["line_channel"]:
        meta = frappe.get_meta("LINE Channel")
        result["mini_app_channel_id_field"] = meta.has_field("mini_app_channel_id")
        result["liff_candidates"] = [
            df.fieldname
            for df in meta.fields
            if "liff" in (df.fieldname or "").lower()
            or "liff" in (df.label or "").lower()
        ]
    return result
