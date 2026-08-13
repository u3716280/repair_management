from __future__ import annotations

import html
import json
import re

import frappe

WORKSPACE = "LINE"
DOCTYPE = "LINE Channel"
METHOD_BASE = "repair_management.integrations.line.services.quota_dashboard"

CARD_SPECS = (
    ("Monthly Quota", "quota_limit", "#2490EF"),
    ("Used This Month", "quota_used", "#F79009"),
    ("Remaining", "quota_remaining", "#12B76A"),
    ("Usage %", "quota_usage_percent", "#7F56D9"),
)


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


def _quota_content(channels, cards):
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

    card_iter = iter(cards)
    for channel in channels:
        if len(channels) > 1:
            blocks.append(
                {
                    "id": f"line-quota-channel-{_slug(channel)}",
                    "type": "header",
                    "data": {
                        "text": f'<span class="h5"><b>{html.escape(channel)}</b></span>',
                        "col": 12,
                    },
                }
            )
        for _ in CARD_SPECS:
            card_name = next(card_iter)
            blocks.append(
                {
                    "id": f"line-quota-{_slug(card_name)}",
                    "type": "number_card",
                    "data": {"number_card_name": card_name, "col": 3},
                }
            )
    return blocks


def _update_workspace(channels, cards):
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

    quota_card_names = set(cards)
    content = [
        block
        for block in content
        if not (
            str(block.get("id") or "").startswith("line-quota-")
            or block.get("id") == "line-channel-quota-header"
            or (
                block.get("type") == "number_card"
                and (block.get("data") or {}).get("number_card_name") in quota_card_names
            )
        )
    ]

    quota_blocks = _quota_content(channels, cards)

    # Place quota immediately after LINE Operations header; leave the rest of the existing
    # Workspace (icon, shortcuts, charts, links, layout) untouched.
    insert_at = 1 if content else 0
    content[insert_at:insert_at] = quota_blocks
    ws.content = json.dumps(content, ensure_ascii=False)
    _save(ws)
    return ws


def apply():
    channels, cards = _quota_cards()
    ws = _update_workspace(channels, cards)
    frappe.db.commit()

    result = {
        "status": "installed",
        "workspace": ws.name,
        "route": "/app/line",
        "channels": channels,
        "quota_cards": cards,
        "methods": [f"{METHOD_BASE}.{spec[1]}" for spec in CARD_SPECS],
        "note": "Quota values are fetched live from LINE Messaging API when Number Cards load.",
    }
    print(json.dumps(result, ensure_ascii=False))
    return result


@frappe.whitelist()
def check():
    ws = frappe.get_doc("Workspace", WORKSPACE) if frappe.db.exists("Workspace", WORKSPACE) else None
    channels = frappe.get_all(DOCTYPE, pluck="name", order_by="name asc", limit_page_length=0) if frappe.db.exists("DocType", DOCTYPE) else []

    expected = [f"LINE - {channel} - {label}" for channel in channels for label, _, _ in CARD_SPECS]
    existing = set(frappe.get_all("Number Card", filters={"name": ["in", expected]}, pluck="name")) if expected else set()
    linked = {row.number_card_name for row in ws.number_cards if row.number_card_name} if ws else set()

    result = {
        "workspace_exists": bool(ws),
        "channels": channels,
        "expected_cards": expected,
        "missing_number_cards": sorted(set(expected) - existing),
        "missing_workspace_cards": sorted(set(expected) - linked),
        "ready": bool(ws) and set(expected).issubset(existing) and set(expected).issubset(linked),
    }
    print(json.dumps(result, ensure_ascii=False))
    return result
