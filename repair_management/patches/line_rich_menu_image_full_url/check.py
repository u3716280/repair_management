from __future__ import annotations

from pathlib import Path

import frappe


def _paths() -> tuple[Path, Path]:
    package_root = Path(frappe.get_app_path("repair_management"))
    integration_root = package_root / "integrations" / "line_sales_order_upload"
    return integration_root / "utils.py", integration_root / "rich_menu_payload.py"


def check(rich_menu: str = "Default Rich Menu") -> dict:
    utils_path, payload_path = _paths()
    utils_text = utils_path.read_text(encoding="utf-8") if utils_path.exists() else ""
    payload_text = payload_path.read_text(encoding="utf-8") if payload_path.exists() else ""

    result = {
        "utils_file": str(utils_path),
        "payload_file": str(payload_path),
        "utils_patched": all(
            token in utils_text
            for token in (
                "BEGIN PATCH: line_rich_menu_image_full_url",
                "def public_file_url(file_reference: str)",
                "def site_file_path(file_url: str)",
            )
        ),
        "payload_patched": all(
            token in payload_text
            for token in (
                "from .utils import public_file_url, site_file_path",
                "image_url = public_file_url(image_reference)",
            )
        ),
        "google_redirect_base_url": frappe.conf.get("google_redirect_base_url"),
    }

    try:
        from repair_management.integrations.line_sales_order_upload.utils import public_file_url, site_file_path

        sample_relative = "/files/EakThai_Default_RichMenu_2500x1686.jpg"
        sample_full = public_file_url(sample_relative)
        sample_path = site_file_path(sample_full)
        result.update(
            {
                "sample_relative_url": sample_relative,
                "sample_full_url": sample_full,
                "sample_resolved_path": str(sample_path),
                "sample_path_exists": sample_path.exists(),
            }
        )
    except Exception as exc:
        result["resolver_error"] = str(exc)

    if frappe.db.exists("LINE Rich Menu", rich_menu):
        doc = frappe.get_doc("LINE Rich Menu", rich_menu)
        result["rich_menu"] = rich_menu
        result["stored_image_reference"] = doc.image
        if doc.image:
            try:
                from repair_management.integrations.line_sales_order_upload.rich_menu_payload import image_path
                from repair_management.integrations.line_sales_order_upload.utils import public_file_url

                result["resolved_full_url"] = public_file_url(doc.image)
                resolved = image_path(doc)
                result["resolved_physical_path"] = str(resolved)
                result["resolved_file_exists"] = resolved.exists()
                result["resolved_file_size"] = resolved.stat().st_size if resolved.exists() else 0
            except Exception as exc:
                result["rich_menu_image_error"] = str(exc)
    else:
        result["rich_menu"] = None
        result["rich_menu_note"] = f"LINE Rich Menu not found: {rich_menu}"

    result["is_fully_patched"] = bool(result["utils_patched"] and result["payload_patched"])
    return result
