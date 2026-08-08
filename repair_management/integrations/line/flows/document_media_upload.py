import math
import mimetypes
from urllib.parse import urlencode

import frappe
from frappe.utils import now_datetime

from repair_management.integrations.line.api.client import LineClient
from repair_management.integrations.line.flows.base import create_session, context, set_context
from repair_management.integrations.line.services import attachments, collage, document_search
from repair_management.integrations.line.utils.files import resolve_file_path


SELECTING = "Selecting Document"
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

    session.db_set({"target_document": document_name, "current_state": WAITING_MEDIA})
    selected = document_search.get_candidates(p, [document_name])
    display = selected[0]["title"] if selected else document_name

    if p.media_type == "Image":
        message = {
            "type": "text",
            "text": f"เลือกเอกสารแล้ว\n{display}\n\nกรุณาถ่ายรูปหรือเลือกรูปจากเครื่อง (1–{int(p.maximum_files or 8)} รูป)",
            "quickReply": {
                "items": [
                    {"type": "action", "action": {"type": "camera", "label": "ถ่ายรูป"}},
                    {"type": "action", "action": {"type": "cameraRoll", "label": "เลือกรูป"}},
                    {"type": "action", "action": {"type": "postback", "label": "เสร็จสิ้น", "displayText": "เสร็จสิ้นการส่งรูป", "data": _postback("media_finish", session=session.name)}},
                    {"type": "action", "action": {"type": "postback", "label": "ยกเลิก", "displayText": "ยกเลิก", "data": _postback("media_cancel", session=session.name)}},
                ]
            },
        }
    else:
        message = _video_prompt_message(session, display=display)
    LineClient(channel).reply(reply_token, [message])


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
    # v1.6+ intentionally does not accept a typed document number for document selection.
    if session.current_state == SELECTING:
        p = _session_profile(session)
        LineClient(channel).reply(reply_token, [
            {"type": "text", "text": "กรุณาเลือกเอกสารจากรายการ"},
            _selection_message(session, p, context(session).get("page", 1)),
        ])
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
    frappe.get_doc({
        "doctype": "LINE Media File",
        "flow_session": session.name,
        "line_message_id": message["id"],
        "image_set_id": image_set.get("id"),
        "image_index": image_set.get("index") if image_set.get("index") is not None else sequence,
        "media_type": p.media_type,
        "temporary_file": file_doc.name,
        "processing_status": "Downloaded",
    }).insert()
    # Recount from LINE Media File instead of incrementing the in-memory session value.
    # This is safer when multiple image events are queued close together.
    count = frappe.db.count(
        "LINE Media File",
        {"flow_session": session.name, "processing_status": "Downloaded"},
    )
    session.db_set("received_files", count)

    if p.media_type == "Video":
        attachments.relink(file_doc.name, session.target_doctype, session.target_document)
        session.db_set({"status": "Completed", "current_state": "Completed"})
        LineClient(channel).push(session.line_user_id, [{"type": "text", "text": "แนบ VDO สำเร็จ"}])
        return

    maximum = int(p.maximum_files or 8)
    if count >= maximum:
        # At the maximum there is no reason to wait for a Finish postback.
        # Queue finalization only after this download transaction commits.
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
        # LINE quick replies disappear after the user sends an image. Re-issue them
        # after every successful download so the user can add more or finalize.
        LineClient(channel).push(session.line_user_id, [_image_continue_message(session, p, count)])



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
    if not session.target_doctype or not session.target_document:
        session.db_set({"status": "Failed", "current_state": "Failed", "error_message": "Missing target document"})
        return
    if not document_search.is_eligible(p, session.target_document):
        session.db_set({"status": "Failed", "current_state": "Failed", "error_message": "Target document is no longer eligible"})
        LineClient(channel).push(session.line_user_id, [{"type": "text", "text": "เอกสารที่เลือกไม่อยู่ในสถานะที่อนุญาตแล้ว จึงยังไม่ได้แนบรูป"}])
        return

    rows = frappe.get_all(
        "LINE Media File",
        filters={"flow_session": session.name, "media_type": "Image", "processing_status": ["in", ["Downloaded", "Finalized"]]},
        fields=["name", "temporary_file", "image_index", "processing_status"],
        order_by="image_index asc",
    )
    try:
        if not rows:
            frappe.throw("No image files found for this LINE Flow Session")

        # Idempotency/recovery: a previous attempt may already have attached the
        # collage before failing during original-file cleanup.
        existing = _find_existing_collage(session)
        if len(rows) > 1 and existing:
            cleanup_errors = _cleanup_original_media(rows) if p.delete_originals_after_merge else []
            _complete_image_session(channel, session, rows, cleanup_errors)
            return

        if len(rows) == 1 and p.single_image_mode == "Attach Directly":
            row = rows[0]
            if row.temporary_file and frappe.db.exists("File", row.temporary_file):
                attachments.relink(row.temporary_file, session.target_doctype, session.target_document)
                frappe.db.set_value(
                    "LINE Media File",
                    row.name,
                    {"processing_status": "Finalized"},
                    update_modified=False,
                )
                _complete_image_session(channel, session, rows)
                return
            frappe.throw("Original image File is missing and no final attachment exists")

        # Multi-image path. Read all originals before creating the final file.
        raw_images = []
        missing = []
        for row in rows:
            if not row.temporary_file or not frappe.db.exists("File", row.temporary_file):
                missing.append(row.name)
                continue
            fdoc = frappe.get_doc("File", row.temporary_file)
            path = resolve_file_path(fdoc.file_url)
            try:
                raw_images.append(path.read_bytes())
            except FileNotFoundError:
                missing.append(row.name)

        if missing:
            # A prior failed transaction can leave the generated collage on disk
            # while some originals were already removed. Recover that artifact.
            recovered = _recover_physical_collage(session, p)
            if recovered:
                cleanup_errors = _cleanup_original_media(rows) if p.delete_originals_after_merge else []
                _complete_image_session(channel, session, rows, cleanup_errors)
                return
            frappe.throw(
                "Missing original image files and no recoverable collage was found: "
                + ", ".join(missing)
            )

        data = collage.create_collage(raw_images)
        attachments.save(
            data,
            f"COLLAGE-{session.target_document}-{now_datetime().strftime('%Y%m%d-%H%M%S')}.jpg",
            session.target_doctype,
            session.target_document,
            bool(p.private_file),
        )

        # Final attachment exists now. Only after this point may originals be removed.
        cleanup_errors = _cleanup_original_media(rows) if p.delete_originals_after_merge else []
        _complete_image_session(channel, session, rows, cleanup_errors)
    except Exception as exc:
        session.db_set({"status": "Failed", "current_state": "Failed", "error_message": str(exc)})
        LineClient(channel).push(session.line_user_id, [{"type": "text", "text": "แนบภาพไม่สำเร็จ ระบบเก็บข้อมูลไว้สำหรับ Retry"}])
        raise

