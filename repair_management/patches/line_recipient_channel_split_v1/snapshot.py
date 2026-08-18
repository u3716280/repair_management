from __future__ import annotations

import json
import os

import frappe
from frappe.utils import now_datetime

RECIPIENT_BASE_FIELDS = [
    "name",
    "line_channel",
    "recipient_type",
    "recipient_id",
    "line_user_id",
    "display_name",
    "picture_url",
    "status_message",
    "enabled",
    "allow_mark_attendance",
    "following_status",
    "first_seen_at",
    "last_seen_at",
    "last_event_type",
    "last_profile_sync_at",
    "profile_sync_error",
    "modified",
]


def capture() -> str:
    """Dump everything the schema-trim migration needs, before the schema changes.

    Must run BEFORE the trimmed `LINE Recipient` doctype JSON is migrated --
    `apply.py` reads this file instead of the (by-then columnless) live table.
    """
    meta = frappe.get_meta("LINE Recipient")
    fields = list(RECIPIENT_BASE_FIELDS)
    if meta.has_field("allow_delivery_confirm"):
        fields.append("allow_delivery_confirm")

    # frappe.get_all()/get_list() silently drops any field whose name merely
    # *contains* "_seen" as a substring (frappe.model.db_query.DatabaseQuery
    # .set_optional_columns() does `f in fld` instead of `f == fld` against the
    # reserved optional field "_seen", stripping first_seen_at/last_seen_at on
    # any doctype lacking a literal "_seen" column). Raw SQL sidesteps it.
    quoted = ", ".join(f"`{f}`" for f in fields)
    recipients = frappe.db.sql(f"select {quoted} from `tabLINE Recipient`", as_dict=True)

    assignments = []
    if frappe.db.exists("DocType", "LINE Rich Menu Recipient Assignment"):
        assignments = frappe.get_all(
            "LINE Rich Menu Recipient Assignment",
            fields=["name", "recipient"],
            limit_page_length=0,
        )

    delivery_confirmations = []
    if frappe.db.exists("DocType", "Delivery Confirmation"):
        delivery_confirmations = frappe.get_all(
            "Delivery Confirmation",
            fields=["name", "line_recipient"],
            limit_page_length=0,
        )

    payload = {
        "captured_at": now_datetime().isoformat(),
        "recipients": recipients,
        "assignments": assignments,
        "delivery_confirmations": delivery_confirmations,
    }

    backup_dir = frappe.get_site_path("private", "backups")
    os.makedirs(backup_dir, exist_ok=True)
    ts = now_datetime().strftime("%Y%m%d_%H%M%S")
    path = os.path.join(backup_dir, f"line_recipient_channel_split_snapshot_{ts}.json")
    with open(path, "w") as f:
        json.dump(payload, f, indent=1, default=str)

    return path


def latest_snapshot_path() -> str | None:
    backup_dir = frappe.get_site_path("private", "backups")
    if not os.path.isdir(backup_dir):
        return None
    candidates = sorted(
        f for f in os.listdir(backup_dir) if f.startswith("line_recipient_channel_split_snapshot_")
    )
    if not candidates:
        return None
    return os.path.join(backup_dir, candidates[-1])
