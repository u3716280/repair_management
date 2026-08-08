import frappe


def apply():
    return check()


def check():
    profile = frappe.db.get_value(
        "LINE Media Upload Profile",
        {"action_key": "video_confirm"},
        [
            "name", "action_key", "target_doctype", "media_type",
            "minimum_files", "maximum_files",
        ],
        as_dict=True,
    )
    return {
        "status": "ready",
        "runtime": "v1.6.3",
        "video_profile": profile,
        "expected_prompt_buttons": ["เปิดกล้อง", "แนบ VDO", "ยกเลิก"],
        "note": "LINE Messaging API has no dedicated video-picker quick-reply action; แนบ VDO provides in-chat instructions while the webhook still accepts only message.type=video.",
    }
