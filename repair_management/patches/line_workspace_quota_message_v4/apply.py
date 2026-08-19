from __future__ import annotations

import json
import re

import frappe

WORKSPACE = "LINE"
DOCTYPE = "LINE Channel"
METHOD_BASE = "repair_management.integrations.line.services.quota_dashboard"

CARD_SPECS = (("Message Quota", "quota_usage_display", "#2490EF"),)

# v4 only rearranges layout (one row instead of a header+card stack per
# channel) -- no cards are retired here, unlike v2/v3.
ROW_COL = 4  # 3 channels x col 4 = one full 12-wide row; wraps in groups of 3 beyond that.


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def _save(doc):
    doc.flags.ignore_permissions = True
    doc.save(ignore_permissions=True)
    return doc


def _upsert_card(channel: str, label: str, method: str, color: str):
    name = f"LINE - {channel} - {label}"
    existing = frappe.db.exists("Number Card", name)
    doc = frappe.get_doc("Number Card", existing) if existing else frappe.new_doc("Number Card")

    doc.name = name
    doc.label = name
    doc.type = "Custom"
    doc.document_type = DOCTYPE
    doc.method = f"{METHOD_BASE}.{method}"
    doc.is_public = 1
    doc.show_percentage_stats = 0
    if doc.meta.has_field("show_full_number"):
        doc.show_full_number = 1
    doc.color = color
    doc.filters_json = json.dumps([[DOCTYPE, "name", "=", channel]], ensure_ascii=False)
    _save(doc)
    return doc.name


def _quota_cards():
    if not frappe.db.exists("DocType", DOCTYPE):
        frappe.throw("Required DocType not found: LINE Channel")

    channels = frappe.get_all(DOCTYPE, pluck="name", order_by="name asc", limit_page_length=0)
    cards = []
    for channel in channels:
        for label, method, color in CARD_SPECS:
            cards.append(_upsert_card(channel, label, method, color))
    return channels, cards


def _quota_content(cards):
    # One shared header, then every channel's card back-to-back at a fixed
    # col width so they wrap into full rows instead of each getting its own
    # row (which is what a per-channel header block used to force).
    blocks = [
        {
            "id": "line-channel-quota-header",
            "type": "header",
            "data": {
                "text": '<span class="h4"><b>LINE Channel — Message Quota</b></span>',
                "col": 12,
            },
        }
    ]
    for card_name in cards:
        blocks.append(
            {
                "id": f"line-quota-{_slug(card_name)}",
                "type": "number_card",
                "data": {"number_card_name": card_name, "col": ROW_COL},
            }
        )
    return blocks


def _update_workspace(cards):
    if not frappe.db.exists("Workspace", WORKSPACE):
        frappe.throw("LINE Workspace not found. Install LINE Workspace first.")

    ws = frappe.get_doc("Workspace", WORKSPACE)

    existing_names = {row.number_card_name for row in ws.number_cards if row.number_card_name}
    for card in cards:
        if card not in existing_names:
            row = ws.append("number_cards", {})
            row.number_card_name = card

    try:
        content = json.loads(ws.content or "[]")
        if not isinstance(content, list):
            content = []
    except Exception:
        content = []

    content = [
        block
        for block in content
        if not (
            str(block.get("id") or "").startswith("line-quota-")
            or block.get("id") == "line-channel-quota-header"
        )
    ]

    quota_blocks = _quota_content(cards)

    insert_at = 1 if content else 0
    content[insert_at:insert_at] = quota_blocks
    ws.content = json.dumps(content, ensure_ascii=False)
    _save(ws)
    return ws


def apply():
    channels, cards = _quota_cards()
    ws = _update_workspace(cards)
    frappe.db.commit()

    result = {
        "status": "installed",
        "workspace": ws.name,
        "route": "/app/line",
        "channels": channels,
        "quota_cards": cards,
        "note": "Message Quota cards for every channel now sit in one row instead of one per line.",
    }
    print(json.dumps(result, ensure_ascii=False))
    return result
