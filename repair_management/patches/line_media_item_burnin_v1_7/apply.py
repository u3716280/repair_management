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
        "runtime": "v1.7",
        "profiles": profiles,
        "states": [
            "Selecting Document",
            "Selecting Item",
            "Selecting Burn-in",
            "Waiting Media",
            "Finalizing",
            "Completed",
        ],
        "burn_in": {
            "content": "Item Name only",
            "font": "Garuda Regular",
            "image_engine": "Pillow",
            "video_engine": "FFmpeg",
            "video_codec": "libx264",
            "preset": "ultrafast",
            "crf": 28,
            "audio": "copy",
            "queue": "long",
        },
        "environment": environment,
    }
