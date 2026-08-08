from __future__ import annotations

from pathlib import Path

import frappe


def check() -> dict:
    package_root = Path(frappe.get_app_path("repair_management"))
    settings_path = package_root / "integrations" / "line_sales_order_upload" / "settings.py"
    diagnostics_path = package_root / "integrations" / "line_sales_order_upload" / "diagnostics.py"

    settings_text = settings_path.read_text(encoding="utf-8") if settings_path.exists() else ""
    diagnostics_text = diagnostics_path.read_text(encoding="utf-8") if diagnostics_path.exists() else ""

    settings_patched = all(
        token in settings_text
        for token in (
            "BEGIN PATCH: line_public_base_url",
            "def get_public_base_url_info()",
            "def get_webhook_url()",
        )
    )
    diagnostics_patched = all(
        token in diagnostics_text
        for token in (
            "get_public_base_url_info",
            '"public_base_url_source"',
            '"webhook_url": get_webhook_url()',
        )
    )

    result = {
        "settings_file": str(settings_path),
        "settings_patched": settings_patched,
        "diagnostics_file": str(diagnostics_path),
        "diagnostics_patched": diagnostics_patched,
        "google_redirect_base_url": frappe.conf.get("google_redirect_base_url"),
        "host_name": frappe.conf.get("host_name"),
        "is_fully_patched": settings_patched and diagnostics_patched,
    }

    if settings_patched:
        from repair_management.integrations.line_sales_order_upload.settings import (
            get_public_base_url_info,
            get_webhook_url,
        )

        public_info = get_public_base_url_info()
        result.update(
            {
                "public_base_url": public_info["url"],
                "public_base_url_source": public_info["source"],
                "webhook_url": get_webhook_url(),
            }
        )

    return result
