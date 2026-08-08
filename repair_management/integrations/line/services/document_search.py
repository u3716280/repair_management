import json

import frappe


SPECIAL_FIELDS = {"name", "docstatus"}


def _valid_fields(doctype):
    meta = frappe.get_meta(doctype)
    return SPECIAL_FIELDS | {df.fieldname for df in meta.fields if df.fieldname}


def _normalize_filter_value(operator, value):
    operator = (operator or "=").strip().lower()
    if operator not in {"in", "not in"}:
        return value

    if isinstance(value, (list, tuple, set)):
        return list(value)

    text = str(value or "").strip()
    if not text:
        return []

    if text.startswith("["):
        try:
            parsed = json.loads(text)
            if isinstance(parsed, list):
                return parsed
        except Exception:
            pass

    return [part.strip() for part in text.split(",") if part.strip()]


def _filters(profile):
    doctype = profile.target_doctype
    valid = _valid_fields(doctype)
    filters = []
    for row in profile.document_filters:
        if row.fieldname not in valid:
            continue
        operator = (row.operator or "=").strip().lower()
        filters.append([
            doctype,
            row.fieldname,
            operator,
            _normalize_filter_value(operator, row.value),
        ])
    return filters


def _display_fields(profile):
    valid = _valid_fields(profile.target_doctype)
    return [row.fieldname for row in profile.display_fields if row.fieldname in valid]


def _search_fields(profile):
    valid = _valid_fields(profile.target_doctype)
    fields = [row.fieldname for row in profile.search_fields if row.fieldname in valid]
    return fields or ["name"]


def _row_to_result(profile, row):
    meta = frappe.get_meta(profile.target_doctype)
    valid = _valid_fields(profile.target_doctype)
    title_field = profile.title_field if profile.title_field in valid else None
    title_value = row.get(title_field) if title_field else None
    details = []
    for fieldname in _display_fields(profile):
        value = row.get(fieldname)
        if value in (None, ""):
            continue
        df = meta.get_field(fieldname)
        label = df.label if df else fieldname
        details.append({"fieldname": fieldname, "label": label, "value": str(value)})

    return {
        "name": row.name,
        "title": f"{row.name} — {title_value or profile.target_doctype}",
        "subtitle": str(title_value or ""),
        "details": details,
    }


def list_candidates(profile, limit=100):
    """Return eligible target documents without requiring a typed keyword."""
    fields = list(dict.fromkeys(["name", *_display_fields(profile), profile.title_field or "name"]))
    fields = [fieldname for fieldname in fields if fieldname in _valid_fields(profile.target_doctype)]
    rows = frappe.get_all(
        profile.target_doctype,
        filters=_filters(profile),
        fields=fields,
        limit=min(max(int(limit or 100), 1), 500),
        order_by=profile.order_by or "modified desc",
    )
    return [_row_to_result(profile, row) for row in rows]


def get_candidates(profile, names):
    """Reload named candidates for display. Eligibility is not implied; select() revalidates."""
    if not names:
        return []
    fields = list(dict.fromkeys(["name", *_display_fields(profile), profile.title_field or "name"]))
    fields = [fieldname for fieldname in fields if fieldname in _valid_fields(profile.target_doctype)]
    rows = frappe.get_all(
        profile.target_doctype,
        filters={"name": ["in", list(names)]},
        fields=fields,
        limit=len(names),
    )
    by_name = {row.name: row for row in rows}
    return [_row_to_result(profile, by_name[name]) for name in names if name in by_name]


def is_eligible(profile, document_name):
    """Revalidate the selected document against the current ERPNext database."""
    if not document_name or not frappe.db.exists(profile.target_doctype, document_name):
        return False
    filters = [[profile.target_doctype, "name", "=", document_name], *_filters(profile)]
    return bool(
        frappe.get_all(
            profile.target_doctype,
            filters=filters,
            pluck="name",
            limit=1,
        )
    )


def search(profile, keyword):
    """Legacy keyword search retained for compatibility with any other profile."""
    doctype = profile.target_doctype
    fields = list(dict.fromkeys(["name", *_display_fields(profile), profile.title_field or "name"]))
    fields = [fieldname for fieldname in fields if fieldname in _valid_fields(doctype)]
    or_filters = [[doctype, fieldname, "like", f"%{keyword}%"] for fieldname in _search_fields(profile)]
    rows = frappe.get_all(
        doctype,
        filters=_filters(profile),
        or_filters=or_filters,
        fields=fields,
        limit=int(profile.maximum_results or 10),
        order_by=profile.order_by or "modified desc",
    )
    return [_row_to_result(profile, row) for row in rows]
