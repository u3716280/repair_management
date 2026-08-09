
import frappe

from repair_management.integrations.line.services import burnin


def apply():
    return check()


def check():
    profiles = frappe.get_all(
        "LINE Document Media Upload Profile",
        filters={"action_key": ["in", ["parts_confirm", "video_confirm"]]},
        fields=[
            "name", "action_key", "target_doctype", "media_type",
            "minimum_files", "maximum_files",
            "single_image_mode", "delete_originals_after_merge",
        ],
        order_by="action_key asc",
    )
    environment = burnin.environment_check()
    return {
        "status": "ready",
        "runtime": "v1.7.1",
        "profiles": profiles,
        "collage": {
            "max_images": 8,
            "max_per_row": 2,
            "odd_last_row": "centered",
            "legacy_layout_removed": ["3+2", "4+3", "4x2"],
            "preserve_detail_priority": True,
            "forced_crop": False,
        },
        "image_burn_in": {
            "content": "Item Name + Date",
            "stage": "final image only",
            "single_image": True,
            "collage": True,
            "font": "Garuda Regular",
        },
        "environment": environment,
    }
