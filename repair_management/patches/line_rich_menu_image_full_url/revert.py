from __future__ import annotations

import shutil
from pathlib import Path

import frappe


def revert(backup_directory: str) -> dict:
    backup_root = Path(backup_directory).expanduser().resolve()
    if not backup_root.is_dir():
        frappe.throw(f"Backup directory not found: {backup_root}")

    package_root = Path(frappe.get_app_path("repair_management"))
    integration_root = package_root / "integrations" / "line_sales_order_upload"
    restored = []
    for filename in ("utils.py", "rich_menu_payload.py"):
        source = backup_root / filename
        target = integration_root / filename
        if source.exists():
            shutil.copy2(source, target)
            restored.append(str(target))

    if not restored:
        frappe.throw("No patch backup files found")
    frappe.clear_cache()
    return {
        "status": "reverted",
        "backup_directory": str(backup_root),
        "restored_files": restored,
        "next_steps": [
            "bench --site <site> clear-cache",
            "bench --site <site> clear-website-cache",
            "Restart bench start",
        ],
    }
