from __future__ import annotations

import math
from urllib.parse import urlencode

import frappe
from frappe.utils import add_to_date, now_datetime

from repair_management.integrations.line.api.client import LineClient
from repair_management.integrations.line.flows.base import active, context, set_context
from repair_management.integrations.line.media import signed_media_url
from repair_management.integrations.line.services import media_history


SELECTING_DOCUMENT = "Selecting Media Document"
SELECTING_MEDIA = "Selecting Final Media"
PAGE_SIZE = 10


def _postback(action, **params):
    return urlencode({"action": action, **params})


def _load_session(channel, user_id, session_name, state=None):
    if not session_name or not frappe.db.exists("LINE Flow Session", session_name):
        return None
    session = frappe.get_doc("LINE Flow Session", session_name)
    if session.line_channel != channel or session.line_user_id != user_id:
        return None
    if session.action_key != "media_view" or session.status != "Active":
        return None
    if session.expires_at and session.expires_at <= now_datetime():
        session.db_set({"status": "Expired", "current_state": "Expired"})
        return None
    if state and session.current_state != state:
        return None
    return session


def _create_session(channel, user_id, candidates):
    session = frappe.get_doc({
        "doctype": "LINE Flow Session",
        "line_channel": channel,
        "line_user_id": user_id,
        "action_key": "media_view",
        "current_state": SELECTING_DOCUMENT,
        "context_json": frappe.as_json({"document_candidates": candidates, "document_page": 1}),
        "expires_at": add_to_date(now_datetime(), minutes=15),
        "status": "Active",
    }).insert()
    return session


def _text_row(label, value):
    return {
        "type": "box", "layout": "baseline", "spacing": "sm",
        "contents": [
            {"type": "text", "text": str(label), "size": "xs", "color": "#8C8C8C", "flex": 3},
            {"type": "text", "text": str(value), "size": "xs", "color": "#333333", "wrap": True, "flex": 5},
        ],
    }


def _document_message(session, page=1):
    ctx = context(session)
    names = list(ctx.get("document_candidates") or [])
    total_pages = max(1, math.ceil(len(names) / PAGE_SIZE))
    page = min(max(int(page or 1), 1), total_pages)
    start = (page - 1) * PAGE_SIZE
    page_names = names[start:start + PAGE_SIZE]
    available = {row.name: row for row in media_history.list_sales_orders(session.line_channel, session.line_user_id, limit=200)}
    bubbles = []
    for offset, name in enumerate(page_names):
        row = available.get(name)
        if not row:
            continue
        bubbles.append({
            "type": "bubble", "size": "kilo",
            "body": {"type": "box", "layout": "vertical", "spacing": "md", "contents": [
                {"type": "text", "text": row.name, "weight": "bold", "wrap": True},
                {"type": "text", "text": row.customer_name or "-", "size": "sm", "color": "#555555", "wrap": True},
                {"type": "separator", "margin": "md"},
                {"type": "box", "layout": "vertical", "spacing": "sm", "contents": [
                    _text_row("วันที่", row.transaction_date or "-"),
                    _text_row("สถานะ", row.status or "-"),
                    _text_row("ไฟล์ยืนยัน", row.media_count),
                ]},
            ]},
            "footer": {"type": "box", "layout": "vertical", "contents": [{
                "type": "button", "style": "primary", "action": {
                    "type": "postback", "label": "เลือก Sales Order",
                    "displayText": f"ดูไฟล์ {row.name}",
                    "data": _postback("media_view_document_select", session=session.name, index=start + offset),
                },
            }]},
        })
    nav = []
    if page > 1:
        nav.append({"type": "button", "style": "secondary", "action": {"type": "postback", "label": "ก่อนหน้า", "data": _postback("media_view_document_page", session=session.name, page=page-1)}})
    if page < total_pages:
        nav.append({"type": "button", "style": "primary", "action": {"type": "postback", "label": "ถัดไป", "data": _postback("media_view_document_page", session=session.name, page=page+1)}})
    if nav:
        bubbles.append({"type": "bubble", "size": "kilo", "body": {"type": "box", "layout": "vertical", "contents": [{"type": "text", "text": f"หน้า {page}/{total_pages}", "align": "center"}]}, "footer": {"type": "box", "layout": "vertical", "spacing": "sm", "contents": nav}})
    return {"type": "flex", "altText": "เลือก Sales Order เพื่อดูไฟล์ยืนยัน", "contents": {"type": "carousel", "contents": bubbles}}


def _media_message(session, page=1):
    ctx = context(session)
    candidates = list(ctx.get("media_candidates") or [])
    total_pages = max(1, math.ceil(len(candidates) / PAGE_SIZE))
    page = min(max(int(page or 1), 1), total_pages)
    start = (page - 1) * PAGE_SIZE
    bubbles = []
    for offset, source_session in enumerate(candidates[start:start + PAGE_SIZE]):
        row = media_history.get_verified_media(session.line_channel, session.line_user_id, source_session, ctx.get("selected_sales_order"))
        if not row:
            continue
        dt = str(row.confirmed_at or "")[:16]
        bubbles.append({
            "type": "bubble", "size": "kilo",
            "body": {"type": "box", "layout": "vertical", "spacing": "md", "contents": [
                {"type": "text", "text": row.item_name or "-", "weight": "bold", "wrap": True},
                {"type": "separator", "margin": "md"},
                {"type": "box", "layout": "vertical", "spacing": "sm", "contents": [
                    _text_row("ประเภท", row.media_type), _text_row("วันที่ยืนยัน", dt),
                ]},
            ]},
            "footer": {"type": "box", "layout": "vertical", "contents": [{
                "type": "button", "style": "primary", "action": {
                    "type": "postback", "label": "ดูไฟล์",
                    "displayText": f"ดูไฟล์ {row.item_name}",
                    "data": _postback("media_view_select", session=session.name, index=start + offset),
                },
            }]},
        })
    nav=[]
    if page > 1:
        nav.append({"type": "button", "style": "secondary", "action": {"type": "postback", "label": "ก่อนหน้า", "data": _postback("media_view_page", session=session.name, page=page-1)}})
    if page < total_pages:
        nav.append({"type": "button", "style": "primary", "action": {"type": "postback", "label": "ถัดไป", "data": _postback("media_view_page", session=session.name, page=page+1)}})
    if nav:
        bubbles.append({"type": "bubble", "size": "kilo", "body": {"type": "box", "layout": "vertical", "contents": [{"type": "text", "text": f"หน้า {page}/{total_pages}", "align": "center"}]}, "footer": {"type": "box", "layout": "vertical", "spacing": "sm", "contents": nav}})
    return {"type": "flex", "altText": "เลือกไฟล์ที่ยืนยันแล้ว", "contents": {"type": "carousel", "contents": bubbles}}


def _line_media_message(row):
    original = signed_media_url(row.file_name, "original", 900)
    preview = signed_media_url(row.file_name, "preview", 900)
    if str(row.media_type).lower() == "video":
        return {"type": "video", "originalContentUrl": original, "previewImageUrl": preview}
    return {"type": "image", "originalContentUrl": original, "previewImageUrl": preview}


def start(channel, user_id, reply_token, **kwargs):
    current = active(channel, user_id)
    if current and current.action_key != "media_view":
        LineClient(channel).reply(reply_token, [{"type": "text", "text": "กรุณาทำรายการที่กำลังดำเนินการให้เสร็จสิ้นหรือยกเลิกก่อนดูไฟล์ยืนยัน"}])
        return
    if current and current.action_key == "media_view":
        current.db_set({"status": "Cancelled", "current_state": "Cancelled"})

    rows = media_history.list_sales_orders(channel, user_id, limit=100)
    if not rows:
        LineClient(channel).reply(reply_token, [{"type": "text", "text": "ไม่พบ Sales Order ที่ยังดำเนินการและมีไฟล์ยืนยัน"}])
        return
    session = _create_session(channel, user_id, [row.name for row in rows])
    LineClient(channel).reply(reply_token, [_document_message(session, 1)])


def document_page(channel, user_id, reply_token, params, **kwargs):
    session = _load_session(channel, user_id, params.get("session"), SELECTING_DOCUMENT)
    if not session:
        LineClient(channel).reply(reply_token, [{"type": "text", "text": "รายการหมดอายุแล้ว กรุณาเริ่มใหม่"}]); return
    try: page=max(int(params.get("page") or 1),1)
    except Exception: page=1
    LineClient(channel).reply(reply_token, [_document_message(session, page)])


def select_document(channel, user_id, reply_token, params, **kwargs):
    session = _load_session(channel, user_id, params.get("session"), SELECTING_DOCUMENT)
    if not session:
        LineClient(channel).reply(reply_token, [{"type": "text", "text": "รายการหมดอายุแล้ว กรุณาเริ่มใหม่"}]); return
    ctx=context(session)
    try: index=int(params.get("index"))
    except Exception: index=-1
    candidates=list(ctx.get("document_candidates") or [])
    if index < 0 or index >= len(candidates):
        LineClient(channel).reply(reply_token, [{"type": "text", "text": "ไม่พบ Sales Order ที่เลือก"}]); return
    sales_order=candidates[index]
    fresh={row.name for row in media_history.list_sales_orders(channel,user_id,limit=200)}
    if sales_order not in fresh:
        LineClient(channel).reply(reply_token, [{"type": "text", "text": "Sales Order นี้ไม่อยู่ในสถานะที่อนุญาตหรือไม่มีไฟล์ยืนยันแล้ว"}]); return
    media=media_history.list_media(channel,user_id,sales_order)
    if not media:
        LineClient(channel).reply(reply_token, [{"type": "text", "text": "ไม่พบไฟล์ยืนยันของ Sales Order นี้"}]); return
    ctx["selected_sales_order"]=sales_order
    ctx["media_candidates"]=[row.session for row in media]
    set_context(session,ctx,SELECTING_MEDIA)
    session.db_set({"target_doctype":"Sales Order","target_document":sales_order})
    if len(media)==1:
        row=media_history.get_verified_media(channel,user_id,media[0].session,sales_order)
        if not row:
            LineClient(channel).reply(reply_token,[{"type":"text","text":"ไฟล์ยืนยันไม่พร้อมใช้งาน"}]); return
        session.db_set({"status":"Completed","current_state":"Completed"})
        LineClient(channel).reply(reply_token,[_line_media_message(row)])
        return
    LineClient(channel).reply(reply_token,[_media_message(session,1)])


def media_page(channel,user_id,reply_token,params,**kwargs):
    session=_load_session(channel,user_id,params.get("session"),SELECTING_MEDIA)
    if not session:
        LineClient(channel).reply(reply_token,[{"type":"text","text":"รายการหมดอายุแล้ว กรุณาเริ่มใหม่"}]); return
    try: page=max(int(params.get("page") or 1),1)
    except Exception: page=1
    LineClient(channel).reply(reply_token,[_media_message(session,page)])


def select_media(channel,user_id,reply_token,params,**kwargs):
    session=_load_session(channel,user_id,params.get("session"),SELECTING_MEDIA)
    if not session:
        LineClient(channel).reply(reply_token,[{"type":"text","text":"รายการหมดอายุแล้ว กรุณาเริ่มใหม่"}]); return
    ctx=context(session)
    try: index=int(params.get("index"))
    except Exception: index=-1
    candidates=list(ctx.get("media_candidates") or [])
    if index < 0 or index >= len(candidates):
        LineClient(channel).reply(reply_token,[{"type":"text","text":"ไม่พบไฟล์ที่เลือก"}]); return
    row=media_history.get_verified_media(channel,user_id,candidates[index],ctx.get("selected_sales_order"))
    if not row:
        LineClient(channel).reply(reply_token,[{"type":"text","text":"ไฟล์นี้ไม่พร้อมใช้งานหรือ Sales Order ปิดงานแล้ว"}]); return
    session.db_set({"status":"Completed","current_state":"Completed"})
    # Use the fresh postback replyToken, so viewing a requested final media does not need Push.
    LineClient(channel).reply(reply_token,[_line_media_message(row)])


def handle_text(channel,user_id,reply_token,session,text,**kwargs):
    LineClient(channel).reply(reply_token,[{"type":"text","text":"กรุณาเลือกรายการจากปุ่มที่แสดง"}])
    return True
