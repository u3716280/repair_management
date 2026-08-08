import frappe


def apply():
    return check()


def check():
    profile = frappe.db.get_value(
        "LINE Document Media Upload Profile",
        {"action_key": "video_confirm"},
        [
            "name",
            "action_key",
            "target_doctype",
            "media_type",
            "minimum_files",
            "maximum_files",
        ],
        as_dict=True,
    )
    return {
        "status": "ready" if profile else "profile_not_found",
        "runtime": "v1.6.3.1",
        "video_profile": profile,
        "expected_prompt_buttons": ["เปิดกล้อง", "แนบ VDO", "ยกเลิก"],
        "note": (
            "Hotfix for v1.6.3 diagnostic. "
            "Uses the correct DocType: LINE Document Media Upload Profile."
        ),
    }
