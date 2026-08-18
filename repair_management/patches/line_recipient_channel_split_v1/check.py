from __future__ import annotations

import json
from collections import defaultdict

import frappe

from .snapshot import latest_snapshot_path

KNOWN_DUPLICATE_IDENTITIES = [
    "Ueb387d8b8b7d0b15be569874e72fceb1",
    "U00ccaab7bbc9beb7f2d98d2797ae4325",
]


def _load_snapshot(snapshot_path: str | None) -> dict:
    path = snapshot_path or latest_snapshot_path()
    if not path:
        frappe.throw("No line_recipient_channel_split snapshot found.")
    with open(path) as f:
        return json.load(f)


def check(snapshot_path: str = None) -> dict:
    data = _load_snapshot(snapshot_path)
    recipients = data["recipients"]
    assignments = data["assignments"]
    delivery_confirmations = data["delivery_confirmations"]

    groups: dict[str, list[dict]] = defaultdict(list)
    channel_pairs: set[tuple[str, str]] = set()
    for row in recipients:
        key = (row.get("recipient_id") or row.get("line_user_id") or "").strip()
        if key:
            groups[key].append(row)
            channel_pairs.add((key, row["line_channel"]))

    missing_persons = [k for k in groups if not frappe.db.exists("LINE Recipient", k)]

    original_names = {row["name"] for row in recipients}
    dangling_old_recipients = [
        name for name in original_names if name not in groups and frappe.db.exists("LINE Recipient", name)
    ]

    bad_assignments = []
    for a in assignments:
        if not frappe.db.exists("LINE Rich Menu Recipient Assignment", a["name"]):
            continue
        current = frappe.db.get_value("LINE Rich Menu Recipient Assignment", a["name"], "recipient")
        if not current or not frappe.db.exists("LINE Recipient Channel", current):
            bad_assignments.append({"name": a["name"], "recipient": current})

    bad_delivery_confirmations = []
    for d in delivery_confirmations:
        if not frappe.db.exists("Delivery Confirmation", d["name"]):
            continue
        current = frappe.db.get_value("Delivery Confirmation", d["name"], "line_recipient")
        if not current or not frappe.db.exists("LINE Recipient", current):
            bad_delivery_confirmations.append({"name": d["name"], "line_recipient": current})

    # Defensive re-check that the blast-radius assumption made during planning
    # still holds: only Delivery Confirmation should still hold a Link to the
    # (now person-level) LINE Recipient.
    other_doc_links = frappe.get_all(
        "DocField",
        filters={"fieldtype": "Link", "options": "LINE Recipient"},
        fields=["parent", "fieldname"],
    )
    expected_link_holders = {"Delivery Confirmation", "LINE Recipient Channel"}
    unexpected_links = [link for link in other_doc_links if link["parent"] not in expected_link_holders]
    unexpected_custom_field_links = frappe.get_all(
        "Custom Field", filters={"fieldtype": "Link", "options": "LINE Recipient"}, fields=["dt", "fieldname"]
    )

    known_duplicate_status = {}
    for uid in KNOWN_DUPLICATE_IDENTITIES:
        known_duplicate_status[uid] = {
            "identity": frappe.db.get_value(
                "LINE Recipient", uid, ["enabled", "allow_mark_attendance"], as_dict=True
            ),
            "channel_count": frappe.db.count("LINE Recipient Channel", {"line_recipient": uid}),
        }

    return {
        "expected_person_count": len(groups),
        "actual_person_count": frappe.db.count("LINE Recipient"),
        "expected_channel_count": len(channel_pairs),
        "actual_channel_count": frappe.db.count("LINE Recipient Channel"),
        "missing_persons": missing_persons,
        "dangling_old_recipients": dangling_old_recipients,
        "bad_assignments": bad_assignments,
        "bad_delivery_confirmations": bad_delivery_confirmations,
        "unexpected_links_to_line_recipient": unexpected_links,
        "unexpected_custom_field_links": unexpected_custom_field_links,
        "known_duplicate_identities": known_duplicate_status,
    }
