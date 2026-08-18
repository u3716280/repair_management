from __future__ import annotations

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


def _profile_due(doc, event_type: str) -> bool:
    if doc.recipient_type != "User":
        return False
    if event_type == "follow" or not doc.display_name or not doc.last_profile_sync_at:
        return True
    return time_diff_in_hours(now_datetime(), doc.last_profile_sync_at) >= 24


def _identity_lock(recipient_type: str, recipient_id: str):
    raw = f"line-recipient-upsert:{recipient_type}:{recipient_id}"
    key = frappe.cache.make_key(raw)
    return frappe.cache.lock(key, timeout=30, blocking_timeout=10)


def _channel_lock(channel: str, recipient_type: str, recipient_id: str):
    raw = f"line-recipient-channel-upsert:{channel}:{recipient_type}:{recipient_id}"
    key = frappe.cache.make_key(raw)
    return frappe.cache.lock(key, timeout=30, blocking_timeout=10)


def _upsert_person(channel: str, recipient_type: str, recipient_id: str, event_type: str, now):
    """Create-or-refresh the person-level LINE Recipient.

    Naming is deterministic (`field:recipient_id`), so lookup is a plain
    existence check -- no legacy-format reconciliation needed here, unlike the
    per-channel relationship below. Never touches allow_mark_attendance /
    allow_delivery_confirm; those stay admin-controlled.
    """
    with _identity_lock(recipient_type, recipient_id):
        if frappe.db.exists("LINE Recipient", recipient_id):
            person = frappe.get_doc("LINE Recipient", recipient_id)
        else:
            person = frappe.new_doc("LINE Recipient")
            person.recipient_type = recipient_type
            person.recipient_id = recipient_id
            person.enabled = 1

        if _profile_due(person, event_type):
            try:
                profile = LineClient(channel).get_profile(recipient_id)
                person.display_name = profile.get("displayName") or person.display_name
                person.picture_url = profile.get("pictureUrl") or person.picture_url
                person.status_message = profile.get("statusMessage") or person.status_message
                person.last_profile_sync_at = now
                person.profile_sync_error = None
            except Exception as exc:
                person.profile_sync_error = str(exc)[:2000]

        if person.is_new():
            person.insert(ignore_permissions=True)
        else:
            person.save(ignore_permissions=True)

        return person


def _upsert_channel_relationship(
    channel: str, person_name: str, recipient_type: str, recipient_id: str, event_type: str, now
):
    """Create-or-refresh the per-channel follow/engagement relationship row.

    Locked separately from the identity upsert above (never nested -- the
    identity lock is always released before this one is acquired), keyed by
    channel so sibling channels for the same person serialize independently.
    """
    with _channel_lock(channel, recipient_type, recipient_id):
        existing_name = frappe.db.get_value(
            "LINE Recipient Channel",
            {"line_recipient": person_name, "line_channel": channel},
            "name",
        )
        rel = (
            frappe.get_doc("LINE Recipient Channel", existing_name)
            if existing_name
            else frappe.new_doc("LINE Recipient Channel")
        )
        if rel.is_new():
            rel.line_recipient = person_name
            rel.line_channel = channel
            rel.first_seen_at = now
            rel.following_status = "Unknown"
            rel.enabled = 1

        rel.last_seen_at = now
        rel.last_event_type = event_type

        if event_type == "follow":
            rel.following_status = "Following"
            rel.enabled = 1
        elif event_type == "unfollow":
            rel.following_status = "Unfollowed"

        if rel.is_new():
            rel.insert(ignore_permissions=True)
        else:
            rel.save(ignore_permissions=True)

        return rel


def upsert_from_event(channel: str, event: dict):
    recipient_type, recipient_id = _identity(event.get("source") or {})
    if not recipient_type or not recipient_id:
        return None

    recipient_id = str(recipient_id).strip()
    if not recipient_id:
        return None

    event_type = event.get("type") or "unknown"
    now = now_datetime()

    person = _upsert_person(channel, recipient_type, recipient_id, event_type, now)
    return _upsert_channel_relationship(channel, person.name, recipient_type, recipient_id, event_type, now)
