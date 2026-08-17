from __future__ import annotations

import frappe

from repair_management.integrations.line.delivery_confirmation.auth import authenticate
from repair_management.integrations.line.delivery_confirmation.service import confirm as confirm_service
from repair_management.integrations.line.delivery_confirmation.service import report_chat_notification as report_chat_notification_service
from repair_management.integrations.line.delivery_confirmation.service import sales_order_view


def _liff_field(meta):
    preferred = ["mini_app_liff_id", "liff_id", "mini_app_id"]
    for fieldname in preferred:
        if meta.has_field(fieldname):
            return fieldname
    for df in meta.fields:
        label = (df.label or "").lower()
        fieldname = (df.fieldname or "").lower()
        if "liff" in label or "liff" in fieldname:
            return df.fieldname
    return None


@frappe.whitelist(allow_guest=True)
def config():
    """Public MINI App bootstrap config. LIFF ID and Channel name are not secrets."""
    if not frappe.db.exists("DocType", "LINE Channel"):
        frappe.throw("LINE Channel DocType not found", frappe.ValidationError)
    meta = frappe.get_meta("LINE Channel")
    liff_field = _liff_field(meta)
    if not liff_field:
        frappe.throw("ไม่พบ LIFF ID field ใน LINE Channel", frappe.ValidationError)

    filters = {}
    if meta.has_field("enabled"):
        filters["enabled"] = 1
    has_channel_id_field = meta.has_field("mini_app_channel_id")
    fields = ["name", liff_field]
    if has_channel_id_field:
        fields.append("mini_app_channel_id")
    rows = frappe.get_all(
        "LINE Channel",
        filters=filters,
        fields=fields,
        order_by="name",
    )
    # Require the same fields authenticate()/_get_channel() will require, so a
    # channel handed to the browser here never fails validation on the next call.
    candidates = [
        item
        for item in rows
        if item.get(liff_field) and (not has_channel_id_field or item.get("mini_app_channel_id"))
    ]
    if not candidates:
        frappe.throw("LINE MINI App ยังไม่ได้ตั้งค่า", frappe.ValidationError)

    # Multiple LINE Channel rows (distinct bots/webhooks) may legitimately share
    # one MINI App identity -- only fail when enabled channels disagree on which
    # LIFF app to open. Which single row is picked below doesn't matter:
    # authenticate() checks recipients across every enabled channel sharing that
    # identity, not just this one.
    identities = {(item.get(liff_field), item.get("mini_app_channel_id")) for item in candidates}
    if len(identities) != 1:
        frappe.throw("LINE MINI App configuration is ambiguous.", frappe.ValidationError)

    row = candidates[0]
    return {"channel_name": row.name, "liff_id": row.get(liff_field)}


@frappe.whitelist(allow_guest=True)
def bootstrap(id_token: str, channel_name: str):
    auth = authenticate(id_token, channel_name)
    return {
        "recipient": auth.recipient_name,
        "max_photos": 8,
        "min_photos": 1,
        "camera_only": True,
        "chat_message_write_required": True,
    }


@frappe.whitelist(allow_guest=True)
def scan_sales_order(id_token: str, channel_name: str, sales_order: str):
    auth = authenticate(id_token, channel_name)
    return sales_order_view(auth, sales_order)


@frappe.whitelist(allow_guest=True)
def confirm(id_token: str, channel_name: str, sales_order: str, request_id: str, latitude, longitude, accuracy=None, location_timestamp=None):
    auth = authenticate(id_token, channel_name)
    uploads = []
    if frappe.request and getattr(frappe.request, "files", None):
        uploads = frappe.request.files.getlist("photos")
    return confirm_service(
        auth,
        sales_order_name=sales_order,
        request_id=request_id,
        latitude=latitude,
        longitude=longitude,
        accuracy=accuracy,
        location_timestamp=location_timestamp,
        photos=uploads,
    )


@frappe.whitelist(allow_guest=True)
def report_chat_notification(id_token: str, channel_name: str, confirmation: str, status: str, error=None):
    auth = authenticate(id_token, channel_name)
    return report_chat_notification_service(auth, confirmation, status, error)
