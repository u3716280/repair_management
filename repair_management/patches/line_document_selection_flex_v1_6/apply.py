import frappe


ACTIONS = ("parts_confirm", "video_confirm")
DISPLAY_FIELDS = ("customer_name", "transaction_date", "delivery_date", "status")


def _profiles():
    return frappe.get_all(
        "LINE Document Media Upload Profile",
        filters={"action_key": ["in", list(ACTIONS)]},
        pluck="name",
        order_by="action_key asc",
    )


def _ensure_filter(profile, fieldname, operator, value):
    for row in profile.document_filters:
        if row.fieldname == fieldname:
            row.operator = operator
            row.value = value
            return
    profile.append("document_filters", {"fieldname": fieldname, "operator": operator, "value": value})


def _ensure_display_fields(profile):
    existing = {row.fieldname for row in profile.display_fields}
    valid = {"name", "docstatus", *[df.fieldname for df in frappe.get_meta(profile.target_doctype).fields]}
    for fieldname in DISPLAY_FIELDS:
        if fieldname in valid and fieldname not in existing:
            profile.append("display_fields", {"fieldname": fieldname})


def apply():
    names = _profiles()
    if not names:
        frappe.throw("No LINE Document Media Upload Profile found for parts_confirm/video_confirm")

    changed = []
    for name in names:
        p = frappe.get_doc("LINE Document Media Upload Profile", name)
        p.target_doctype = "Sales Order"
        p.title_field = "customer_name"
        p.order_by = "transaction_date desc, modified desc"
        p.maximum_results = min(max(int(p.maximum_results or 10), 1), 10)
        if p.action_key == "parts_confirm":
            p.media_type = "Image"
            p.minimum_files = 1
            p.maximum_files = 8
            p.create_collage = "Auto"
            p.single_image_mode = "Attach Directly"
            p.delete_originals_after_merge = 1
        elif p.action_key == "video_confirm":
            p.media_type = "Video"
            p.minimum_files = 1
            p.maximum_files = 1
            p.create_collage = "Never"
            p.delete_originals_after_merge = 0

        _ensure_filter(p, "docstatus", "=", "1")
        _ensure_filter(p, "status", "not in", "Completed,Closed,Cancelled")
        _ensure_display_fields(p)
        p.save(ignore_permissions=True)
        changed.append(p.name)

    frappe.db.commit()
    return {"status": "patched", "profiles": changed}


def check():
    result = []
    for name in _profiles():
        p = frappe.get_doc("LINE Document Media Upload Profile", name)
        result.append({
            "name": p.name,
            "action_key": p.action_key,
            "target_doctype": p.target_doctype,
            "media_type": p.media_type,
            "maximum_results": p.maximum_results,
            "minimum_files": p.minimum_files,
            "maximum_files": p.maximum_files,
            "filters": [
                {"fieldname": row.fieldname, "operator": row.operator, "value": row.value}
                for row in p.document_filters
            ],
            "display_fields": [row.fieldname for row in p.display_fields],
        })
    return {"profiles": result}
