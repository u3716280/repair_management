from __future__ import annotations

import re
from datetime import datetime

import frappe
from frappe.utils import cint, flt, get_datetime, now_datetime

from repair_management.integrations.line.delivery_confirmation.auth import as_integration_user
from repair_management.integrations.line.delivery_confirmation.share import create_image_urls
from repair_management.integrations.line.services import attachments, burnin


MAX_PHOTOS = 8
MIN_PHOTOS = 1
JPEG_QUALITY = 85


def _sales_order(name: str):
    name = (name or "").strip()
    if not name or not frappe.db.exists("Sales Order", name):
        frappe.throw("ไม่พบ Sales Order จาก QR Code", frappe.DoesNotExistError)
    return frappe.get_doc("Sales Order", name)


def _delivery_note_names(sales_order: str) -> list[str]:
    # "Delivery Note Item" is a child table, so frappe.get_list() (permission-
    # checked) has no parent document to check permission against here and
    # throws "Delivery Note Item is not a valid parent DocType for Delivery
    # Note Item". This is only a lookup for candidate parent names -- the
    # actual read permission is enforced afterward on the resolved Delivery
    # Note/Sales Order document, so an unchecked get_all() is correct here.
    return list(
        dict.fromkeys(
            frappe.get_all(
                "Delivery Note Item",
                filters={"against_sales_order": sales_order},
                pluck="parent",
                limit_page_length=0,
            )
        )
    )


def resolve_attachment_target(sales_order: str):
    """Newest non-Completed Delivery Note; fall back to Sales Order.

    Business rule: all Delivery Note states are eligible except Completed.
    Newest means posting_date DESC then posting_time DESC.
    creation DESC is only a deterministic final tie-breaker.
    """
    names = _delivery_note_names(sales_order)
    if names:
        rows = frappe.get_list(
            "Delivery Note",
            filters={
                "name": ["in", names],
                "status": ["!=", "Completed"],
            },
            fields=["name", "status", "posting_date", "posting_time", "creation"],
            order_by="posting_date desc, posting_time desc, creation desc",
            limit_page_length=1,
        )
        if rows:
            row = rows[0]
            return frappe._dict(
                doctype="Delivery Note",
                name=row.name,
                status=row.status,
                posting_date=row.posting_date,
                posting_time=row.posting_time,
            )

    return frappe._dict(
        doctype="Sales Order",
        name=sales_order,
        status=None,
        posting_date=None,
        posting_time=None,
    )


def sales_order_view(auth, sales_order_name: str):
    with as_integration_user(auth.channel):
        doc = _sales_order(sales_order_name)
        doc.check_permission("read")
        target = resolve_attachment_target(doc.name)
        target_doc = frappe.get_doc(target.doctype, target.name)
        target_doc.check_permission("read")
        return {
            "sales_order": doc.name,
            "customer": doc.customer,
            "customer_name": doc.customer_name or doc.customer,
            "transaction_date": doc.transaction_date,
            "delivery_date": doc.delivery_date,
            "status": doc.status,
            "attachment_target": {"doctype": target.doctype, "name": target.name},
        }


def _verify_attachment(file_name: str, doctype: str, docname: str) -> bool:
    values = frappe.db.get_value(
        "File",
        file_name,
        ["attached_to_doctype", "attached_to_name"],
        as_dict=True,
    )
    return bool(values and values.attached_to_doctype == doctype and values.attached_to_name == docname)


def _day_text(value: datetime | None = None) -> str:
    value = value or now_datetime()
    return f"{value.day:02d}"


def _existing_max_image_no(sales_order: str, day_text: str) -> int:
    prefix = f"LINE-POD-{sales_order}-{day_text}-"
    rows = frappe.get_list(
        "File",
        filters={"file_name": ["like", f"{prefix}%.jpg"]},
        fields=["file_name"],
        limit_page_length=0,
    )
    pattern = re.compile(rf"^{re.escape(prefix)}(\d{{2,}})\.jpg$", re.IGNORECASE)
    maximum = 0
    for row in rows:
        match = pattern.match(row.file_name or "")
        if match:
            maximum = max(maximum, int(match.group(1)))
    return maximum


def _location_datetime(value):
    if not value:
        return None
    try:
        return get_datetime(value)
    except Exception:
        return None


def _create_confirmation(auth, so, target, request_id, latitude, longitude, accuracy, location_timestamp):
    doc = frappe.new_doc("Delivery Confirmation")
    doc.status = "Processing"
    doc.request_id = request_id
    doc.sales_order = so.name
    doc.delivery_note = target.name if target.doctype == "Delivery Note" else None
    doc.attachment_doctype = target.doctype
    doc.attachment_name = target.name
    doc.customer = so.customer
    doc.customer_name = so.customer_name or so.customer
    doc.line_recipient = auth.recipient_name
    doc.line_user_id = auth.line_user_id
    if doc.meta.has_field("employee"):
        doc.employee = auth.employee
    doc.confirmation_datetime = now_datetime()
    doc.latitude = flt(latitude)
    doc.longitude = flt(longitude)
    doc.accuracy = flt(accuracy) if accuracy not in (None, "") else None
    doc.location_timestamp = _location_datetime(location_timestamp)
    if doc.meta.has_field("chat_notification_status"):
        doc.chat_notification_status = "Pending"
    doc.insert()
    return doc


def _existing_confirmation(request_id: str):
    if not request_id:
        return None
    name = frappe.db.get_value("Delivery Confirmation", {"request_id": request_id}, "name")
    return frappe.get_doc("Delivery Confirmation", name) if name else None


def _existing_confirmation_response(existing):
    if existing.status == "Confirmed":
        return _confirmation_result(existing)
    if existing.status == "Processing":
        frappe.throw("รายการนี้กำลังประมวลผลอยู่", frappe.ValidationError)
    frappe.throw("request_id นี้เคยประมวลผลไม่สำเร็จ กรุณาลองยืนยันใหม่", frappe.ValidationError)


def _confirmation_files(doc) -> list[dict]:
    first_no = cint(doc.first_image_no)
    last_no = cint(doc.last_image_no)
    if doc.status != "Confirmed" or first_no <= 0 or last_no < first_no:
        return []

    day_text = _day_text(get_datetime(doc.confirmation_datetime))
    expected = {
        f"LINE-POD-{doc.sales_order}-{day_text}-{image_no:02d}.jpg": image_no
        for image_no in range(first_no, last_no + 1)
    }
    rows = frappe.get_list(
        "File",
        filters={
            "attached_to_doctype": doc.attachment_doctype,
            "attached_to_name": doc.attachment_name,
            "file_name": ["in", list(expected)],
        },
        fields=["name", "file_name", "file_url", "is_private"],
        limit_page_length=0,
    )
    result = []
    for row in rows:
        image_no = expected.get(row.file_name)
        if image_no is not None:
            result.append(
                {
                    "image_no": image_no,
                    "file": row.name,
                    "file_name": row.file_name,
                    "file_url": row.file_url,
                    "is_private": cint(row.is_private),
                }
            )
    result.sort(key=lambda row: row["image_no"])
    return result


def confirm(auth, *, sales_order_name: str, request_id: str, latitude, longitude, accuracy=None, location_timestamp=None, photos=None):
    photos = list(photos or [])
    if len(photos) < MIN_PHOTOS or len(photos) > MAX_PHOTOS:
        frappe.throw(f"ต้องมีรูปจำนวน {MIN_PHOTOS}–{MAX_PHOTOS} รูป", frappe.ValidationError)
    if latitude in (None, "") or longitude in (None, ""):
        frappe.throw("ไม่พบพิกัดสำหรับ Proof of Delivery", frappe.ValidationError)
    request_id = (request_id or "").strip()
    if not request_id:
        frappe.throw("Missing request_id", frappe.ValidationError)

    with as_integration_user(auth.channel):
        existing = _existing_confirmation(request_id)
        if existing:
            return _existing_confirmation_response(existing)

        so = _sales_order(sales_order_name)
        so.check_permission("read")
        target = resolve_attachment_target(so.name)
        frappe.get_doc(target.doctype, target.name).check_permission("read")

        if not frappe.has_permission("File", "create"):
            frappe.throw("LINE Integration User ไม่มีสิทธิ์ Create File", frappe.PermissionError)

        lock_key = frappe.cache.make_key(f"line-pod:{so.name}:{_day_text()}")
        with frappe.cache.lock(lock_key, timeout=60, blocking_timeout=15):
            # Re-check for a concurrent submit with the same request_id that was
            # created and completed while this request waited for the lock.
            existing = _existing_confirmation(request_id)
            if existing:
                return _existing_confirmation_response(existing)

            # Re-read source data and attachment target at the actual confirmation moment.
            so = _sales_order(so.name)
            so.check_permission("read")
            target = resolve_attachment_target(so.name)
            frappe.get_doc(target.doctype, target.name).check_permission("read")

            confirmation = _create_confirmation(
                auth,
                so,
                target,
                request_id,
                latitude,
                longitude,
                accuracy,
                location_timestamp,
            )

            day_text = _day_text(confirmation.confirmation_datetime)
            start_no = _existing_max_image_no(so.name, day_text) + 1
            created_files: list[str] = []
            try:
                customer_name = (so.customer_name or so.customer or "").strip()
                for offset, upload in enumerate(photos):
                    raw = upload.stream.read() if getattr(upload, "stream", None) else upload.read()
                    if not raw:
                        frappe.throw("พบไฟล์รูปว่าง", frappe.ValidationError)

                    # No permanent Original File is created. The uploaded bytes exist
                    # only during this request, then the burn-in JPEG becomes the final File.
                    final_bytes = burnin.burn_in_image_bytes(raw, customer_name, quality=JPEG_QUALITY)
                    image_no = start_no + offset
                    file_name = f"LINE-POD-{so.name}-{day_text}-{image_no:02d}.jpg"
                    final_doc = attachments.save(
                        final_bytes,
                        file_name,
                        target.doctype,
                        target.name,
                        True,
                    )
                    created_files.append(final_doc.name)
                    if not _verify_attachment(final_doc.name, target.doctype, target.name):
                        frappe.throw(f"Attachment verification failed: {file_name}")

                values = {
                    "photo_count": len(created_files),
                    "first_image_no": start_no,
                    "last_image_no": start_no + len(created_files) - 1,
                    "status": "Confirmed",
                }
                if confirmation.meta.has_field("chat_notification_status"):
                    values["chat_notification_status"] = "Pending"
                    values["chat_notification_error"] = None
                    values["chat_notified_at"] = None
                confirmation.db_set(values, update_modified=True)
                return _confirmation_result(frappe.get_doc("Delivery Confirmation", confirmation.name))
            except Exception:
                # Remove partial final attachments. Since no Original File is persisted,
                # retry starts clean and can safely reuse the filenames.
                for file_name in reversed(created_files):
                    try:
                        if frappe.db.exists("File", file_name):
                            frappe.delete_doc("File", file_name)
                    except Exception:
                        frappe.log_error(
                            title=f"POD cleanup failed: {file_name}",
                            message=frappe.get_traceback(),
                        )
                confirmation.db_set("status", "Failed", update_modified=True)
                raise


def report_chat_notification(auth, confirmation_name: str, status: str, error: str | None = None):
    status = (status or "").strip().title()
    if status not in ("Sent", "Failed"):
        frappe.throw("Invalid chat notification status", frappe.ValidationError)

    with as_integration_user(auth.channel):
        if not frappe.db.exists("Delivery Confirmation", confirmation_name):
            frappe.throw("ไม่พบ Delivery Confirmation", frappe.DoesNotExistError)
        doc = frappe.get_doc("Delivery Confirmation", confirmation_name)
        if doc.line_recipient != auth.recipient_name:
            frappe.throw("ไม่มีสิทธิ์อัปเดต POD นี้", frappe.PermissionError)
        if doc.status != "Confirmed":
            frappe.throw("POD ยังไม่ Confirmed", frappe.ValidationError)

        values = {}
        if doc.meta.has_field("chat_notification_status"):
            values["chat_notification_status"] = status
        if doc.meta.has_field("chat_notification_error"):
            values["chat_notification_error"] = (error or "")[:2000] if status == "Failed" else None
        if doc.meta.has_field("chat_notified_at"):
            values["chat_notified_at"] = now_datetime() if status == "Sent" else None
        if values:
            doc.db_set(values, update_modified=True)
        return {"confirmation": doc.name, "status": status}


def _confirmation_result(doc):
    files = _confirmation_files(doc)
    chat_images = []
    if doc.status == "Confirmed":
        for row in files:
            urls = create_image_urls(doc.name, row["file"])
            chat_images.append(
                {
                    "image_no": row["image_no"],
                    "file_name": row["file_name"],
                    **urls,
                }
            )

    return {
        "confirmation": doc.name,
        "status": doc.status,
        "sales_order": doc.sales_order,
        "delivery_note": doc.delivery_note,
        "attachment_target": {"doctype": doc.attachment_doctype, "name": doc.attachment_name},
        "customer_name": doc.customer_name,
        "confirmation_datetime": doc.confirmation_datetime,
        "photo_count": cint(doc.photo_count),
        "latitude": doc.latitude,
        "longitude": doc.longitude,
        "accuracy": doc.accuracy,
        "chat_images": chat_images,
        "chat_text": f"[POD] ยืนยันการจัดส่ง {doc.sales_order} เรียบร้อยแล้ว",
        "chat_notification_status": getattr(doc, "chat_notification_status", None),
    }
