from __future__ import annotations

import json

import frappe

from .apply import CARD_SPECS, DOCTYPE, ROW_COL, WORKSPACE


@frappe.whitelist()
def check():
    ws = frappe.get_doc("Workspace", WORKSPACE) if frappe.db.exists("Workspace", WORKSPACE) else None
    channels = (
        frappe.get_all(DOCTYPE, pluck="name", order_by="name asc", limit_page_length=0)
        if frappe.db.exists("DocType", DOCTYPE)
        else []
    )

    expected = [f"LINE - {channel} - {label}" for channel in channels for label, _, _ in CARD_SPECS]

    existing = set(frappe.get_all("Number Card", filters={"name": ["in", expected]}, pluck="name")) if expected else set()
    linked = {row.number_card_name for row in ws.number_cards if row.number_card_name} if ws else set()

    try:
        content = json.loads(ws.content or "[]") if ws else []
    except Exception:
        content = []

    quota_card_blocks = [
        block
        for block in content
        if block.get("type") == "number_card" and str(block.get("id") or "").startswith("line-quota-")
    ]
    content_card_names = {(b.get("data") or {}).get("number_card_name") for b in quota_card_blocks}
    wrong_col = [
        (b.get("data") or {}).get("number_card_name")
        for b in quota_card_blocks
        if (b.get("data") or {}).get("col") != ROW_COL
    ]
    per_channel_headers_remaining = [
        block.get("id")
        for block in content
        if str(block.get("id") or "").startswith("line-quota-channel-")
    ]

    result = {
        "workspace_exists": bool(ws),
        "channels": channels,
        "expected_cards": expected,
        "missing_number_cards": sorted(set(expected) - existing),
        "missing_workspace_links": sorted(set(expected) - linked),
        "missing_content_blocks": sorted(set(expected) - content_card_names),
        "wrong_col_cards": wrong_col,
        "per_channel_headers_remaining": per_channel_headers_remaining,
        "ready": bool(ws)
        and set(expected).issubset(existing)
        and set(expected).issubset(linked)
        and set(expected).issubset(content_card_names)
        and not wrong_col
        and not per_channel_headers_remaining,
    }
    print(json.dumps(result, ensure_ascii=False))
    return result
