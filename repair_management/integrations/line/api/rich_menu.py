from __future__ import annotations

import hashlib
import json
import re

import frappe
from frappe import _
from frappe.utils import now_datetime

from repair_management.integrations.line.api.client import LineClient
from repair_management.integrations.line.utils.files import resolve_file_path


CAMERA_URI = "https://line.me/R/nv/camera/"
CAMERA_ROLL_SINGLE_URI = "https://line.me/R/nv/cameraRoll/single"
CAMERA_ROLL_MULTI_URI = "https://line.me/R/nv/cameraRoll/multi"
LOCATION_URI = "https://line.me/R/nv/location/"

_DATETIME_PATTERNS = {
    "date": re.compile(r"^\d{4}-\d{2}-\d{2}$"),
    "time": re.compile(r"^\d{2}:\d{2}$"),
    "datetime": re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$"),
}


def _required_action_data(value, action_key=None, label="Action Data"):
    data = (value or "").strip()
    if not data and action_key:
        data = f"action={str(action_key).strip()}"
    if not data:
        frappe.throw(_("{0} is required.").format(label))
    if len(data) > 300:
        frappe.throw(_("{0} must not exceed 300 characters.").format(label))
    return data


def _validate_datetime_value(value, mode, field_label):
    if not value:
        return
    pattern = _DATETIME_PATTERNS[mode]
    if not pattern.fullmatch(value):
        formats = {
            "date": "YYYY-MM-DD",
            "time": "HH:mm",
            "datetime": "YYYY-MM-DDTHH:mm",
        }
        frappe.throw(
            _("{0} must use {1} format for mode {2}.").format(
                field_label,
                formats[mode],
                mode,
            )
        )


def _resolve_switch_target(source_doc, area):
    target_name = (area.target_rich_menu or "").strip()
    if not target_name:
        frappe.throw(
            _("Target Rich Menu is required for area {0}.").format(area.area_label)
        )

    target = frappe.db.get_value(
        "LINE Rich Menu Definition",
        target_name,
        ["name", "line_channel", "scope", "alias_id"],
        as_dict=True,
    )
    if not target:
        frappe.throw(
            _("Target Rich Menu {0} does not exist.").format(
                frappe.bold(target_name)
            )
        )

    if target.line_channel != source_doc.line_channel:
        frappe.throw(
            _("Rich Menu Switch target must use the same LINE Channel as the source menu.")
        )

    alias_id = (target.alias_id or "").strip()
    if not alias_id:
        frappe.throw(
            _("Target Rich Menu {0} must have an Alias ID before it can be used by Rich Menu Switch.").format(
                frappe.bold(target_name)
            )
        )

    return alias_id


def _build_action(source_doc, area):
    action_type = (area.action_type or "").strip()
    label = area.area_label

    if action_type == "Postback":
        action = {
            "type": "postback",
            "label": label,
            "data": _required_action_data(
                area.postback_data,
                area.action_key,
                "Postback Data",
            ),
        }
        if area.display_text:
            action["displayText"] = area.display_text
        if area.input_option:
            action["inputOption"] = area.input_option
            if area.input_option == "openKeyboard" and area.fill_in_text:
                action["fillInText"] = area.fill_in_text
        return action

    if action_type == "Message":
        return {
            "type": "message",
            "label": label,
            "text": area.message_text or label,
        }

    if action_type == "URI":
        uri = (area.uri or "").strip()
        if not uri:
            frappe.throw(_("URI is required for area {0}.").format(label))
        return {"type": "uri", "label": label, "uri": uri}

    if action_type == "Datetime Picker":
        mode = (area.datetime_picker_mode or "date").strip()
        if mode not in _DATETIME_PATTERNS:
            frappe.throw(_("Invalid Datetime Picker Mode: {0}").format(mode))

        action = {
            "type": "datetimepicker",
            "label": label,
            "data": _required_action_data(
                area.datetime_picker_data,
                area.action_key,
                "Datetime Picker Data",
            ),
            "mode": mode,
        }

        optional_values = (
            ("initial", area.datetime_picker_initial, "Initial"),
            ("min", area.datetime_picker_min, "Min"),
            ("max", area.datetime_picker_max, "Max"),
        )
        for key, value, field_label in optional_values:
            value = (value or "").strip()
            if value:
                _validate_datetime_value(value, mode, field_label)
                action[key] = value

        if action.get("min") and action.get("max") and action["min"] > action["max"]:
            frappe.throw(_("Datetime Picker Min must be less than Max."))

        return action

    if action_type == "Rich Menu Switch":
        alias_id = _resolve_switch_target(source_doc, area)
        data = (area.switch_data or "").strip()
        if not data:
            data = f"action=richmenu_switch&menu={alias_id}"
        if len(data) > 300:
            frappe.throw(_("Switch Data must not exceed 300 characters."))
        return {
            "type": "richmenuswitch",
            "label": label,
            "richMenuAliasId": alias_id,
            "data": data,
        }

    if action_type == "Clipboard":
        clipboard_text = area.clipboard_text or ""
        if not clipboard_text:
            frappe.throw(_("Clipboard Text is required for area {0}.").format(label))
        if len(clipboard_text) > 1000:
            frappe.throw(_("Clipboard Text must not exceed 1000 characters."))
        return {
            "type": "clipboard",
            "label": label,
            "clipboardText": clipboard_text,
        }

    if action_type == "Camera":
        return {
            "type": "uri",
            "label": label,
            "uri": CAMERA_URI,
        }

    # CameraRoll is retained as a runtime compatibility alias for existing
    # rows created before the UI label was normalized to "Camera Roll".
    if action_type in {"Camera Roll", "CameraRoll"}:
        mode = (area.camera_roll_mode or "Multi").strip().lower()
        if mode == "single":
            uri = CAMERA_ROLL_SINGLE_URI
        elif mode == "multi":
            uri = CAMERA_ROLL_MULTI_URI
        else:
            frappe.throw(_("Camera Roll Selection Mode must be Single or Multi."))
        return {
            "type": "uri",
            "label": label,
            "uri": uri,
        }

    if action_type == "Location":
        return {
            "type": "uri",
            "label": label,
            "uri": LOCATION_URI,
        }

    frappe.throw(_("Unsupported Rich Menu Action Type: {0}").format(action_type))


def build_payload(doc):
    areas = []

    enabled_areas = [area for area in doc.areas if area.enabled]
    enabled_areas = sorted(
        enabled_areas,
        key=lambda area: area.sort_order or area.idx,
    )

    for area in enabled_areas:
        if area.x + area.width > doc.width or area.y + area.height > doc.height:
            frappe.throw(f"Area {area.idx} exceeds menu bounds")

        action = _build_action(doc, area)
        areas.append(
            {
                "bounds": {
                    "x": int(area.x),
                    "y": int(area.y),
                    "width": int(area.width),
                    "height": int(area.height),
                },
                "action": action,
            }
        )

    if not areas:
        frappe.throw("At least one enabled area is required")

    return {
        "size": {
            "width": int(doc.width),
            "height": int(doc.height),
        },
        "selected": bool(doc.selected),
        "name": doc.menu_name,
        "chatBarText": doc.chat_bar_text,
        "areas": areas,
    }


@frappe.whitelist()
def validate_draft(definition_name):
    return build_payload(
        frappe.get_doc("LINE Rich Menu Definition", definition_name)
    )


@frappe.whitelist()
def deploy(definition_name):
    doc = frappe.get_doc("LINE Rich Menu Definition", definition_name)
    payload = build_payload(doc)
    path = resolve_file_path(doc.rich_menu_image)
    image = path.read_bytes()
    text = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    version = (
        frappe.db.count(
            "LINE Rich Menu Deployment",
            {"rich_menu_definition": doc.name},
        )
        + 1
    )

    deployment = frappe.get_doc(
        {
            "doctype": "LINE Rich Menu Deployment",
            "line_channel": doc.line_channel,
            "rich_menu_definition": doc.name,
            "version": version,
            "scope": doc.scope,
            "payload_snapshot": text,
            "image_snapshot": doc.rich_menu_image,
            "payload_sha256": hashlib.sha256(text.encode()).hexdigest(),
            "image_sha256": hashlib.sha256(image).hexdigest(),
            "deployment_status": "Validated",
        }
    ).insert()

    client = LineClient(doc.line_channel)
    alias_sync = None

    try:
        rich_menu_id = client.create_rich_menu(payload)
        deployment.db_set(
            {
                "line_rich_menu_id": rich_menu_id,
                "deployment_status": "Created",
            }
        )

        client.upload_image(
            rich_menu_id,
            image,
            path.name,
        )
        deployment.db_set("deployment_status", "Image Uploaded")

        # Alias can only be created/updated after the Rich Menu exists and
        # its image has been uploaded. This changes navigation mapping only;
        # it deliberately does not touch per-user assignment/re-link logic.
        if doc.alias_id:
            alias_sync = client.upsert_rich_menu_alias(
                doc.alias_id,
                rich_menu_id,
            )

        if doc.scope == "Default":
            client.set_default(rich_menu_id)

        deployment.db_set(
            {
                "deployment_status": "Active",
                "activated_at": now_datetime(),
            }
        )
        doc.db_set("current_active_deployment", deployment.name)

        return {
            "deployment": deployment.name,
            "rich_menu_id": rich_menu_id,
            "alias_id": doc.alias_id or None,
            "alias_sync": alias_sync,
        }
    except Exception as exc:
        deployment.db_set(
            {
                "deployment_status": "Failed",
                "error_response": str(exc),
            }
        )
        raise


@frappe.whitelist()
def sync_recipient(assignment_name):
    assignment = frappe.get_doc(
        "LINE Rich Menu Recipient Assignment",
        assignment_name,
    )
    client = LineClient(assignment.line_channel)
    deployment_name = assignment.direct_deployment_override or (
        assignment.audience
        and frappe.db.get_value(
            "LINE Rich Menu Audience",
            assignment.audience,
            "active_deployment",
        )
    )

    if not assignment.enabled or not deployment_name:
        client.unlink_user(assignment.line_user_id)
        assignment.db_set("sync_status", "Unlinked")
        return {"status": "Unlinked"}

    deployment = frappe.get_doc(
        "LINE Rich Menu Deployment",
        deployment_name,
    )
    client.link_user(
        assignment.line_user_id,
        deployment.line_rich_menu_id,
    )
    actual = client.get_user_menu(assignment.line_user_id)
    status = (
        "Verified"
        if actual == deployment.line_rich_menu_id
        else "Mismatch"
    )
    assignment.db_set(
        {
            "desired_rich_menu_id": deployment.line_rich_menu_id,
            "actual_rich_menu_id": actual,
            "sync_status": status,
            "last_verified_at": now_datetime(),
        }
    )
    return {"status": status}
