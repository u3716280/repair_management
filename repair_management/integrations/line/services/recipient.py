from __future__ import annotations

import hashlib

import frappe
from frappe.utils import now_datetime, time_diff_in_hours

from repair_management.integrations.line.api.client import LineClient


def _identity(source: dict) -> tuple[str | None, str | None]:
    source_type = (source or {}).get("type")
    if source_type == "user":
        return "User", source.get("userId")
    if source_type == "group":
        return "Group", source.get("groupId")
    if source_type == "room":
        return "Room", source.get("roomId")
    return None, None


def recipient_name(channel: str, recipient_type: str, recipient_id: str) -> str:
    raw = f"{channel}:{recipient_type}:{recipient_id}"
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:20].upper()
    return f"LINE-REC-{digest}"


def _profile_due(doc, event_type: str) -> bool:
    if doc.recipient_type != "User":
        return False
    if event_type == "follow" or not doc.display_name or not doc.last_profile_sync_at:
        return True
    return time_diff_in_hours(now_datetime(), doc.last_profile_sync_at) >= 24


def upsert_from_event(channel: str, event: dict):
    recipient_type, recipient_id = _identity(event.get("source") or {})
    if not recipient_type or not recipient_id:
        return None

    name = recipient_name(channel, recipient_type, recipient_id)
    now = now_datetime()
    if frappe.db.exists("LINE Recipient", name):
        doc = frappe.get_doc("LINE Recipient", name)
    else:
        doc = frappe.new_doc("LINE Recipient")
        doc.line_channel = channel
        doc.recipient_type = recipient_type
        doc.recipient_id = recipient_id
        doc.first_seen_at = now
        doc.following_status = "Unknown"
        doc.enabled = 1

    event_type = event.get("type") or "unknown"
    doc.last_seen_at = now
    doc.last_event_type = event_type
    if event_type == "follow":
        doc.following_status = "Following"
        doc.enabled = 1
    elif event_type == "unfollow":
        doc.following_status = "Unfollowed"

    if _profile_due(doc, event_type):
        try:
            profile = LineClient(channel).get_profile(recipient_id)
            doc.display_name = profile.get("displayName") or doc.display_name
            doc.picture_url = profile.get("pictureUrl") or doc.picture_url
            doc.status_message = profile.get("statusMessage") or doc.status_message
            doc.last_profile_sync_at = now
            doc.profile_sync_error = None
        except Exception as exc:
            doc.profile_sync_error = str(exc)[:2000]

    doc.save(ignore_permissions=True) if doc.name else doc.insert(ignore_permissions=True)
    return doc
