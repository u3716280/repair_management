from __future__ import annotations

import hashlib

import frappe
from frappe.utils import cint, now_datetime, time_diff_in_hours

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


def _recipient_candidates(
    channel: str,
    recipient_type: str,
    recipient_id: str,
) -> list[dict]:
    """Return existing records for the same LINE business identity.

    Older versions used naming-series records (LINE-RECIP-xxxxx), while the
    current version uses deterministic LINE-REC-<hash> names.  We therefore
    search by business identity instead of document name.
    """
    fields = ["name", "enabled", "creation"]

    rows = frappe.get_all(
        "LINE Recipient",
        filters={
            "line_channel": channel,
            "recipient_type": recipient_type,
            "recipient_id": recipient_id,
        },
        fields=fields,
        order_by="creation asc, name asc",
        limit_page_length=0,
    )

    # Compatibility with legacy User records where line_user_id was populated
    # correctly but recipient_id may have differed during an older migration.
    if recipient_type == "User":
        legacy_rows = frappe.get_all(
            "LINE Recipient",
            filters={
                "line_channel": channel,
                "recipient_type": "User",
                "line_user_id": recipient_id,
            },
            fields=fields,
            order_by="creation asc, name asc",
            limit_page_length=0,
        )

        seen = {row.name for row in rows}
        rows.extend(row for row in legacy_rows if row.name not in seen)

    return rows


def _existing_recipient(
    channel: str,
    recipient_type: str,
    recipient_id: str,
):
    rows = _recipient_candidates(channel, recipient_type, recipient_id)
    if not rows:
        return None

    expected_name = recipient_name(channel, recipient_type, recipient_id)

    # Prefer the deterministic current-format record when it already exists.
    for row in rows:
        if row.name == expected_name:
            chosen = row
            break
    else:
        # Otherwise prefer an enabled legacy record.  If more than one exists,
        # keep the oldest stable record and log the data-quality issue.
        enabled_rows = [row for row in rows if cint(row.enabled)]
        chosen = (enabled_rows or rows)[0]

    if len(rows) > 1:
        frappe.log_error(
            title="Duplicate LINE Recipient identity",
            message=frappe.as_json(
                {
                    "line_channel": channel,
                    "recipient_type": recipient_type,
                    "recipient_id": recipient_id,
                    "chosen": chosen.name,
                    "duplicates": [row.name for row in rows],
                }
            ),
        )

    return frappe.get_doc("LINE Recipient", chosen.name)


def _recipient_lock(
    channel: str,
    recipient_type: str,
    recipient_id: str,
):
    raw = f"line-recipient-upsert:{channel}:{recipient_type}:{recipient_id}"
    key = frappe.cache.make_key(raw)
    return frappe.cache.lock(
        key,
        timeout=30,
        blocking_timeout=10,
    )


def upsert_from_event(channel: str, event: dict):
    recipient_type, recipient_id = _identity(event.get("source") or {})
    if not recipient_type or not recipient_id:
        return None

    recipient_id = str(recipient_id).strip()
    if not recipient_id:
        return None

    # Serialize all webhook workers for the same LINE identity.  This prevents
    # two simultaneous events from both deciding that a recipient is missing.
    with _recipient_lock(channel, recipient_type, recipient_id):
        doc = _existing_recipient(
            channel,
            recipient_type,
            recipient_id,
        )

        now = now_datetime()

        if doc is None:
            doc = frappe.new_doc("LINE Recipient")
            doc.line_channel = channel
            doc.recipient_type = recipient_type
            doc.recipient_id = recipient_id
            doc.first_seen_at = now
            doc.following_status = "Unknown"
            doc.enabled = 1
        else:
            # Normalize legacy records to the current business identity without
            # renaming the document, so existing links remain valid.
            doc.line_channel = channel
            doc.recipient_type = recipient_type
            doc.recipient_id = recipient_id

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

        if doc.is_new():
            doc.insert(ignore_permissions=True)
        else:
            doc.save(ignore_permissions=True)

        return doc
