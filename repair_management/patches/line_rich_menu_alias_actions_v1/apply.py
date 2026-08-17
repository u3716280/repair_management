from __future__ import annotations

import frappe


ACTION_TYPES = [
    "Postback",
    "Message",
    "URI",
    "Datetime Picker",
    "Rich Menu Switch",
    "Clipboard",
    "Camera",
    "Camera Roll",
    "Location",
]


def apply():
    """Normalize legacy CameraRoll values without deleting or recreating records."""
    if not frappe.db.table_exists("LINE Rich Menu Area"):
        return {"status": "skipped", "reason": "LINE Rich Menu Area table not found"}

    legacy_rows = frappe.get_all(
        "LINE Rich Menu Area",
        filters={"action_type": "CameraRoll"},
        fields=["name", "uri", "camera_roll_mode"],
    )

    for row in legacy_rows:
        uri = (row.uri or "").strip()
        mode = (row.camera_roll_mode or "").strip()

        if uri.endswith("/cameraRoll/single"):
            mode = "Single"
        elif uri.endswith("/cameraRoll/multi"):
            mode = "Multi"
        elif mode not in {"Single", "Multi"}:
            mode = "Multi"

        frappe.db.set_value(
            "LINE Rich Menu Area",
            row.name,
            {
                "action_type": "Camera Roll",
                "camera_roll_mode": mode,
            },
            update_modified=False,
        )

    if legacy_rows:
        frappe.db.commit()

    return {
        "status": "ok",
        "camera_roll_rows_normalized": len(legacy_rows),
    }


def check():
    area_meta = frappe.get_meta("LINE Rich Menu Area")
    definition_meta = frappe.get_meta("LINE Rich Menu Definition")

    action_field = area_meta.get_field("action_type")
    options = [
        value.strip()
        for value in (action_field.options or "").splitlines()
        if value.strip()
    ]

    expected_fields = {
        "datetime_picker_data",
        "datetime_picker_mode",
        "datetime_picker_initial",
        "datetime_picker_min",
        "datetime_picker_max",
        "target_rich_menu",
        "switch_data",
        "clipboard_text",
        "camera_roll_mode",
    }
    missing_fields = sorted(
        fieldname
        for fieldname in expected_fields
        if not area_meta.has_field(fieldname)
    )

    result = {
        "status": "ready",
        "action_types": options,
        "expected_action_types": ACTION_TYPES,
        "action_types_match": options == ACTION_TYPES,
        "alias_field_present": bool(definition_meta.has_field("alias_id")),
        "missing_area_fields": missing_fields,
        "legacy_camera_roll_rows": frappe.db.count(
            "LINE Rich Menu Area",
            {"action_type": "CameraRoll"},
        ),
    }

    if (
        not result["action_types_match"]
        or not result["alias_field_present"]
        or result["missing_area_fields"]
        or result["legacy_camera_roll_rows"]
    ):
        result["status"] = "check_failed"

    return result
