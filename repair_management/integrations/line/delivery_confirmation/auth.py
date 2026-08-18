from __future__ import annotations

from contextlib import contextmanager

import frappe
from frappe.utils import cint

from repair_management.integrations.line.attendance.auth import _verify_id_token


ALLOW_FIELD = "allow_delivery_confirm"

POD_CHANNEL_FIELDS = ["name", "enabled", "integration_user", "mini_app_channel_id", "mini_app_liff_id"]


def _get_channel(channel_name: str):
    """Resolve and validate the LINE Channel used for Delivery Confirmation.

    Deliberately independent of attendance's channel checks: POD does not use
    ``default_company``, so it must not be required here. This must stay in sync
    with ``api.config()``'s own channel-selection criteria, or a channel that
    ``config()`` hands to the browser can fail here right after.
    """
    if not channel_name:
        frappe.throw("LINE MINI App configuration is missing.", frappe.ValidationError)

    channel = frappe.db.get_value("LINE Channel", channel_name, POD_CHANNEL_FIELDS, as_dict=True)
    if not channel or not channel.enabled:
        frappe.throw("LINE Channel is not available.", frappe.PermissionError)
    if not channel.mini_app_channel_id or not channel.mini_app_liff_id:
        frappe.throw("LINE MINI App configuration is incomplete.", frappe.ValidationError)
    return channel


def authenticate(id_token: str, channel_name: str):
    """Verify LINE ID token and resolve an enabled POD-authorized Recipient.

    Authorization is now purely person-level: `LINE Recipient` is one row per
    physical LINE user (see services/recipient.py), so there is no more
    per-channel duplication to scan or guess between here.
    """
    channel = _get_channel(channel_name)
    payload = _verify_id_token(id_token, channel.mini_app_channel_id)
    line_user_id = (payload.get("sub") or "").strip()
    if not line_user_id:
        frappe.throw("LINE identity is missing", frappe.AuthenticationError)

    meta = frappe.get_meta("LINE Recipient")
    if not meta.has_field(ALLOW_FIELD):
        frappe.throw(
            "LINE Recipient ยังไม่มีฟิลด์ Allow Delivery Confirm กรุณารัน POD setup",
            frappe.ValidationError,
        )

    fields = ["name", "enabled", ALLOW_FIELD]
    if meta.has_field("employee"):
        fields.append("employee")

    row = frappe.db.get_value("LINE Recipient", line_user_id, fields, as_dict=True)
    if not row or not cint(row.enabled) or not cint(row.get(ALLOW_FIELD)):
        frappe.throw("ไม่มีสิทธิ์ใช้งาน Proof of Delivery", frappe.PermissionError)

    return frappe._dict(
        channel=channel,
        recipient_name=row.name,
        line_user_id=line_user_id,
        employee=row.get("employee"),
        token_payload=payload,
    )


def get_integration_user() -> str:
    """Return the configured LINE Integration User; never fall back to Administrator."""
    candidates = (
        ("LINE Channel", "integration_user"),
        ("LINE Sales Order Settings", "integration_user"),
    )
    for doctype, fieldname in candidates:
        if not frappe.db.exists("DocType", doctype):
            continue
        meta = frappe.get_meta(doctype)
        if not meta.has_field(fieldname):
            continue
        if meta.issingle:
            value = frappe.db.get_single_value(doctype, fieldname)
            if value:
                return value
        elif doctype == "LINE Channel":
            # A channel-specific value is preferred, but caller may not know the
            # channel here. The service normally supplies one explicitly.
            value = frappe.db.get_value(doctype, {fieldname: ["is", "set"]}, fieldname)
            if value:
                return value
    frappe.throw("LINE Integration User is not configured", frappe.ValidationError)


def integration_user_for_channel(channel) -> str:
    value = getattr(channel, "integration_user", None)
    if value:
        return value
    return get_integration_user()


@contextmanager
def as_integration_user(channel):
    original_user = frappe.session.user
    integration_user = integration_user_for_channel(channel)
    if not frappe.db.exists("User", integration_user):
        frappe.throw("Configured LINE Integration User does not exist", frappe.ValidationError)
    frappe.set_user(integration_user)
    try:
        yield integration_user
    finally:
        frappe.set_user(original_user)
