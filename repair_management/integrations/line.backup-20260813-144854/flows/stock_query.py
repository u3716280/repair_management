from __future__ import annotations

import math
from urllib.parse import urlencode

import frappe
from frappe.utils import now_datetime

from repair_management.integrations.line.api.client import LineClient
from repair_management.integrations.line.flows.base import create_session, context, set_context
from repair_management.integrations.line.services import stock


SELECTING_TYPE = "Selecting Search Type"
WAITING_KEYWORD = "Waiting Search Keyword"
SELECTING_GROUP = "Selecting Item Group"
SHOWING_RESULTS = "Showing Results"

PROMPTS = {
    "item_code": "กรุณาพิมพ์ข้อมูลที่ต้องการค้นหา",
    "item_name": "กรุณาพิมพ์ข้อมูลที่ต้องการค้นหา",
    "item_group": "กรุณาพิมพ์ข้อมูลที่ต้องการค้นหา",
    "any": "กรุณาพิมพ์ข้อมูลที่ต้องการค้นหา",
}


def _config_from_flow(flow):
    return frappe.get_doc(flow.configuration_doctype, flow.configuration_name)


def _config_from_session(session):
    flow = frappe.get_doc("LINE Business Flow", session.business_flow)
    return _config_from_flow(flow)


def _page_size(config):
    for fieldname in ("results_per_page", "maximum_results", "max_results"):
        value = getattr(config, fieldname, None)
        try:
            value = int(value)
        except (TypeError, ValueError):
            continue
        if value > 0:
            return min(value, 10)
    return 10


def _postback(action, **params):
    return urlencode({"action": action, **params})


def _load_session(channel, user_id, session_name):
    if not session_name or not frappe.db.exists("LINE Flow Session", session_name):
        return None
    session = frappe.get_doc("LINE Flow Session", session_name)
    if session.line_channel != channel or session.line_user_id != user_id:
        return None
    if session.status != "Active":
        return None
    if session.expires_at and session.expires_at <= now_datetime():
        session.db_set({"status": "Expired", "current_state": "Expired"})
        return None
    return session


def _text_row(label, value):
    return {
        "type": "box",
        "layout": "baseline",
        "spacing": "sm",
        "contents": [
            {"type": "text", "text": str(label), "size": "xs", "color": "#8C8C8C", "flex": 3},
            {"type": "text", "text": str(value), "size": "xs", "color": "#333333", "wrap": True, "flex": 5},
        ],
    }


def _money(value):
    if value is None:
        return "-"
    try:
        return f"{float(value):,.2f}"
    except (TypeError, ValueError):
        return str(value)


def _qty(value):
    try:
        number = float(value or 0)
    except (TypeError, ValueError):
        return str(value or 0)
    return f"{number:,.2f}".rstrip("0").rstrip(".")


def _search_type_message(session):
    items = []
    for label, search_type in (
        ("Item Code", "item_code"),
        ("Item Name", "item_name"),
        ("Item Group", "item_group"),
        ("ไม่ระบุ", "any"),
    ):
        items.append({
            "type": "action",
            "action": {
                "type": "postback",
                "label": label,
                "displayText": label,
                "data": _postback("stock_search_type", type=search_type, session=session.name),
            },
        })
    return {
        "type": "text",
        "text": "ต้องการค้นหา STOCK ด้วยข้อมูลใด?",
        "quickReply": {"items": items},
    }


def _item_bubble(item, session_name, index):
    detail = stock.detail(_config_from_session(frappe.get_doc("LINE Flow Session", session_name)), item.name)
    total = detail.get("total_actual_qty", 0) if detail else 0
    purchase_rate = detail.get("purchase_rate") if detail else None
    selling_rate = detail.get("selling_rate") if detail else None

    rows = [
        _text_row("Item Group", item.item_group or "-"),
        _text_row("UOM", item.stock_uom or "-"),
        _text_row("Actual Stock", _qty(total)),
    ]
    if purchase_rate is not None:
        rows.append(_text_row("ราคาซื้อ", _money(purchase_rate)))
    if selling_rate is not None:
        rows.append(_text_row("ราคาขาย", _money(selling_rate)))

    return {
        "type": "bubble",
        "size": "kilo",
        "body": {
            "type": "box",
            "layout": "vertical",
            "spacing": "md",
            "contents": [
                {"type": "text", "text": item.name, "weight": "bold", "size": "md", "wrap": True},
                {"type": "text", "text": item.item_name or item.name, "size": "sm", "color": "#555555", "wrap": True},
                {"type": "separator", "margin": "md"},
                {"type": "box", "layout": "vertical", "spacing": "sm", "contents": rows},
            ],
        },
        "footer": {
            "type": "box",
            "layout": "vertical",
            "contents": [{
                "type": "button",
                "style": "primary",
                "action": {
                    "type": "postback",
                    "label": "ดูรายละเอียด",
                    "displayText": f"ดูรายละเอียด {item.name}",
                    "data": _postback("stock_detail", session=session_name, index=index),
                },
            }],
        },
    }


def _navigation_bubble(session_name, page, total_pages, label="ผลการค้นหา"):
    buttons = []
    if page > 1:
        buttons.append({
            "type": "button",
            "style": "secondary",
            "action": {
                "type": "postback",
                "label": "ก่อนหน้า",
                "data": _postback("stock_page", session=session_name, page=page - 1),
            },
        })
    if page < total_pages:
        buttons.append({
            "type": "button",
            "style": "primary",
            "action": {
                "type": "postback",
                "label": "ถัดไป",
                "data": _postback("stock_page", session=session_name, page=page + 1),
            },
        })
    return {
        "type": "bubble",
        "size": "kilo",
        "body": {
            "type": "box",
            "layout": "vertical",
            "contents": [
                {"type": "text", "text": label, "weight": "bold", "align": "center"},
                {"type": "text", "text": f"หน้า {page}/{total_pages}", "size": "sm", "color": "#777777", "align": "center", "margin": "md"},
            ],
        },
        "footer": {"type": "box", "layout": "vertical", "spacing": "sm", "contents": buttons},
    }


def _item_results_message(session, page=1):
    cfg = _config_from_session(session)
    ctx = context(session)
    names = list(ctx.get("item_candidates") or [])
    size = _page_size(cfg)
    total_pages = max(1, math.ceil(len(names) / size))
    page = min(max(int(page or 1), 1), total_pages)
    start = (page - 1) * size
    page_names = names[start:start + size]

    rows = frappe.get_all(
        "Item",
        filters={"name": ["in", page_names], "disabled": 0},
        fields=["name", "item_name", "item_group", "stock_uom"],
        order_by="name asc",
        limit_page_length=0,
    )
    by_name = {row.name: row for row in rows}
    bubbles = []
    for offset, name in enumerate(page_names):
        item = by_name.get(name)
        if item:
            bubbles.append(_item_bubble(item, session.name, start + offset))
    if total_pages > 1:
        bubbles.append(_navigation_bubble(session.name, page, total_pages))

    return {
        "type": "flex",
        "altText": "ผลการค้นหา STOCK",
        "contents": {"type": "carousel", "contents": bubbles},
    }


def _group_bubble(group, session_name, index):
    has_children = bool(group.is_group)
    details = [
        _text_row("Parent", group.parent_item_group or "-"),
        _text_row("Sub Group", "มี" if has_children else "ไม่มี"),
    ]
    return {
        "type": "bubble",
        "size": "kilo",
        "body": {
            "type": "box",
            "layout": "vertical",
            "spacing": "md",
            "contents": [
                {"type": "text", "text": group.name, "weight": "bold", "size": "md", "wrap": True},
                {"type": "separator", "margin": "md"},
                {"type": "box", "layout": "vertical", "spacing": "sm", "contents": details},
            ],
        },
        "footer": {
            "type": "box",
            "layout": "vertical",
            "contents": [{
                "type": "button",
                "style": "primary",
                "action": {
                    "type": "postback",
                    "label": "เลือก Item Group",
                    "displayText": f"เลือก {group.name}",
                    # Reuse stock_detail so router.py does not need modification.
                    "data": _postback("stock_detail", session=session_name, index=index),
                },
            }],
        },
    }


def _group_results_message(session, page=1):
    cfg = _config_from_session(session)
    ctx = context(session)
    names = list(ctx.get("group_candidates") or [])
    size = _page_size(cfg)
    total_pages = max(1, math.ceil(len(names) / size))
    page = min(max(int(page or 1), 1), total_pages)
    start = (page - 1) * size
    page_names = names[start:start + size]

    rows = frappe.get_all(
        "Item Group",
        filters={"name": ["in", page_names]},
        fields=["name", "parent_item_group", "is_group", "lft", "rgt"],
        limit_page_length=0,
    )
    by_name = {row.name: row for row in rows}
    bubbles = []
    for offset, name in enumerate(page_names):
        group = by_name.get(name)
        if group:
            bubbles.append(_group_bubble(group, session.name, start + offset))
    if total_pages > 1:
        bubbles.append(_navigation_bubble(session.name, page, total_pages, label="Item Group"))

    return {
        "type": "flex",
        "altText": "เลือก Item Group",
        "contents": {"type": "carousel", "contents": bubbles},
    }


def _detail_message(detail):
    rows = [
        _text_row("Item Group", detail.get("item_group") or "-"),
        _text_row("UOM", detail.get("stock_uom") or "-"),
        _text_row("Actual Stock", _qty(detail.get("total_actual_qty"))),
    ]
    if detail.get("purchase_rate") is not None:
        rows.append(_text_row("ราคาซื้อ", _money(detail.get("purchase_rate"))))
    if detail.get("selling_rate") is not None:
        rows.append(_text_row("ราคาขาย", _money(detail.get("selling_rate"))))

    warehouse_rows = []
    for row in detail.get("warehouses") or []:
        warehouse_rows.append(_text_row(row.get("warehouse") or "Warehouse", _qty(row.get("actual_qty"))))
    if not warehouse_rows:
        warehouse_rows.append(_text_row("Warehouse", "ไม่มี Stock"))

    return {
        "type": "flex",
        "altText": f"รายละเอียด STOCK {detail.get('item_code')}",
        "contents": {
            "type": "bubble",
            "size": "mega",
            "body": {
                "type": "box",
                "layout": "vertical",
                "spacing": "md",
                "contents": [
                    {"type": "text", "text": detail.get("item_code") or "-", "weight": "bold", "size": "lg", "wrap": True},
                    {"type": "text", "text": detail.get("item_name") or detail.get("item_code") or "-", "size": "sm", "color": "#555555", "wrap": True},
                    {"type": "separator", "margin": "md"},
                    {"type": "box", "layout": "vertical", "spacing": "sm", "contents": rows},
                    {"type": "separator", "margin": "md"},
                    {"type": "text", "text": "Actual Qty by Warehouse", "weight": "bold", "size": "sm"},
                    {"type": "box", "layout": "vertical", "spacing": "sm", "contents": warehouse_rows},
                ],
            },
        },
    }


def _store_items(session, rows, **extra_context):
    ctx = context(session)
    ctx.update(extra_context)
    ctx["item_candidates"] = sorted({row.name for row in rows if row.name})
    ctx["page"] = 1
    set_context(session, ctx, SHOWING_RESULTS)


def _select_group(session, group_name):
    cfg = _config_from_session(session)
    groups = stock.expand_item_group(group_name)
    rows = stock.items_for_groups(cfg, groups)
    ctx = context(session)
    ctx["selected_item_group"] = group_name
    ctx["expanded_item_groups"] = groups
    ctx["item_candidates"] = [row.name for row in rows]
    ctx["page"] = 1
    set_context(session, ctx, SHOWING_RESULTS)
    return rows


def start(channel, user_id, reply_token, flow, **kwargs):
    session = create_session(
        channel,
        user_id,
        flow,
        SELECTING_TYPE,
        {"type": "any", "page": 1},
    )
    LineClient(channel).reply(reply_token, [_search_type_message(session)])


def select_type(channel, user_id, reply_token, params, **kwargs):
    session = _load_session(channel, user_id, params.get("session"))
    if not session:
        LineClient(channel).reply(reply_token, [{"type": "text", "text": "รายการค้นหาหมดอายุแล้ว กรุณาเริ่มใหม่"}])
        return

    search_type = params.get("type") if params.get("type") in PROMPTS else "any"
    ctx = context(session)
    ctx["type"] = search_type
    ctx.pop("group_candidates", None)
    ctx.pop("selected_item_group", None)
    ctx.pop("expanded_item_groups", None)
    ctx.pop("item_candidates", None)
    set_context(session, ctx, WAITING_KEYWORD)
    LineClient(channel).reply(reply_token, [{"type": "text", "text": PROMPTS[search_type]}])


def handle_text(channel, user_id, reply_token, session, text, **kwargs):
    if session.current_state == SELECTING_TYPE:
        LineClient(channel).reply(reply_token, [_search_type_message(session)])
        return True

    if session.current_state != WAITING_KEYWORD:
        return False

    keyword = (text or "").strip()
    if not keyword:
        LineClient(channel).reply(reply_token, [{"type": "text", "text": "กรุณาพิมพ์ข้อมูลที่ต้องการค้นหา"}])
        return True

    cfg = _config_from_session(session)
    ctx = context(session)
    search_type = ctx.get("type", "any")
    ctx["keyword"] = keyword

    if search_type == "item_group":
        groups = stock.search_item_groups(keyword, limit=100)
        if not groups:
            set_context(session, ctx, WAITING_KEYWORD)
            LineClient(channel).reply(reply_token, [{"type": "text", "text": "ไม่พบ Item Group ที่ใกล้เคียง กรุณาลองคำค้นอื่น"}])
            return True

        ctx["group_candidates"] = [row.name for row in groups]
        ctx["group_page"] = 1
        set_context(session, ctx, SELECTING_GROUP)

        if len(groups) == 1:
            rows = _select_group(session, groups[0].name)
            if not rows:
                LineClient(channel).reply(reply_token, [{"type": "text", "text": f"Item Group {groups[0].name} ไม่มี Item ที่ใช้งานอยู่"}])
                return True
            LineClient(channel).reply(reply_token, [_item_results_message(session, 1)])
            return True

        LineClient(channel).reply(reply_token, [_group_results_message(session, 1)])
        return True

    rows, serial = stock.search(cfg, search_type, keyword)
    if not rows:
        set_context(session, ctx, WAITING_KEYWORD)
        LineClient(channel).reply(reply_token, [{"type": "text", "text": "ไม่พบ Item ที่ตรงกับข้อมูลที่ค้นหา"}])
        return True

    _store_items(session, rows, serial_match=serial)

    # Item Name: one candidate = auto select and show live detail immediately.
    if search_type == "item_name" and len(rows) == 1:
        detail = stock.detail(cfg, rows[0].name)
        if detail:
            LineClient(channel).reply(reply_token, [_detail_message(detail)])
            return True

    LineClient(channel).reply(reply_token, [_item_results_message(session, 1)])
    return True


def show_page(channel, user_id, reply_token, params, **kwargs):
    session = _load_session(channel, user_id, params.get("session"))
    if not session:
        LineClient(channel).reply(reply_token, [{"type": "text", "text": "รายการค้นหาหมดอายุแล้ว กรุณาเริ่มใหม่"}])
        return

    try:
        page = max(int(params.get("page") or 1), 1)
    except (TypeError, ValueError):
        page = 1

    ctx = context(session)
    if session.current_state == SELECTING_GROUP:
        ctx["group_page"] = page
        set_context(session, ctx)
        LineClient(channel).reply(reply_token, [_group_results_message(session, page)])
        return

    if session.current_state == SHOWING_RESULTS:
        ctx["page"] = page
        set_context(session, ctx)
        LineClient(channel).reply(reply_token, [_item_results_message(session, page)])
        return

    LineClient(channel).reply(reply_token, [{"type": "text", "text": "ไม่พบหน้าผลการค้นหาที่เปิดอยู่"}])


def show_detail(channel, user_id, reply_token, params, **kwargs):
    session = _load_session(channel, user_id, params.get("session"))
    if not session:
        LineClient(channel).reply(reply_token, [{"type": "text", "text": "รายการค้นหาหมดอายุแล้ว กรุณาเริ่มใหม่"}])
        return

    try:
        index = int(params.get("index"))
    except (TypeError, ValueError):
        index = -1

    ctx = context(session)

    # Reuse stock_detail action as Item Group selection, so router.py remains unchanged.
    if session.current_state == SELECTING_GROUP:
        candidates = list(ctx.get("group_candidates") or [])
        if index < 0 or index >= len(candidates):
            LineClient(channel).reply(reply_token, [{"type": "text", "text": "ไม่พบ Item Group ที่เลือก"}])
            return

        group_name = candidates[index]
        if not frappe.db.exists("Item Group", group_name):
            fresh = stock.search_item_groups(ctx.get("keyword"), limit=100)
            ctx["group_candidates"] = [row.name for row in fresh]
            ctx["group_page"] = 1
            set_context(session, ctx, SELECTING_GROUP)
            LineClient(channel).reply(reply_token, [{"type": "text", "text": "Item Group มีการเปลี่ยนแปลง กรุณาเลือกใหม่"}, _group_results_message(session, 1)])
            return

        rows = _select_group(session, group_name)
        if not rows:
            LineClient(channel).reply(reply_token, [{"type": "text", "text": f"Item Group {group_name} ไม่มี Item ที่ใช้งานอยู่"}])
            return

        LineClient(channel).reply(reply_token, [_item_results_message(session, 1)])
        return

    if session.current_state != SHOWING_RESULTS:
        LineClient(channel).reply(reply_token, [{"type": "text", "text": "ไม่มีผลการค้นหาที่สามารถดูรายละเอียดได้"}])
        return

    candidates = list(ctx.get("item_candidates") or [])
    if index < 0 or index >= len(candidates):
        LineClient(channel).reply(reply_token, [{"type": "text", "text": "ไม่พบ Item ที่เลือก"}])
        return

    item_code = candidates[index]
    cfg = _config_from_session(session)
    detail = stock.detail(cfg, item_code)
    if not detail:
        LineClient(channel).reply(reply_token, [{"type": "text", "text": "Item นี้ไม่สามารถใช้งานได้แล้ว กรุณาค้นหาใหม่"}])
        return

    LineClient(channel).reply(reply_token, [_detail_message(detail)])
