import math
import mimetypes
from pathlib import Path
import tempfile
from urllib.parse import urlencode

import frappe
from frappe.utils import now_datetime, nowdate

from repair_management.integrations.line.api.client import LineClient
from repair_management.integrations.line.flows.base import create_session, context, set_context
from repair_management.integrations.line.services import attachments, burnin, collage, document_search
from repair_management.integrations.line.utils.files import resolve_file_path


SELECTING = "Selecting Document"
SELECTING_ITEM = "Selecting Item"
SELECTING_BURNIN = "Selecting Burn-in"
WAITING_MEDIA = "Waiting Media"


def profile(flow):
    return frappe.get_doc(flow.configuration_doctype, flow.configuration_name)


def _session_profile(session):
    flow = frappe.get_doc("LINE Business Flow", session.business_flow)
    return profile(flow)


def _page_size(p):
    # LINE Flex carousel supports at most 12 bubbles. Keep room for navigation.
    return min(max(int(p.maximum_results or 10), 1), 10)


def _postback(action, **params):
    return urlencode({"action": action, **params})


def _video_prompt_message(session, display=None, help_mode=False):
    title = f"เลือกเอกสารแล้ว\n{display}\n\n" if display else ""
    if help_mode:
        body = (
            "การแนบ VDO\n"
            "• ถ้าจะถ่ายใหม่ กด “เปิดกล้อง” แล้วสลับเป็นโหมดวิดีโอถ้า LINE/อุปกรณ์รองรับ\n"
            "• ถ้ามี VDO อยู่แล้ว ให้แตะปุ่ม + ของ LINE แล้วเลือกวิดีโอจากเครื่อง จากนั้นส่งในแชตนี้\n\n"
            "ระบบจะรับเฉพาะข้อความชนิด Video และแนบเข้า Sales Order ที่เลือกไว้"
        )
    else:
        body = (
            "เลือกวิธีส่ง VDO\n"
            "• เปิดกล้อง: สำหรับถ่าย VDO ใหม่\n"
            "• แนบ VDO: ดูวิธีเลือกวิดีโอที่มีอยู่ในเครื่อง"
        )
    return {
        "type": "text",
        "text": title + body,
        "quickReply": {
            "items": [
                {
                    "type": "action",
                    "action": {"type": "camera", "label": "เปิดกล้อง"},
                },
                {
                    "type": "action",
                    "action": {
                        "type": "postback",
                        "label": "แนบ VDO",
                        "displayText": "แนบ VDO",
                        "data": _postback("video_attach_help", session=session.name),
                    },
                },
                {
                    "type": "action",
                    "action": {
                        "type": "postback",
                        "label": "ยกเลิก",
                        "displayText": "ยกเลิก",
                        "data": _postback("media_cancel", session=session.name),
                    },
                },
            ]
        },
    }


def _candidate_bubble(item, session_name, index):
    detail_contents = []
    for detail in item.get("details", [])[:5]:
        detail_contents.append({
            "type": "box",
            "layout": "baseline",
            "spacing": "sm",
            "contents": [
                {"type": "text", "text": str(detail["label"]), "size": "xs", "color": "#8C8C8C", "flex": 3},
                {"type": "text", "text": str(detail["value"]), "size": "xs", "color": "#333333", "wrap": True, "flex": 5},
            ],
        })

    return {
        "type": "bubble",
        "size": "kilo",
        "body": {
            "type": "box",
            "layout": "vertical",
            "spacing": "md",
            "contents": [
                {"type": "text", "text": item["name"], "weight": "bold", "size": "md", "wrap": True},
                {"type": "text", "text": item.get("subtitle") or "Sales Order", "size": "sm", "color": "#555555", "wrap": True},
                {"type": "separator", "margin": "md"},
                {"type": "box", "layout": "vertical", "spacing": "sm", "contents": detail_contents},
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
                    "label": "เลือกเอกสาร",
                    "displayText": f"เลือก {item['name']}",
                    "data": _postback("document_select", session=session_name, index=index),
                },
            }],
        },
    }


def _navigation_bubble(session_name, page, total_pages):
    buttons = []
    if page > 1:
        buttons.append({
            "type": "button",
            "style": "secondary",
            "action": {
                "type": "postback",
                "label": "ก่อนหน้า",
                "data": _postback("document_page", session=session_name, page=page - 1),
            },
        })
    if page < total_pages:
        buttons.append({
            "type": "button",
            "style": "primary",
            "action": {
                "type": "postback",
                "label": "ถัดไป",
                "data": _postback("document_page", session=session_name, page=page + 1),
            },
        })
    return {
        "type": "bubble",
        "size": "kilo",
        "body": {
            "type": "box",
            "layout": "vertical",
            "justifyContent": "center",
            "contents": [
                {"type": "text", "text": "รายการเอกสาร", "weight": "bold", "align": "center"},
                {"type": "text", "text": f"หน้า {page}/{total_pages}", "size": "sm", "color": "#777777", "align": "center", "margin": "md"},
            ],
        },
        "footer": {"type": "box", "layout": "vertical", "spacing": "sm", "contents": buttons},
    }


def _selection_message(session, p, page=1):
    ctx = context(session)
    names = list(ctx.get("candidates") or [])
    size = _page_size(p)
    total_pages = max(1, math.ceil(len(names) / size))
    page = min(max(int(page or 1), 1), total_pages)
    start_index = (page - 1) * size
    page_names = names[start_index:start_index + size]
    rows = document_search.get_candidates(p, page_names)
    by_name = {row["name"]: row for row in rows}

    bubbles = []
    for offset, name in enumerate(page_names):
        item = by_name.get(name)
        if item:
            bubbles.append(_candidate_bubble(item, session.name, start_index + offset))
    if total_pages > 1:
        bubbles.append(_navigation_bubble(session.name, page, total_pages))

    return {
        "type": "flex",
        "altText": f"เลือก {p.target_doctype}",
        "contents": {"type": "carousel", "contents": bubbles},
    }


def _load_owned_session(channel, user_id, session_name, state=None):
    if not session_name or not frappe.db.exists("LINE Flow Session", session_name):
        return None
    session = frappe.get_doc("LINE Flow Session", session_name)
    if session.line_channel != channel or session.line_user_id != user_id or session.status != "Active":
        return None
    if session.expires_at and session.expires_at <= now_datetime():
        session.db_set({"status": "Expired", "current_state": "Expired"})
        return None
    if state and session.current_state != state:
        return None
    return session


def _sales_order_item_rows(document_name):
    doc = frappe.get_doc("Sales Order", document_name)
    return list(doc.items or [])


def _current_item_rows(session):
    ctx = context(session)
    candidates = list(ctx.get("item_candidates") or [])
    rows = _sales_order_item_rows(session.target_document)
    by_name = {row.name: row for row in rows}
    return [by_name[name] for name in candidates if name in by_name]


def _remember_selected_item(session, row, state=SELECTING_BURNIN):
    ctx = context(session)
    ctx["selected_item_row"] = row.name
    ctx["item_code"] = row.item_code
    ctx["item_name"] = row.item_name or row.item_code
    set_context(session, ctx, state)


def _revalidate_target_item(session, p):
    if not session.target_document or not document_search.is_eligible(p, session.target_document):
        return None, "document"
    ctx = context(session)
    row_name = ctx.get("selected_item_row")
    if not row_name:
        return None, "item"
    for row in _sales_order_item_rows(session.target_document):
        if row.name == row_name:
            return row, None
    return None, "item"


def _item_bubble(row, session_name, index):
    qty_text = f"{row.qty} {row.uom or ''}".strip()
    return {
        "type": "bubble",
        "size": "kilo",
        "body": {
            "type": "box",
            "layout": "vertical",
            "spacing": "md",
            "contents": [
                {"type": "text", "text": row.item_code or "-", "weight": "bold", "size": "md", "wrap": True},
                {"type": "text", "text": row.item_name or row.item_code or "-", "size": "sm", "color": "#555555", "wrap": True},
                {"type": "separator", "margin": "md"},
                {
                    "type": "box",
                    "layout": "baseline",
                    "spacing": "sm",
                    "contents": [
                        {"type": "text", "text": "จำนวน", "size": "xs", "color": "#8C8C8C", "flex": 2},
                        {"type": "text", "text": qty_text, "size": "xs", "color": "#333333", "wrap": True, "flex": 5},
                    ],
                },
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
                    "label": "เลือกรายการนี้",
                    "displayText": f"เลือก {row.item_code}",
                    "data": _postback("document_item_select", session=session_name, index=index),
                },
            }],
        },
    }


def _item_navigation_bubble(session_name, page, total_pages):
    buttons = []
    if page > 1:
        buttons.append({
            "type": "button",
            "style": "secondary",
            "action": {
                "type": "postback",
                "label": "ก่อนหน้า",
                "data": _postback("document_item_page", session=session_name, page=page - 1),
            },
        })
    if page < total_pages:
        buttons.append({
            "type": "button",
            "style": "primary",
            "action": {
                "type": "postback",
                "label": "ถัดไป",
                "data": _postback("document_item_page", session=session_name, page=page + 1),
            },
        })
    return {
        "type": "bubble",
        "size": "kilo",
        "body": {
            "type": "box",
            "layout": "vertical",
            "justifyContent": "center",
            "contents": [
                {"type": "text", "text": "รายการสินค้า", "weight": "bold", "align": "center"},
                {"type": "text", "text": f"หน้า {page}/{total_pages}", "size": "sm", "color": "#777777", "align": "center", "margin": "md"},
            ],
        },
        "footer": {"type": "box", "layout": "vertical", "spacing": "sm", "contents": buttons},
    }


def _item_selection_message(session, page=1):
    ctx = context(session)
    candidates = list(ctx.get("item_candidates") or [])
    page_size = 10
    total_pages = max(1, math.ceil(len(candidates) / page_size))
    page = min(max(int(page or 1), 1), total_pages)
    start = (page - 1) * page_size
    page_names = candidates[start:start + page_size]

    rows = _sales_order_item_rows(session.target_document)
    by_name = {row.name: row for row in rows}
    bubbles = []
    for offset, row_name in enumerate(page_names):
        row = by_name.get(row_name)
        if row:
            bubbles.append(_item_bubble(row, session.name, start + offset))
    if total_pages > 1:
        bubbles.append(_item_navigation_bubble(session.name, page, total_pages))

    return {
        "type": "flex",
        "altText": "เลือกรายการสินค้า",
        "contents": {"type": "carousel", "contents": bubbles},
    }


def _burnin_prompt_message(session):
    ctx = context(session)
    item_name = ctx.get("item_name") or "-"
    return {
        "type": "text",
        "text": f"สินค้า: {item_name}\n\nต้องการระบุชื่อสินค้าบนไฟล์หรือไม่?",
        "quickReply": {
            "items": [
                {
                    "type": "action",
                    "action": {
                        "type": "postback",
                        "label": "ระบุข้อความ",
                        "displayText": "ระบุชื่อสินค้าบนไฟล์",
                        "data": _postback("burn_in_select", session=session.name, value=1),
                    },
                },
                {
                    "type": "action",
                    "action": {
                        "type": "postback",
                        "label": "ไม่ระบุ",
                        "displayText": "ไม่ระบุชื่อสินค้าบนไฟล์",
                        "data": _postback("burn_in_select", session=session.name, value=0),
                    },
                },
                {
                    "type": "action",
                    "action": {
                        "type": "postback",
                        "label": "ยกเลิก",
                        "displayText": "ยกเลิก",
                        "data": _postback("media_cancel", session=session.name),
                    },
                },
            ]
        },
    }


def _media_prompt_message(session, p):
    ctx = context(session)
    item_name = ctx.get("item_name") or "-"
    burn_label = "ระบุชื่อสินค้า" if int(ctx.get("burn_in") or 0) else "ไม่ระบุข้อความ"
    display = f"{session.target_document} — {item_name}"

    if p.media_type == "Image":
        return {
            "type": "text",
            "text": (
                f"เลือกเอกสารและสินค้าแล้ว\n{display}\n"
                f"Burn-in: {burn_label}\n\n"
                f"กรุณาถ่ายรูปหรือเลือกรูปจากเครื่อง (1–{int(p.maximum_files or 8)} รูป)"
            ),
            "quickReply": {
                "items": [
                    {"type": "action", "action": {"type": "camera", "label": "ถ่ายรูป"}},
                    {"type": "action", "action": {"type": "cameraRoll", "label": "เลือกรูป"}},
                    {
                        "type": "action",
                        "action": {
                            "type": "postback",
                            "label": "ยกเลิก",
                            "displayText": "ยกเลิก",
                            "data": _postback("media_cancel", session=session.name),
                        },
                    },
                ]
            },
        }
    return _video_prompt_message(session, display=display)


def _verify_attachment(file_name, doctype, docname):
    if not file_name or not frappe.db.exists("File", file_name):
        return False
    values = frappe.db.get_value(
        "File",
        file_name,
        ["attached_to_doctype", "attached_to_name"],
        as_dict=True,
    )
    return bool(
        values
        and values.attached_to_doctype == doctype
        and values.attached_to_name == docname
    )


def _remember_final_file(session, file_name):
    ctx = context(session)
    ctx["final_file"] = file_name
    set_context(session, ctx)


def _existing_final_file(session):
    file_name = context(session).get("final_file")
    if _verify_attachment(file_name, session.target_doctype, session.target_document):
        return file_name
    return None




def _image_quality(profile_doc):
    for fieldname in (
        "jpeg_quality",
        "image_quality",
        "collage_quality",
        "output_quality",
        "quality",
    ):
        value = getattr(profile_doc, fieldname, None)
        try:
            quality = int(value)
        except (TypeError, ValueError):
            continue
        if 40 <= quality <= 95:
            return quality
    return 85


def _remember_burnin_date(session):
    ctx = context(session)
    if not ctx.get("burn_in_date"):
        ctx["burn_in_date"] = nowdate()
        set_context(session, ctx)
    return ctx["burn_in_date"]


def _image_burnin_text(item_name, burn_in_date):
    if not item_name:
        raise ValueError("Item Name snapshot is required for image Burn-in")
    text = str(item_name).strip()
    if burn_in_date:
        text = f"{text}\n{str(burn_in_date).strip()}"
    return text

def _complete_video_session(channel, session, cleanup_errors=None):
    session.db_set({
        "status": "Completed",
        "current_state": "Completed",
        "error_message": "\n".join(cleanup_errors or [])[:1400] if cleanup_errors else None,
    })
    LineClient(channel).push(
        session.line_user_id,
        [{"type": "text", "text": "แนบ VDO สำเร็จ"}],
    )

def start(channel, user_id, reply_token, flow, **kwargs):
    p = profile(flow)
    rows = document_search.list_candidates(p, limit=100)
    if not rows:
        LineClient(channel).reply(reply_token, [{"type": "text", "text": f"ไม่พบ {p.target_doctype} ที่อยู่ระหว่างดำเนินการ"}])
        return

    session = create_session(channel, user_id, flow, SELECTING, {
        "profile": p.name,
        "candidates": [row["name"] for row in rows],
        "page": 1,
    })
    session.db_set({
        "target_doctype": p.target_doctype,
        "expected_media_type": p.media_type,
    })
    LineClient(channel).reply(reply_token, [_selection_message(session, p, 1)])


def show_page(channel, user_id, reply_token, params, **kwargs):
    session = _load_owned_session(channel, user_id, params.get("session"), SELECTING)
    if not session:
        LineClient(channel).reply(reply_token, [{"type": "text", "text": "รายการนี้หมดอายุแล้ว กรุณาเริ่มรายการใหม่"}])
        return
    p = _session_profile(session)
    try:
        page = int(params.get("page") or 1)
    except (TypeError, ValueError):
        page = 1
    ctx = context(session)
    ctx["page"] = page
    set_context(session, ctx)
    LineClient(channel).reply(reply_token, [_selection_message(session, p, page)])


def select_document(channel, user_id, reply_token, params, **kwargs):
    session = _load_owned_session(channel, user_id, params.get("session"), SELECTING)
    if not session:
        LineClient(channel).reply(reply_token, [{"type": "text", "text": "รายการนี้หมดอายุแล้ว กรุณาเริ่มรายการใหม่"}])
        return

    p = _session_profile(session)
    ctx = context(session)
    candidates = list(ctx.get("candidates") or [])
    try:
        index = int(params.get("index"))
    except (TypeError, ValueError):
        index = -1
    if index < 0 or index >= len(candidates):
        LineClient(channel).reply(reply_token, [{"type": "text", "text": "ไม่พบเอกสารที่เลือก กรุณาเปิดรายการใหม่"}])
        return

    document_name = candidates[index]
    if not document_search.is_eligible(p, document_name):
        fresh = document_search.list_candidates(p, limit=100)
        ctx["candidates"] = [row["name"] for row in fresh]
        ctx["page"] = 1
        set_context(session, ctx, SELECTING)
        if fresh:
            LineClient(channel).reply(reply_token, [
                {"type": "text", "text": "เอกสารนี้ไม่สามารถใช้งานได้แล้ว กรุณาเลือกรายการใหม่"},
                _selection_message(session, p, 1),
            ])
        else:
            session.db_set({"status": "Cancelled", "current_state": "Cancelled"})
            LineClient(channel).reply(reply_token, [{"type": "text", "text": f"ไม่พบ {p.target_doctype} ที่อยู่ระหว่างดำเนินการ"}])
        return

    if p.target_doctype != "Sales Order":
        frappe.throw("Item selection is currently implemented for Sales Order targets only")

    session.db_set("target_document", document_name)
    rows = _sales_order_item_rows(document_name)
    if not rows:
        session.db_set({"status": "Cancelled", "current_state": "Cancelled"})
        LineClient(channel).reply(reply_token, [{"type": "text", "text": "Sales Order นี้ไม่มีรายการสินค้า"}])
        return

    ctx = context(session)
    ctx["item_candidates"] = [row.name for row in rows]
    ctx["item_page"] = 1
    set_context(session, ctx)

    if len(rows) == 1:
        _remember_selected_item(session, rows[0], SELECTING_BURNIN)
        LineClient(channel).reply(reply_token, [_burnin_prompt_message(session)])
        return

    set_context(session, context(session), SELECTING_ITEM)
    LineClient(channel).reply(reply_token, [
        {"type": "text", "text": f"เลือก {document_name} แล้ว กรุณาเลือกรายการสินค้า"},
        _item_selection_message(session, 1),
    ])


def show_item_page(channel, user_id, reply_token, params, **kwargs):
    session = _load_owned_session(channel, user_id, params.get("session"), SELECTING_ITEM)
    if not session:
        LineClient(channel).reply(reply_token, [{"type": "text", "text": "รายการนี้หมดอายุแล้ว กรุณาเริ่มรายการใหม่"}])
        return
    try:
        page = int(params.get("page") or 1)
    except (TypeError, ValueError):
        page = 1
    ctx = context(session)
    ctx["item_page"] = page
    set_context(session, ctx)
    LineClient(channel).reply(reply_token, [_item_selection_message(session, page)])


def select_item(channel, user_id, reply_token, params, **kwargs):
    session = _load_owned_session(channel, user_id, params.get("session"), SELECTING_ITEM)
    if not session:
        LineClient(channel).reply(reply_token, [{"type": "text", "text": "รายการนี้หมดอายุแล้ว กรุณาเริ่มรายการใหม่"}])
        return
    p = _session_profile(session)
    if not document_search.is_eligible(p, session.target_document):
        session.db_set({"status": "Cancelled", "current_state": "Cancelled"})
        LineClient(channel).reply(reply_token, [{"type": "text", "text": "Sales Order ไม่อยู่ในสถานะที่อนุญาตแล้ว กรุณาเริ่มรายการใหม่"}])
        return

    ctx = context(session)
    candidates = list(ctx.get("item_candidates") or [])
    try:
        index = int(params.get("index"))
    except (TypeError, ValueError):
        index = -1
    if index < 0 or index >= len(candidates):
        LineClient(channel).reply(reply_token, [{"type": "text", "text": "ไม่พบรายการสินค้าที่เลือก"}])
        return

    selected_row_name = candidates[index]
    rows = _sales_order_item_rows(session.target_document)
    row = next((item for item in rows if item.name == selected_row_name), None)
    if not row:
        fresh = _sales_order_item_rows(session.target_document)
        ctx["item_candidates"] = [item.name for item in fresh]
        ctx["item_page"] = 1
        set_context(session, ctx, SELECTING_ITEM)
        LineClient(channel).reply(reply_token, [
            {"type": "text", "text": "รายการสินค้ามีการเปลี่ยนแปลง กรุณาเลือกใหม่"},
            _item_selection_message(session, 1),
        ])
        return

    _remember_selected_item(session, row, SELECTING_BURNIN)
    LineClient(channel).reply(reply_token, [_burnin_prompt_message(session)])


def select_burn_in(channel, user_id, reply_token, params, **kwargs):
    session = _load_owned_session(channel, user_id, params.get("session"), SELECTING_BURNIN)
    if not session:
        LineClient(channel).reply(reply_token, [{"type": "text", "text": "รายการนี้หมดอายุแล้ว กรุณาเริ่มรายการใหม่"}])
        return

    p = _session_profile(session)
    row, reason = _revalidate_target_item(session, p)
    if reason:
        session.db_set({"status": "Cancelled", "current_state": "Cancelled"})
        LineClient(channel).reply(reply_token, [{"type": "text", "text": "เอกสารหรือรายการสินค้ามีการเปลี่ยนแปลง กรุณาเริ่มรายการใหม่"}])
        return

    raw = str(params.get("value") or "")
    if raw not in ("0", "1"):
        LineClient(channel).reply(reply_token, [{"type": "text", "text": "ค่าการระบุข้อความไม่ถูกต้อง"}])
        return

    ctx = context(session)
    ctx["burn_in"] = int(raw)
    # Keep the selected Item Name as the server-side snapshot used for this media session.
    ctx["item_name"] = ctx.get("item_name") or row.item_name or row.item_code
    set_context(session, ctx, WAITING_MEDIA)
    LineClient(channel).reply(reply_token, [_media_prompt_message(session, p)])

def _image_continue_message(session, p, count):
    maximum = int(p.maximum_files or 8)
    remaining = max(maximum - int(count or 0), 0)
    text = f"รับรูปแล้ว {count}/{maximum} รูป"
    if remaining:
        text += "\nสามารถส่งรูปเพิ่ม หรือกด เสร็จสิ้น เพื่อแนบไปยังเอกสาร"
    else:
        text += "\nรับรูปครบจำนวนสูงสุดแล้ว ระบบกำลังรวมและแนบรูป"

    items = []
    if remaining:
        items.extend([
            {"type": "action", "action": {"type": "camera", "label": "ถ่ายเพิ่ม"}},
            {"type": "action", "action": {"type": "cameraRoll", "label": "เลือกเพิ่ม"}},
            {"type": "action", "action": {"type": "postback", "label": "เสร็จสิ้น", "displayText": "เสร็จสิ้นการส่งรูป", "data": _postback("media_finish", session=session.name)}},
        ])
    items.append({"type": "action", "action": {"type": "postback", "label": "ยกเลิก", "displayText": "ยกเลิก", "data": _postback("media_cancel", session=session.name)}})

    message = {"type": "text", "text": text}
    if items:
        message["quickReply"] = {"items": items}
    return message



def video_attach_help(channel, user_id, reply_token, params, **kwargs):
    session = _load_owned_session(channel, user_id, params.get("session"), WAITING_MEDIA)
    if not session:
        LineClient(channel).reply(
            reply_token,
            [{"type": "text", "text": "รายการนี้หมดอายุแล้ว กรุณาเริ่มรายการใหม่"}],
        )
        return
    p = _session_profile(session)
    if (p.media_type or "").lower() != "video":
        LineClient(channel).reply(
            reply_token,
            [{"type": "text", "text": "Session นี้ไม่ได้รอรับ VDO"}],
        )
        return
    LineClient(channel).reply(reply_token, [_video_prompt_message(session, help_mode=True)])



def cancel(channel, user_id, reply_token, params, **kwargs):
    session = _load_owned_session(channel, user_id, params.get("session"))
    if not session:
        LineClient(channel).reply(reply_token, [{"type": "text", "text": "รายการนี้หมดอายุแล้ว"}])
        return
    session.db_set({"status": "Cancelled", "current_state": "Cancelled"})
    LineClient(channel).reply(reply_token, [{"type": "text", "text": "ยกเลิกรายการแล้ว"}])


def finish(channel, user_id, reply_token, params, **kwargs):
    session = _load_owned_session(channel, user_id, params.get("session"), WAITING_MEDIA)
    if not session:
        LineClient(channel).reply(reply_token, [{"type": "text", "text": "รายการนี้หมดอายุแล้ว กรุณาเริ่มรายการใหม่"}])
        return
    p = _session_profile(session)
    count = int(session.received_files or 0)
    minimum = int(p.minimum_files or 1)
    maximum = int(p.maximum_files or 8)
    if count < minimum:
        LineClient(channel).reply(reply_token, [{"type": "text", "text": f"กรุณาส่งรูปอย่างน้อย {minimum} รูปก่อนกดเสร็จสิ้น"}])
        return
    if count > maximum:
        LineClient(channel).reply(reply_token, [{"type": "text", "text": f"จำนวนไฟล์เกินกำหนดสูงสุด {maximum} รูป"}])
        return
    session.db_set("current_state", "Finalizing")
    LineClient(channel).reply(reply_token, [{"type": "text", "text": "กำลังรวมและแนบรูป กรุณารอสักครู่"}])
    frappe.enqueue(finalize, queue="long", channel=channel, session_name=session.name, enqueue_after_commit=True)


def handle_text(channel, user_id, reply_token, session, text, **kwargs):
    if session.current_state == SELECTING:
        p = _session_profile(session)
        LineClient(channel).reply(reply_token, [
            {"type": "text", "text": "กรุณาเลือกเอกสารจากรายการ"},
            _selection_message(session, p, context(session).get("page", 1)),
        ])
        return True

    if session.current_state == SELECTING_ITEM:
        LineClient(channel).reply(reply_token, [
            {"type": "text", "text": "กรุณาเลือกรายการสินค้าจากรายการ"},
            _item_selection_message(session, context(session).get("item_page", 1)),
        ])
        return True

    if session.current_state == SELECTING_BURNIN:
        LineClient(channel).reply(reply_token, [_burnin_prompt_message(session)])
        return True

    if session.current_state == WAITING_MEDIA:
        p = _session_profile(session)
        if (p.media_type or "").lower() == "video":
            LineClient(channel).reply(reply_token, [_video_prompt_message(session, help_mode=True)])
            return True
    return False


def receive(channel, user_id, reply_token, session, message, **kwargs):
    if session.current_state != WAITING_MEDIA or not session.target_document:
        return False
    p = _session_profile(session)

    ctx = context(session)
    if ctx.get("burn_in") not in (0, 1):
        LineClient(channel).reply(reply_token, [{"type": "text", "text": "กรุณาเลือกการระบุข้อความก่อนส่งไฟล์"}])
        return True

    row, reason = _revalidate_target_item(session, p)
    if reason:
        session.db_set({"status": "Cancelled", "current_state": "Cancelled"})
        LineClient(channel).reply(reply_token, [{"type": "text", "text": "เอกสารหรือรายการสินค้ามีการเปลี่ยนแปลง กรุณาเริ่มรายการใหม่"}])
        return True

    expected = (p.media_type or "").lower()
    actual = (message.get("type") or "").lower()
    if expected != actual:
        LineClient(channel).reply(reply_token, [{"type": "text", "text": "ชนิดไฟล์ไม่ตรงกับรายการที่กำลังยืนยัน"}])
        return True

    maximum = int(p.maximum_files or 8)
    if int(session.received_files or 0) >= maximum:
        LineClient(channel).reply(reply_token, [{"type": "text", "text": f"รับไฟล์ครบจำนวนสูงสุด {maximum} ไฟล์แล้ว"}])
        return True

    frappe.enqueue(
        download,
        queue="long",
        channel=channel,
        session_name=session.name,
        message=message,
        enqueue_after_commit=True,
    )
    LineClient(channel).reply(reply_token, [{"type": "text", "text": "กำลังรับไฟล์"}])
    return True


def download(channel, session_name, message):
    session = frappe.get_doc("LINE Flow Session", session_name)
    p = _session_profile(session)
    ctx = context(session)

    row, reason = _revalidate_target_item(session, p)
    if reason:
        session.db_set({"status": "Failed", "current_state": "Failed", "error_message": "Target document or item is no longer valid"})
        return

    content, content_type = LineClient(channel).get_content(message["id"])
    sequence = frappe.db.count("LINE Media File", {"flow_session": session.name}) + 1
    extension = mimetypes.guess_extension(content_type.split(";")[0]) or (".jpg" if p.media_type == "Image" else ".mp4")
    prefix = "LINE-PHOTO" if p.media_type == "Image" else "LINE-VIDEO"
    file_doc = attachments.save(
        content,
        f"{prefix}-{session.target_document}-{sequence:02d}{extension}",
        "LINE Flow Session",
        session.name,
        bool(p.private_file),
    )
    image_set = message.get("imageSet") or {}
    media_row = frappe.get_doc({
        "doctype": "LINE Media File",
        "flow_session": session.name,
        "line_message_id": message["id"],
        "image_set_id": image_set.get("id"),
        "image_index": image_set.get("index") if image_set.get("index") is not None else sequence,
        "media_type": p.media_type,
        "temporary_file": file_doc.name,
        "processing_status": "Downloaded",
    }).insert()

    count = frappe.db.count(
        "LINE Media File",
        {"flow_session": session.name, "processing_status": "Downloaded"},
    )
    session.db_set("received_files", count)

    if p.media_type == "Image":
        _remember_burnin_date(session)

    if p.media_type == "Video":
        if int(ctx.get("burn_in") or 0):
            session.db_set("current_state", "Finalizing")
            LineClient(channel).push(
                session.line_user_id,
                [{"type": "text", "text": "รับ VDO แล้ว กำลังระบุชื่อสินค้าและแนบไปยังเอกสาร"}],
            )
            frappe.enqueue(
                process_video_burnin,
                queue="long",
                channel=channel,
                session_name=session.name,
                media_row_name=media_row.name,
                enqueue_after_commit=True,
            )
            return

        attachments.relink(file_doc.name, session.target_doctype, session.target_document)
        if not _verify_attachment(file_doc.name, session.target_doctype, session.target_document):
            frappe.throw("Video attachment verification failed")
        frappe.db.set_value(
            "LINE Media File",
            media_row.name,
            {"processing_status": "Finalized"},
            update_modified=False,
        )
        _remember_final_file(session, file_doc.name)
        _complete_video_session(channel, session)
        return

    maximum = int(p.maximum_files or 8)
    if count >= maximum:
        session.db_set("current_state", "Finalizing")
        LineClient(channel).push(
            session.line_user_id,
            [{"type": "text", "text": f"รับรูปครบ {count}/{maximum} รูปแล้ว กำลังรวมและแนบไปยังเอกสาร"}],
        )
        frappe.enqueue(
            finalize,
            queue="long",
            channel=channel,
            session_name=session.name,
            enqueue_after_commit=True,
        )
    else:
        LineClient(channel).push(session.line_user_id, [_image_continue_message(session, p, count)])



def process_video_burnin(channel, session_name, media_row_name):
    session = frappe.get_doc("LINE Flow Session", session_name)
    p = _session_profile(session)
    ctx = context(session)

    try:
        row, reason = _revalidate_target_item(session, p)
        if reason:
            frappe.throw("Target document or item is no longer eligible")

        existing = _existing_final_file(session)
        media_row = frappe.get_doc("LINE Media File", media_row_name)
        if existing:
            cleanup_errors = _cleanup_original_media([media_row])
            _complete_video_session(channel, session, cleanup_errors)
            return

        if not media_row.temporary_file or not frappe.db.exists("File", media_row.temporary_file):
            frappe.throw("Original video File is missing")

        source_doc = frappe.get_doc("File", media_row.temporary_file)
        source_path = resolve_file_path(source_doc.file_url)
        if not source_path.exists():
            frappe.throw("Original video path is missing")

        item_name = ctx.get("item_name")
        if not item_name:
            frappe.throw("Item Name snapshot is missing")

        output_path = None
        try:
            with tempfile.NamedTemporaryFile(
                suffix=".mp4",
                prefix=f"line-video-{session.name}-",
                delete=False,
            ) as handle:
                output_path = Path(handle.name)

            burnin.burn_in_video(source_path, output_path, item_name)

            final_doc = attachments.save(
                output_path.read_bytes(),
                f"LINE-VIDEO-BURNIN-{session.target_document}-{session.name}.mp4",
                session.target_doctype,
                session.target_document,
                bool(p.private_file),
            )
            if not _verify_attachment(final_doc.name, session.target_doctype, session.target_document):
                frappe.throw("Final video attachment verification failed")

            _remember_final_file(session, final_doc.name)
            cleanup_errors = _cleanup_original_media([media_row])
            _complete_video_session(channel, session, cleanup_errors)
        finally:
            if output_path:
                try:
                    output_path.unlink(missing_ok=True)
                except Exception:
                    pass
    except Exception as exc:
        session.db_set({
            "status": "Failed",
            "current_state": "Failed",
            "error_message": str(exc),
        })
        LineClient(channel).push(
            session.line_user_id,
            [{"type": "text", "text": "ประมวลผล VDO ไม่สำเร็จ ระบบเก็บไฟล์ต้นฉบับไว้สำหรับ Retry"}],
        )
        raise

def _find_existing_collage(session):
    """Return an already attached collage File, if a previous finalize got that far."""
    prefix = f"COLLAGE-{session.target_document}-"
    rows = frappe.get_all(
        "File",
        filters={
            "attached_to_doctype": session.target_doctype,
            "attached_to_name": session.target_document,
        },
        fields=["name", "file_name", "file_url", "creation"],
        order_by="creation desc",
        limit=50,
    )
    for row in rows:
        if (row.file_name or "").startswith(prefix):
            return row
    return None


def _recover_physical_collage(session, p):
    """Recover a collage written to disk before a failed DB transaction completed."""
    prefix = f"COLLAGE-{session.target_document}-"
    candidates = []
    for private in (True, False):
        folder = frappe.get_site_path("private" if private else "public", "files")
        path = resolve_file_path(f"/{'private' if private else 'files'}/files/dummy")
        # resolve_file_path behavior is site-relative in this app; use get_site_path
        # directly for recovery so worker cwd does not matter.
        folder_path = frappe.get_site_path("private" if private else "public", "files")
        from pathlib import Path
        folder_obj = Path(folder_path)
        if folder_obj.exists():
            candidates.extend(folder_obj.glob(f"{prefix}*.jpg"))
    if not candidates:
        return None
    candidate = max(candidates, key=lambda pth: pth.stat().st_mtime)
    return attachments.save(
        candidate.read_bytes(),
        candidate.name,
        session.target_doctype,
        session.target_document,
        bool(p.private_file),
    )


def _cleanup_original_media(rows):
    """Detach LINE Media File links first, then delete originals.

    Cleanup is deliberately best-effort after the final attachment exists.
    A cleanup problem must not turn an already-successful final attachment
    into a failed business transaction.
    """
    errors = []
    for row in rows:
        file_name = row.temporary_file
        try:
            # LINE Media File.temporary_file is a Link to File. Clear it before
            # deleting File, otherwise Frappe raises LinkExistsError.
            frappe.db.set_value(
                "LINE Media File",
                row.name,
                {
                    "temporary_file": None,
                    "processing_status": "Finalized",
                },
                update_modified=False,
            )
            if file_name and frappe.db.exists("File", file_name):
                frappe.delete_doc("File", file_name, ignore_permissions=True)
        except Exception as exc:
            errors.append(f"{row.name}: {exc}")
            frappe.log_error(
                title=f"LINE original cleanup failed: {row.name}",
                message=frappe.get_traceback(),
            )
    return errors


def _complete_image_session(channel, session, rows, cleanup_errors=None):
    session.db_set(
        {
            "status": "Completed",
            "current_state": "Completed",
            "error_message": "\n".join(cleanup_errors or [])[:1400] if cleanup_errors else None,
        }
    )
    LineClient(channel).push(
        session.line_user_id,
        [{"type": "text", "text": "แนบภาพสำเร็จ"}],
    )



def finalize(channel, session_name):
    session = frappe.get_doc("LINE Flow Session", session_name)
    p = _session_profile(session)
    ctx = context(session)

    if not session.target_doctype or not session.target_document:
        session.db_set({"status": "Failed", "current_state": "Failed", "error_message": "Missing target document"})
        return

    row, reason = _revalidate_target_item(session, p)
    if reason:
        session.db_set({"status": "Failed", "current_state": "Failed", "error_message": "Target document or item is no longer eligible"})
        LineClient(channel).push(session.line_user_id, [{"type": "text", "text": "เอกสารหรือรายการสินค้าเปลี่ยนแปลง จึงยังไม่ได้แนบรูป"}])
        return

    rows = frappe.get_all(
        "LINE Media File",
        filters={
            "flow_session": session.name,
            "media_type": "Image",
            "processing_status": ["in", ["Downloaded", "Finalized"]],
        },
        fields=["name", "temporary_file", "image_index", "processing_status"],
        order_by="image_index asc",
    )

    try:
        if not rows:
            frappe.throw("No image files found for this LINE Flow Session")

        existing = _existing_final_file(session)
        if existing:
            cleanup_errors = _cleanup_original_media(rows) if len(rows) > 1 or int(ctx.get("burn_in") or 0) else []
            _complete_image_session(channel, session, rows, cleanup_errors)
            return

        burn_enabled = bool(int(ctx.get("burn_in") or 0))
        item_name = ctx.get("item_name")
        if burn_enabled and not item_name:
            frappe.throw("Item Name snapshot is missing")

        if len(rows) == 1 and p.single_image_mode == "Attach Directly":
            media_row = rows[0]
            if not media_row.temporary_file or not frappe.db.exists("File", media_row.temporary_file):
                frappe.throw("Original image File is missing")

            if not burn_enabled:
                attachments.relink(media_row.temporary_file, session.target_doctype, session.target_document)
                if not _verify_attachment(media_row.temporary_file, session.target_doctype, session.target_document):
                    frappe.throw("Image attachment verification failed")
                frappe.db.set_value(
                    "LINE Media File",
                    media_row.name,
                    {"processing_status": "Finalized"},
                    update_modified=False,
                )
                _remember_final_file(session, media_row.temporary_file)
                _complete_image_session(channel, session, rows)
                return

            fdoc = frappe.get_doc("File", media_row.temporary_file)
            source_path = resolve_file_path(fdoc.file_url)
            burn_text = _image_burnin_text(item_name, _remember_burnin_date(session))
            final_bytes = burnin.burn_in_image_bytes(
                source_path.read_bytes(),
                burn_text,
                quality=_image_quality(p),
            )
            final_doc = attachments.save(
                final_bytes,
                f"LINE-PHOTO-BURNIN-{session.target_document}-{session.name}.jpg",
                session.target_doctype,
                session.target_document,
                bool(p.private_file),
            )
            if not _verify_attachment(final_doc.name, session.target_doctype, session.target_document):
                frappe.throw("Burn-in image attachment verification failed")

            _remember_final_file(session, final_doc.name)
            cleanup_errors = _cleanup_original_media(rows)
            _complete_image_session(channel, session, rows, cleanup_errors)
            return

        raw_images = []
        missing = []
        for media_row in rows:
            if not media_row.temporary_file or not frappe.db.exists("File", media_row.temporary_file):
                missing.append(media_row.name)
                continue
            fdoc = frappe.get_doc("File", media_row.temporary_file)
            path = resolve_file_path(fdoc.file_url)
            try:
                raw_images.append(path.read_bytes())
            except FileNotFoundError:
                missing.append(media_row.name)

        if missing:
            recovered = _recover_physical_collage(session, p)
            if recovered and _verify_attachment(recovered.name, session.target_doctype, session.target_document):
                _remember_final_file(session, recovered.name)
                cleanup_errors = _cleanup_original_media(rows) if p.delete_originals_after_merge else []
                _complete_image_session(channel, session, rows, cleanup_errors)
                return
            frappe.throw(
                "Missing original image files and no recoverable collage was found: "
                + ", ".join(missing)
            )

        data = collage.create_collage(raw_images, quality=_image_quality(p))
        if burn_enabled:
            burn_text = _image_burnin_text(item_name, _remember_burnin_date(session))
            data = burnin.burn_in_image_bytes(
                data,
                burn_text,
                quality=_image_quality(p),
            )

        final_doc = attachments.save(
            data,
            f"COLLAGE-{session.target_document}-{session.name}.jpg",
            session.target_doctype,
            session.target_document,
            bool(p.private_file),
        )
        if not _verify_attachment(final_doc.name, session.target_doctype, session.target_document):
            frappe.throw("Collage attachment verification failed")

        _remember_final_file(session, final_doc.name)
        cleanup_errors = _cleanup_original_media(rows) if p.delete_originals_after_merge else []
        _complete_image_session(channel, session, rows, cleanup_errors)
    except Exception as exc:
        session.db_set({
            "status": "Failed",
            "current_state": "Failed",
            "error_message": str(exc),
        })
        LineClient(channel).push(
            session.line_user_id,
            [{"type": "text", "text": "แนบภาพไม่สำเร็จ ระบบเก็บไฟล์ต้นฉบับไว้สำหรับ Retry"}],
        )
        raise

