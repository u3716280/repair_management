from __future__ import annotations

import json
from collections import defaultdict

import frappe

from .snapshot import latest_snapshot_path


def _load_snapshot(snapshot_path: str | None) -> dict:
    path = snapshot_path or latest_snapshot_path()
    if not path:
        frappe.throw("No line_recipient_channel_split snapshot found to revert from.")
    with open(path) as f:
        return json.load(f)


def revert(snapshot_path: str = None) -> dict:
    """Undo apply()'s DATA merge using the snapshot as ground truth.

    IMPORTANT ordering caveat: this only reverses the data migration. It
    assumes the `LINE Recipient` doctype schema still has the original
    (pre-split) fields available (line_channel, following_status,
    first_seen_at, last_seen_at, last_event_type) to recreate the original
    rows into. If the doctype JSON / `bench migrate` schema change has
    already been reverted via git, run that revert AFTER this one, not
    before -- reverting the schema first removes the columns this function
    needs to restore the original per-channel rows' data into.
    """
    data = _load_snapshot(snapshot_path)
    recipients = data["recipients"]
    assignments = data["assignments"]
    delivery_confirmations = data["delivery_confirmations"]

    for a in assignments:
        if frappe.db.exists("LINE Rich Menu Recipient Assignment", a["name"]):
            frappe.db.set_value(
                "LINE Rich Menu Recipient Assignment",
                a["name"],
                "recipient",
                a["recipient"],
                update_modified=False,
            )

    for d in delivery_confirmations:
        if frappe.db.exists("Delivery Confirmation", d["name"]):
            frappe.db.set_value(
                "Delivery Confirmation",
                d["name"],
                "line_recipient",
                d["line_recipient"],
                update_modified=False,
            )

    deleted_channels = []
    for name in frappe.get_all("LINE Recipient Channel", pluck="name"):
        frappe.delete_doc("LINE Recipient Channel", name, force=True, ignore_permissions=True)
        deleted_channels.append(name)

    groups: dict[str, list[dict]] = defaultdict(list)
    for row in recipients:
        key = (row.get("recipient_id") or row.get("line_user_id") or "").strip()
        if key:
            groups[key].append(row)

    deleted_persons = []
    for key in groups:
        if frappe.db.exists("LINE Recipient", key):
            frappe.delete_doc("LINE Recipient", key, force=True, ignore_permissions=True)
            deleted_persons.append(key)

    recreated = []
    for row in recipients:
        if frappe.db.exists("LINE Recipient", row["name"]):
            continue
        doc = frappe.new_doc("LINE Recipient")
        doc.update(row)
        doc.flags.ignore_permissions = True
        doc.insert(set_name=row["name"])
        recreated.append(row["name"])

    frappe.db.commit()

    return {
        "status": "reverted",
        "deleted_channels": deleted_channels,
        "deleted_persons": deleted_persons,
        "recreated_recipients": recreated,
    }
