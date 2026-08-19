from __future__ import annotations

import json

import frappe

from .apply import CARD_SPECS, DOCTYPE, RETIRED_LABELS, WORKSPACE


@frappe.whitelist()
def check():
    ws = frappe.get_doc("Workspace", WORKSPACE) if frappe.db.exists("Workspace", WORKSPACE) else None
    channels = (
        frappe.get_all(DOCTYPE, pluck="name", order_by="name asc", limit_page_length=0)
        if frappe.db.exists("DocType", DOCTYPE)
        else []
    )

    expected = [f"LINE - {channel} - {label}" for channel in channels for label, _, _ in CARD_SPECS]
    retired = [f"LINE - {channel} - {label}" for channel in channels for label in RETIRED_LABELS]

    existing = set(frappe.get_all("Number Card", filters={"name": ["in", expected]}, pluck="name")) if expected else set()
    linked = {row.number_card_name for row in ws.number_cards if row.number_card_name} if ws else set()
    lingering_retired = set(frappe.get_all("Number Card", filters={"name": ["in", retired]}, pluck="name")) if retired else set()

    try:
        content = json.loads(ws.content or "[]") if ws else []
    except Exception:
        content = []
    content_card_names = {
        (block.get("data") or {}).get("number_card_name")
        for block in content
        if block.get("type") == "number_card"
    }

    result = {
        "workspace_exists": bool(ws),
        "channels": channels,
        "expected_cards": expected,
        "missing_number_cards": sorted(set(expected) - existing),
        "missing_workspace_links": sorted(set(expected) - linked),
        "missing_content_blocks": sorted(set(expected) - content_card_names),
        "lingering_retired_cards": sorted(lingering_retired),
        "ready": bool(ws)
        and set(expected).issubset(existing)
        and set(expected).issubset(linked)
        and set(expected).issubset(content_card_names)
        and not lingering_retired,
    }
    print(json.dumps(result, ensure_ascii=False))
    return result
