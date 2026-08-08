# BEGIN PATCH: stock_query_flex_results_v1_5
from __future__ import annotations

import frappe
from frappe.utils import flt, getdate, nowdate

from repair_management.integrations.line.api.client import LineClient
from repair_management.integrations.line.flows.base import create_session, context, set_context
from repair_management.integrations.line.services import stock

PROMPTS = {
    "item_code": "กรุณาพิมพ์ข้อมูลที่ต้องการค้นหา",
    "item_name": "กรุณาพิมพ์ข้อมูลที่ต้องการค้นหา",
    "item_group": "กรุณาพิมพ์ข้อมูลที่ต้องการค้นหา",
    "any": "กรุณาพิมพ์ข้อมูลที่ต้องการค้นหา",
}


def start(channel, user_id, reply_token, flow, **k):
    session = create_session(channel, user_id, flow, "Selecting Search Type")
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
                "data": f"action=stock_search_type&type={search_type}&session={session.name}",
                "displayText": label,
            },
        })
    LineClient(channel).reply(reply_token, [{
        "type": "text",
        "text": "เลือกประเภทการค้นหา Stock",
        "quickReply": {"items": items},
    }])


def _valid_session(channel, user_id, session_name):
    if not session_name or not frappe.db.exists("LINE Flow Session", session_name):
        return None
    session = frappe.get_doc("LINE Flow Session", session_name)
    if session.line_channel != channel or session.line_user_id != user_id or session.status != "Active":
        return None
    return session


def select_type(channel, user_id, reply_token, params, **k):
    session = _valid_session(channel, user_id, params.get("session"))
    if not session:
        LineClient(channel).reply(reply_token, [{"type": "text", "text": "Session หมดอายุ กรุณาเริ่มค้นหาใหม่"}])
        return
    search_type = params.get("type") if params.get("type") in PROMPTS else "any"
    ctx = context(session)
    ctx["type"] = search_type
    set_context(session, ctx, "Waiting Query")
    LineClient(channel).reply(reply_token, [{"type": "text", "text": PROMPTS[search_type]}])


def _allowed_warehouses(cfg):
    names = []
    for row in cfg.get("allowed_warehouses") or []:
        value = row.get("warehouse") or row.get("warehouse_name") or row.get("allowed_warehouse")
        if value:
            names.append(value)
    return list(dict.fromkeys(names))


def _company_warehouses(cfg):
    if not cfg.company:
        return []
    names = frappe.get_all("Warehouse", filters={"company": cfg.company, "is_group": 0, "disabled": 0}, pluck="name")
    allowed = set(_allowed_warehouses(cfg))
    return [name for name in names if not allowed or name in allowed]


def _stock_rows(cfg, item_code):
    warehouses = set(_company_warehouses(cfg))
    if not warehouses:
        return []
    bins = frappe.get_all("Bin", filters={"item_code": item_code}, fields=["warehouse", "actual_qty", "valuation_rate"])
    rows = []
    for row in bins:
        if row.warehouse not in warehouses:
            continue
        qty = flt(row.actual_qty)
        if not cfg.get("include_zero_stock") and qty == 0:
            continue
        rows.append(frappe._dict(warehouse=row.warehouse, actual_qty=qty, valuation_rate=flt(row.valuation_rate)))
    rows.sort(key=lambda x: (-x.actual_qty, x.warehouse))
    return rows


def _company_currency(cfg):
    return frappe.db.get_value("Company", cfg.company, "default_currency") if cfg.company else ""


def _selling_price(cfg, item):
    if not cfg.selling_price_list:
        return None, ""
    rows = frappe.get_all(
        "Item Price",
        filters={"price_list": cfg.selling_price_list, "item_code": item.name, "selling": 1},
        fields=["price_list_rate", "currency", "uom", "valid_from", "valid_upto", "modified"],
        order_by="valid_from desc, modified desc",
        limit_page_length=30,
    )
    today = getdate(nowdate())
    valid = []
    for row in rows:
        if row.valid_from and getdate(row.valid_from) > today:
            continue
        if row.valid_upto and getdate(row.valid_upto) < today:
            continue
        valid.append(row)
    if not valid:
        return None, ""
    exact = [row for row in valid if not row.uom or row.uom == item.stock_uom]
    selected = (exact or valid)[0]
    return flt(selected.price_list_rate), selected.currency or ""


def _purchase_price(cfg, item, stock_rows):
    price = flt(item.get("last_purchase_rate"))
    if price:
        return price, _company_currency(cfg)
    rates = [flt(row.valuation_rate) for row in stock_rows if flt(row.valuation_rate)]
    return (rates[0] if rates else None), _company_currency(cfg)


def _money(value, currency=""):
    return "-" if value is None else f"{flt(value):,.2f} {currency}".strip()


def _qty(value, uom=""):
    text = f"{flt(value):,.2f}".rstrip("0").rstrip(".")
    return f"{text} {uom}".strip()


def _item_snapshot(cfg, item_code):
    item = frappe.get_doc("Item", item_code)
    stock_rows = _stock_rows(cfg, item_code)
    purchase_price, purchase_currency = _purchase_price(cfg, item, stock_rows)
    selling_price, selling_currency = _selling_price(cfg, item)
    return frappe._dict(
        item=item,
        stock_rows=stock_rows,
        total_qty=sum(flt(row.actual_qty) for row in stock_rows),
        purchase_price=purchase_price,
        purchase_currency=purchase_currency,
        selling_price=selling_price,
        selling_currency=selling_currency,
    )


def _text_row(label, value, bold=False):
    return {
        "type": "box", "layout": "horizontal", "spacing": "sm",
        "contents": [
            {"type": "text", "text": label, "size": "sm", "color": "#777777", "flex": 3},
            {"type": "text", "text": str(value), "size": "sm", "weight": "bold" if bold else "regular", "wrap": True, "flex": 5, "align": "end"},
        ],
    }


def _result_bubble(cfg, session, item_code, index):
    snap = _item_snapshot(cfg, item_code)
    item = snap.item
    body = [
        {"type": "text", "text": item.name, "weight": "bold", "size": "lg", "wrap": True},
        {"type": "text", "text": item.item_name or item.name, "size": "sm", "wrap": True, "margin": "sm", "color": "#555555"},
        {"type": "separator", "margin": "md"},
        _text_row("Item Group", item.item_group or "-"),
        _text_row("UOM", item.stock_uom or "-"),
    ]
    if cfg.get("show_purchase_price"):
        body.append(_text_row("ราคาซื้อ", _money(snap.purchase_price, snap.purchase_currency)))
    if cfg.get("show_selling_price"):
        body.append(_text_row("ราคาขาย", _money(snap.selling_price, snap.selling_currency)))
    body.append(_text_row("Stock รวม", _qty(snap.total_qty, item.stock_uom), bold=True))
    return {
        "type": "bubble",
        "body": {"type": "box", "layout": "vertical", "spacing": "sm", "contents": body},
        "footer": {"type": "box", "layout": "vertical", "contents": [{
            "type": "button", "style": "primary", "height": "sm",
            "action": {"type": "postback", "label": "ดูรายละเอียด", "data": f"action=stock_detail&session={session.name}&index={index}", "displayText": f"ดูรายละเอียด {item.name}"},
        }]},
    }


def _navigation_bubble(session, page, page_count):
    buttons = []
    if page > 1:
        buttons.append({"type": "button", "height": "sm", "action": {"type": "postback", "label": "ก่อนหน้า", "data": f"action=stock_page&session={session.name}&page={page - 1}", "displayText": "ผลค้นหาหน้าก่อน"}})
    if page < page_count:
        buttons.append({"type": "button", "style": "primary", "height": "sm", "action": {"type": "postback", "label": "ถัดไป", "data": f"action=stock_page&session={session.name}&page={page + 1}", "displayText": "ผลค้นหาหน้าถัดไป"}})
    if not buttons:
        return None
    return {
        "type": "bubble",
        "body": {"type": "box", "layout": "vertical", "contents": [
            {"type": "text", "text": "ผลการค้นหา", "weight": "bold", "align": "center"},
            {"type": "text", "text": f"หน้า {page} / {page_count}", "size": "sm", "color": "#777777", "align": "center", "margin": "sm"},
        ]},
        "footer": {"type": "box", "layout": "vertical", "spacing": "sm", "contents": buttons},
    }


def _reply_results(channel, reply_token, session, page=1):
    ctx = context(session)
    candidates = ctx.get("candidates") or []
    if not candidates:
        LineClient(channel).reply(reply_token, [{"type": "text", "text": "ไม่พบสินค้า"}])
        return
    flow = frappe.get_doc("LINE Business Flow", session.business_flow)
    cfg = frappe.get_doc(flow.configuration_doctype, flow.configuration_name)
    per_page = max(1, min(int(cfg.get("results_per_page") or 5), 10))
    page_count = max(1, (len(candidates) + per_page - 1) // per_page)
    page = max(1, min(int(page or 1), page_count))
    start_at = (page - 1) * per_page
    bubbles = [_result_bubble(cfg, session, code, start_at + offset) for offset, code in enumerate(candidates[start_at:start_at + per_page])]
    nav = _navigation_bubble(session, page, page_count)
    if nav:
        bubbles.append(nav)
    ctx["page"] = page
    set_context(session, ctx, "Showing Results")
    LineClient(channel).reply(reply_token, [{"type": "flex", "altText": f"ผลค้นหา Stock หน้า {page}/{page_count}", "contents": {"type": "carousel", "contents": bubbles}}])


def handle_text(channel, user_id, reply_token, session, text, **k):
    if session.current_state != "Waiting Query":
        return False
    flow = frappe.get_doc("LINE Business Flow", session.business_flow)
    cfg = frappe.get_doc(flow.configuration_doctype, flow.configuration_name)
    search_type = context(session).get("type", "any")
    rows, serial = stock.search(cfg, search_type, text)
    candidates = []
    for row in rows:
        item_code = row.name if hasattr(row, "name") else row.get("name")
        if item_code and item_code not in candidates:
            candidates.append(item_code)
    ctx = context(session)
    ctx.update({"candidates": candidates, "query": text, "page": 1})
    if serial:
        serial_no = getattr(serial, "name", None) or getattr(serial, "serial_no", None) or (serial.get("name") if isinstance(serial, dict) else None)
        if serial_no:
            ctx["serial_no"] = serial_no
    set_context(session, ctx, "Showing Results")
    if not candidates:
        LineClient(channel).reply(reply_token, [{"type": "text", "text": "ไม่พบสินค้า"}])
        return True
    _reply_results(channel, reply_token, session, page=1)
    return True


def show_page(channel, user_id, reply_token, params, **k):
    session = _valid_session(channel, user_id, params.get("session"))
    if not session:
        LineClient(channel).reply(reply_token, [{"type": "text", "text": "Session หมดอายุ กรุณาเริ่มค้นหาใหม่"}])
        return
    try:
        page = int(params.get("page") or 1)
    except (TypeError, ValueError):
        page = 1
    _reply_results(channel, reply_token, session, page=page)


def show_detail(channel, user_id, reply_token, params, **k):
    session = _valid_session(channel, user_id, params.get("session"))
    if not session:
        LineClient(channel).reply(reply_token, [{"type": "text", "text": "Session หมดอายุ กรุณาเริ่มค้นหาใหม่"}])
        return
    ctx = context(session)
    candidates = ctx.get("candidates") or []
    try:
        index = int(params.get("index"))
    except (TypeError, ValueError):
        index = -1
    if index < 0 or index >= len(candidates):
        LineClient(channel).reply(reply_token, [{"type": "text", "text": "ไม่พบรายการที่เลือก กรุณาค้นหาใหม่"}])
        return
    flow = frappe.get_doc("LINE Business Flow", session.business_flow)
    cfg = frappe.get_doc(flow.configuration_doctype, flow.configuration_name)
    snap = _item_snapshot(cfg, candidates[index])
    item = snap.item
    contents = [
        {"type": "text", "text": item.name, "weight": "bold", "size": "xl", "wrap": True},
        {"type": "text", "text": item.item_name or item.name, "size": "sm", "color": "#555555", "wrap": True, "margin": "sm"},
        {"type": "separator", "margin": "md"},
        _text_row("Item Group", item.item_group or "-"),
        _text_row("UOM", item.stock_uom or "-"),
    ]
    if cfg.get("show_purchase_price"):
        contents.append(_text_row("ราคาซื้อ", _money(snap.purchase_price, snap.purchase_currency)))
    if cfg.get("show_selling_price"):
        contents.append(_text_row("ราคาขาย", _money(snap.selling_price, snap.selling_currency)))
    contents += [{"type": "separator", "margin": "md"}, {"type": "text", "text": "Stock ตาม Warehouse", "weight": "bold", "size": "sm"}]
    if snap.stock_rows:
        for row in snap.stock_rows[:10]:
            contents.append(_text_row(row.warehouse, _qty(row.actual_qty, item.stock_uom)))
    else:
        contents.append({"type": "text", "text": "ไม่มี Stock ใน Warehouse ที่อนุญาต", "size": "sm", "color": "#777777", "wrap": True})
    contents.append(_text_row("รวม", _qty(snap.total_qty, item.stock_uom), bold=True))
    serial_no = ctx.get("serial_no")
    if serial_no:
        serial_warehouse = frappe.db.get_value("Serial No", serial_no, "warehouse")
        contents += [{"type": "separator", "margin": "md"}, _text_row("Serial No", serial_no), _text_row("Serial Warehouse", serial_warehouse or "-")]
    page = int(ctx.get("page") or 1)
    LineClient(channel).reply(reply_token, [{
        "type": "flex",
        "altText": f"รายละเอียด Stock {item.name}",
        "contents": {
            "type": "bubble",
            "body": {"type": "box", "layout": "vertical", "spacing": "sm", "contents": contents},
            "footer": {"type": "box", "layout": "vertical", "contents": [{
                "type": "button", "style": "primary", "height": "sm",
                "action": {"type": "postback", "label": "กลับผลค้นหา", "data": f"action=stock_page&session={session.name}&page={page}", "displayText": "กลับผลค้นหา Stock"},
            }]},
        },
    }])
# END PATCH: stock_query_flex_results_v1_5

