from __future__ import annotations

import frappe
from frappe.utils import now_datetime

from repair_management.integrations.line.delivery_confirmation.share import is_valid_pod_share_url


POD_TEXT_MARKER = "[POD]"


def is_pod_text_echo(event: dict) -> bool:
    if (event or {}).get("type") != "message":
        return False
    message = (event or {}).get("message") or {}
    if message.get("type") != "text":
        return False
    return str(message.get("text") or "").strip().startswith(POD_TEXT_MARKER)


def is_pod_image_echo(event: dict) -> bool:
    if (event or {}).get("type") != "message":
        return False
    message = (event or {}).get("message") or {}
    if message.get("type") != "image":
        return False
    provider = message.get("contentProvider") or {}
    if provider.get("type") != "external":
        return False
    urls = [provider.get("originalContentUrl"), provider.get("previewImageUrl")]
    return any(is_valid_pod_share_url(url) for url in urls if url)


def should_ignore_pod_echo(event: dict) -> bool:
    return is_pod_text_echo(event) or is_pod_image_echo(event)


def _mark_webhook_event_ignored(event_key: str | None) -> None:
    """Best-effort status update when the current router stores queued events.

    The POD echo guard must not depend on one exact LINE Webhook Event schema.
    If a compatible record/status field exists we mark it Ignored/Processed;
    otherwise the RQ job simply returns successfully.
    """
    if not event_key or not frappe.db.exists("DocType", "LINE Webhook Event"):
        return
    if not frappe.db.exists("LINE Webhook Event", event_key):
        return

    meta = frappe.get_meta("LINE Webhook Event")
    values = {}
    if meta.has_field("status"):
        field = meta.get_field("status")
        options = [row.strip() for row in str(field.options or "").splitlines() if row.strip()]
        if "Ignored" in options:
            values["status"] = "Ignored"
        elif "Processed" in options:
            values["status"] = "Processed"
    if meta.has_field("processed_at"):
        values["processed_at"] = now_datetime()
    if meta.has_field("error_message"):
        values["error_message"] = None
    if values:
        frappe.db.set_value("LINE Webhook Event", event_key, values, update_modified=False)


def ignore_pod_echo(event_key: str | None, event_payload: dict) -> bool:
    """Return True for POD messages echoed back by liff.sendMessages()."""
    if not should_ignore_pod_echo(event_payload):
        return False
    try:
        _mark_webhook_event_ignored(event_key)
    except Exception:
        # Echo suppression is more important than bookkeeping.  Do not route a
        # POD image/text into AI/media flows only because an optional log schema
        # differs on this site.
        frappe.log_error(
            title="LINE POD echo status update failed",
            message=frappe.get_traceback(),
        )
    return True
