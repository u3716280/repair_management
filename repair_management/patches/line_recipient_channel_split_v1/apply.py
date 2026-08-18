from __future__ import annotations

import json
from collections import defaultdict

import frappe
from frappe.utils import cint

from .snapshot import latest_snapshot_path


def _load_snapshot(snapshot_path: str | None) -> dict:
    path = snapshot_path or latest_snapshot_path()
    if not path:
        frappe.throw(
            "No line_recipient_channel_split snapshot found. Run "
            "repair_management.patches.line_recipient_channel_split_v1.snapshot.capture() first."
        )
    with open(path) as f:
        return json.load(f)


def _group_key(row: dict) -> str:
    return (row.get("recipient_id") or row.get("line_user_id") or "").strip()


def apply(snapshot_path: str = None) -> dict:
    """Merge per-channel LINE Recipient rows into one person + N LINE Recipient
    Channel rows, then repoint every known foreign key.

    Must run AFTER the trimmed LINE Recipient doctype + new LINE Recipient
    Channel doctype have been migrated (`bench migrate`) -- it reads the
    pre-schema-change data from the snapshot file, not the live table.
    Idempotent: safe to re-run, skips identities/relationships that already
    exist and only repoints links that still point at an old name.
    """
    data = _load_snapshot(snapshot_path)
    recipients = data["recipients"]
    assignments = data["assignments"]
    delivery_confirmations = data["delivery_confirmations"]

    has_pod_field = frappe.get_meta("LINE Recipient").has_field("allow_delivery_confirm")

    groups: dict[str, list[dict]] = defaultdict(list)
    for row in recipients:
        key = _group_key(row)
        if key:
            groups[key].append(row)

    old_to_channel_row: dict[str, str] = {}
    old_to_person: dict[str, str] = {}

    created_persons = []
    skipped_persons_already_migrated = []
    created_channels = []

    for recipient_id, rows in groups.items():
        if frappe.db.exists("LINE Recipient", recipient_id):
            skipped_persons_already_migrated.append(recipient_id)
        else:
            allow_attendance = any(cint(r.get("allow_mark_attendance")) for r in rows)
            allow_pod = any(cint(r.get("allow_delivery_confirm")) for r in rows)
            enabled = any(cint(r.get("enabled")) for r in rows)
            newest = max(rows, key=lambda r: (r.get("last_profile_sync_at") or r.get("modified") or ""))

            person = frappe.new_doc("LINE Recipient")
            person.recipient_type = rows[0]["recipient_type"]
            person.recipient_id = recipient_id
            person.display_name = newest.get("display_name")
            person.picture_url = newest.get("picture_url")
            person.status_message = newest.get("status_message")
            person.last_profile_sync_at = newest.get("last_profile_sync_at")
            person.profile_sync_error = newest.get("profile_sync_error")
            person.enabled = 1 if enabled else 0
            person.allow_mark_attendance = 1 if allow_attendance else 0
            if has_pod_field:
                person.allow_delivery_confirm = 1 if allow_pod else 0
            person.flags.ignore_permissions = True
            person.insert()
            created_persons.append(person.name)

        # A single (person, channel) pair can itself have more than one old
        # row -- e.g. a leftover legacy-naming-series duplicate alongside the
        # current hash-named one for the same channel. Sub-group by channel
        # and merge those together too (OR enabled, widen the seen-at range,
        # take the rest from whichever row was modified most recently) rather
        # than arbitrarily keeping whichever happens to sort first.
        channel_groups: dict[str, list[dict]] = defaultdict(list)
        for row in rows:
            old_to_person[row["name"]] = recipient_id
            channel_groups[row["line_channel"]].append(row)

        for line_channel, channel_rows in channel_groups.items():
            existing_channel_name = frappe.db.get_value(
                "LINE Recipient Channel",
                {"line_recipient": recipient_id, "line_channel": line_channel},
                "name",
            )
            if existing_channel_name:
                for row in channel_rows:
                    old_to_channel_row[row["name"]] = existing_channel_name
                continue

            newest_row = max(channel_rows, key=lambda r: r.get("modified") or "")
            channel_enabled = any(cint(r.get("enabled")) for r in channel_rows)
            first_seen_values = [r.get("first_seen_at") for r in channel_rows if r.get("first_seen_at")]
            last_seen_values = [r.get("last_seen_at") for r in channel_rows if r.get("last_seen_at")]

            rel = frappe.new_doc("LINE Recipient Channel")
            rel.line_recipient = recipient_id
            rel.line_channel = line_channel
            rel.following_status = newest_row.get("following_status") or "Unknown"
            rel.enabled = 1 if channel_enabled else 0
            rel.first_seen_at = min(first_seen_values) if first_seen_values else None
            rel.last_seen_at = max(last_seen_values) if last_seen_values else None
            rel.last_event_type = newest_row.get("last_event_type")
            rel.flags.ignore_permissions = True
            rel.insert()
            created_channels.append(rel.name)
            for row in channel_rows:
                old_to_channel_row[row["name"]] = rel.name

    repointed_assignments = []
    for a in assignments:
        new_recipient = old_to_channel_row.get(a.get("recipient"))
        if not new_recipient or not frappe.db.exists("LINE Rich Menu Recipient Assignment", a["name"]):
            continue
        doc = frappe.get_doc("LINE Rich Menu Recipient Assignment", a["name"])
        if doc.recipient == new_recipient:
            continue
        doc.recipient = new_recipient
        doc.flags.ignore_permissions = True
        doc.save()
        repointed_assignments.append(a["name"])

    repointed_delivery_confirmations = []
    for d in delivery_confirmations:
        new_recipient = old_to_person.get(d.get("line_recipient"))
        if not new_recipient or not frappe.db.exists("Delivery Confirmation", d["name"]):
            continue
        doc = frappe.get_doc("Delivery Confirmation", d["name"])
        if doc.line_recipient == new_recipient:
            continue
        doc.line_recipient = new_recipient
        doc.flags.ignore_permissions = True
        doc.save()
        repointed_delivery_confirmations.append(d["name"])

    deleted_old_recipients = []
    for row in recipients:
        old_name = row["name"]
        if old_name == old_to_person.get(old_name):
            continue  # already had the canonical name -- nothing to delete
        if frappe.db.exists("LINE Recipient", old_name):
            frappe.delete_doc("LINE Recipient", old_name, force=True, ignore_permissions=True)
            deleted_old_recipients.append(old_name)

    frappe.db.commit()

    return {
        "status": "applied",
        "distinct_identities": len(groups),
        "created_persons": created_persons,
        "skipped_persons_already_migrated": skipped_persons_already_migrated,
        "created_channels": created_channels,
        "repointed_assignments": repointed_assignments,
        "repointed_delivery_confirmations": repointed_delivery_confirmations,
        "deleted_old_recipients": deleted_old_recipients,
    }
