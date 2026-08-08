from __future__ import annotations

import shutil
from pathlib import Path

import frappe


def revert(backup_directory: str) -> dict:
    """Restore settings.py and diagnostics.py from a backup created by apply()."""
    backup_root = Path(backup_directory).expanduser().resolve()
    if not backup_root.exists() or not backup_root.is_dir():
        frappe.throw(f"Backup directory not found: {backup_root}")

    package_root = Path(frappe.get_app_path("repair_management"))
    integration_root = package_root / "integrations" / "line_sales_order_upload"
    restored = []
    for filename in ("settings.py", "diagnostics.py"):
        source = backup_root / filename
        destination = integration_root / filename
        if not source.exists():
            frappe.throw(f"Backup file not found: {source}")
        shutil.copy2(source, destination)
        restored.append(str(destination))

    frappe.clear_cache()
    return {"status": "reverted", "backup_directory": str(backup_root), "restored_files": restored}
