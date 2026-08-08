from __future__ import annotations

import ast
import shutil
from datetime import datetime
from pathlib import Path

import frappe

PATCH_NAME = "line_public_base_url"
SETTINGS_BLOCK_START = "# BEGIN PATCH: line_public_base_url"
SETTINGS_BLOCK_END = "# END PATCH: line_public_base_url"

SETTINGS_BLOCK = r'''
# BEGIN PATCH: line_public_base_url
PUBLIC_BASE_URL_CONFIG_KEY = "google_redirect_base_url"
LINE_WEBHOOK_PATH = "/api/method/repair_management.integrations.line_sales_order_upload.webhook.handle"


def _normalize_public_base_url(value) -> str:
    """Return a clean HTTP(S) base URL without a trailing slash."""
    from urllib.parse import urlsplit

    raw = str(value or "").strip()
    if not raw:
        return ""
    if "://" not in raw:
        raw = f"https://{raw}"

    parsed = urlsplit(raw)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        frappe.throw(f"Invalid public base URL: {raw}")
    if parsed.query or parsed.fragment:
        frappe.throw("Public base URL must not contain a query string or fragment")

    path = parsed.path.rstrip("/")
    return f"{parsed.scheme}://{parsed.netloc}{path}"


def get_public_base_url_info() -> dict:
    """Resolve the public URL with google_redirect_base_url taking priority."""
    from frappe.utils import get_url

    candidates = (
        (PUBLIC_BASE_URL_CONFIG_KEY, frappe.conf.get(PUBLIC_BASE_URL_CONFIG_KEY)),
        ("host_name", frappe.conf.get("host_name")),
    )
    for source, raw_value in candidates:
        normalized = _normalize_public_base_url(raw_value)
        if normalized:
            return {
                "url": normalized,
                "source": source,
                "configured_value": str(raw_value).strip(),
            }

    fallback = _normalize_public_base_url(get_url())
    return {
        "url": fallback,
        "source": "frappe.utils.get_url",
        "configured_value": fallback,
    }


def get_public_base_url() -> str:
    return get_public_base_url_info()["url"]


def get_webhook_url() -> str:
    return f"{get_public_base_url()}{LINE_WEBHOOK_PATH}"
# END PATCH: line_public_base_url
'''.strip()


def _app_paths() -> tuple[Path, Path, Path]:
    package_root = Path(frappe.get_app_path("repair_management"))
    integration_root = package_root / "integrations" / "line_sales_order_upload"
    return package_root, integration_root / "settings.py", integration_root / "diagnostics.py"


def _replace_marked_block(text: str, block: str) -> str:
    if SETTINGS_BLOCK_START in text and SETTINGS_BLOCK_END in text:
        prefix = text.split(SETTINGS_BLOCK_START, 1)[0].rstrip()
        suffix = text.split(SETTINGS_BLOCK_END, 1)[1].lstrip("\n")
        result = f"{prefix}\n\n{block}\n"
        if suffix:
            result += f"\n{suffix}"
        return result
    return f"{text.rstrip()}\n\n{block}\n"


def _patch_settings(text: str) -> str:
    return _replace_marked_block(text, SETTINGS_BLOCK)


def _patch_diagnostics(text: str) -> str:
    text = text.replace("from frappe.utils import get_url\n", "")

    old_import = "from .settings import get_settings"
    new_import = "from .settings import get_public_base_url_info, get_settings, get_webhook_url"
    if old_import in text:
        text = text.replace(old_import, new_import)
    elif new_import not in text:
        raise RuntimeError("Could not locate settings import in diagnostics.py")

    settings_line = "    settings = get_settings(required=False)\n"
    info_line = "    public_base_url_info = get_public_base_url_info()\n"
    if info_line not in text:
        if settings_line not in text:
            raise RuntimeError("Could not locate settings initialization in diagnostics.py")
        text = text.replace(settings_line, settings_line + info_line, 1)

    old_webhook = '        "webhook_url": f"{get_url()}/api/method/repair_management.integrations.line_sales_order_upload.webhook.handle",\n'
    new_webhook = (
        '        "public_base_url": public_base_url_info["url"],\n'
        '        "public_base_url_source": public_base_url_info["source"],\n'
        '        "google_redirect_base_url": frappe.conf.get("google_redirect_base_url"),\n'
        '        "host_name": frappe.conf.get("host_name"),\n'
        '        "webhook_url": get_webhook_url(),\n'
    )
    if old_webhook in text:
        text = text.replace(old_webhook, new_webhook, 1)
    elif '"webhook_url": get_webhook_url()' not in text:
        raise RuntimeError("Could not locate webhook URL generation in diagnostics.py")

    return text


def _validate_python(path: Path, content: str) -> None:
    ast.parse(content, filename=str(path))


def _backup_files(files: list[Path], backup_root: Path) -> None:
    for source in files:
        relative = source.name
        destination = backup_root / relative
        shutil.copy2(source, destination)


def apply() -> dict:
    """Apply the patch idempotently and back up every modified source file."""
    _package_root, settings_path, diagnostics_path = _app_paths()
    missing = [str(path) for path in (settings_path, diagnostics_path) if not path.exists()]
    if missing:
        frappe.throw(f"Required LINE integration file(s) not found: {', '.join(missing)}")

    original_settings = settings_path.read_text(encoding="utf-8")
    original_diagnostics = diagnostics_path.read_text(encoding="utf-8")
    patched_settings = _patch_settings(original_settings)
    patched_diagnostics = _patch_diagnostics(original_diagnostics)

    _validate_python(settings_path, patched_settings)
    _validate_python(diagnostics_path, patched_diagnostics)

    bench_root = Path(frappe.get_app_path("repair_management")).parents[2]
    backup_root = bench_root / "patch_backups" / f"{PATCH_NAME}-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    backup_root.mkdir(parents=True, exist_ok=False)
    _backup_files([settings_path, diagnostics_path], backup_root)

    settings_changed = patched_settings != original_settings
    diagnostics_changed = patched_diagnostics != original_diagnostics
    if settings_changed:
        settings_path.write_text(patched_settings, encoding="utf-8")
    if diagnostics_changed:
        diagnostics_path.write_text(patched_diagnostics, encoding="utf-8")

    frappe.clear_cache()
    from repair_management.integrations.line_sales_order_upload.settings import get_public_base_url_info, get_webhook_url

    public_info = get_public_base_url_info()
    result = {
        "status": "patched" if settings_changed or diagnostics_changed else "already_patched",
        "backup_directory": str(backup_root),
        "modified_files": [
            str(path)
            for path, changed in ((settings_path, settings_changed), (diagnostics_path, diagnostics_changed))
            if changed
        ],
        "public_base_url": public_info["url"],
        "public_base_url_source": public_info["source"],
        "google_redirect_base_url": frappe.conf.get("google_redirect_base_url"),
        "host_name": frappe.conf.get("host_name"),
        "webhook_url": get_webhook_url(),
        "next_steps": [
            "bench --site <site> clear-cache",
            "bench --site <site> clear-website-cache",
            "Restart bench start",
            "Run diagnostics.check_setup",
        ],
    }
    return result
