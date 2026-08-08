from __future__ import annotations

import ast
import importlib
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path

import frappe

PATCH_NAME = "line_rich_menu_image_full_url"
UTILS_BLOCK_START = "# BEGIN PATCH: line_rich_menu_image_full_url"
UTILS_BLOCK_END = "# END PATCH: line_rich_menu_image_full_url"

UTILS_BLOCK = r'''
# BEGIN PATCH: line_rich_menu_image_full_url
def _public_base_url_for_file() -> str:
    """Use the same public base URL policy as the LINE webhook patch."""
    try:
        from .settings import get_public_base_url

        return get_public_base_url().rstrip("/")
    except (ImportError, AttributeError):
        from frappe.utils import get_url

        raw = (
            frappe.conf.get("google_redirect_base_url")
            or frappe.conf.get("host_name")
            or get_url()
        )
        return str(raw or "").strip().rstrip("/")


def _strip_site_name_prefix(path: str) -> str:
    """Remove an accidental site-name prefix such as local.147/files/..."""
    normalized = "/" + str(path or "").lstrip("/")
    site_name = str(getattr(frappe.local, "site", "") or "").strip("/")
    if site_name and normalized.startswith(f"/{site_name}/"):
        normalized = normalized[len(site_name) + 1 :]
        normalized = "/" + normalized.lstrip("/")
    return normalized


def public_file_url(file_reference: str) -> str:
    """Return an HTTP(S) full URL for a Frappe file reference."""
    from urllib.parse import urlsplit, urlunsplit

    raw = str(file_reference or "").strip()
    if not raw:
        frappe.throw("File URL is empty")

    parsed = urlsplit(raw)
    if parsed.scheme or parsed.netloc:
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            frappe.throw(f"Unsupported file URL: {raw}")
        return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, parsed.query, ""))

    path = _strip_site_name_prefix(raw)
    return f"{_public_base_url_for_file()}{path}"


def site_file_path(file_url: str) -> Path:
    """Resolve a relative or full Frappe file URL to the current site's filesystem.

    Supported examples:
    - /files/menu.jpg
    - https://house147.eakthai.com/files/menu.jpg
    - /private/files/menu.jpg
    - local.147/files/menu.jpg (legacy malformed value; site prefix is removed)
    """
    from urllib.parse import unquote, urlsplit

    raw = str(file_url or "").strip()
    if not raw:
        frappe.throw("File URL is empty")

    parsed = urlsplit(raw)
    if parsed.scheme or parsed.netloc:
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            frappe.throw(f"Unsupported file URL: {raw}")
        url_path = parsed.path
    else:
        url_path = raw

    url_path = _strip_site_name_prefix(unquote(url_path))
    if url_path.startswith("/files/"):
        relative = Path("public") / "files" / url_path.removeprefix("/files/")
    elif url_path == "/files":
        relative = Path("public") / "files"
    elif url_path.startswith("/private/files/"):
        relative = Path("private") / "files" / url_path.removeprefix("/private/files/")
    elif url_path == "/private/files":
        relative = Path("private") / "files"
    elif url_path.startswith("files/"):
        relative = Path("public") / url_path
    elif url_path.startswith("private/files/"):
        relative = Path(url_path)
    else:
        # Preserve compatibility for existing callers that pass a site-relative path.
        relative = Path(url_path.lstrip("/"))

    site_root = Path(frappe.get_site_path()).resolve()
    candidate = (site_root / relative).resolve()
    if candidate != site_root and site_root not in candidate.parents:
        frappe.throw(f"File path escapes the current site: {file_url}")
    return candidate
# END PATCH: line_rich_menu_image_full_url
'''.strip()


def _paths() -> tuple[Path, Path, Path]:
    package_root = Path(frappe.get_app_path("repair_management"))
    integration_root = package_root / "integrations" / "line_sales_order_upload"
    return package_root, integration_root / "utils.py", integration_root / "rich_menu_payload.py"


def _replace_site_file_path(text: str) -> str:
    if UTILS_BLOCK_START in text and UTILS_BLOCK_END in text:
        prefix = text.split(UTILS_BLOCK_START, 1)[0].rstrip()
        suffix = text.split(UTILS_BLOCK_END, 1)[1].lstrip("\n")
        return f"{prefix}\n\n{UTILS_BLOCK}\n" + (f"\n{suffix}" if suffix else "")

    pattern = re.compile(
        r"\n\ndef site_file_path\(file_url: str\) -> Path:\n"
        r"(?:    .*\n)+?"
        r"(?=\n\ndef |\Z)",
        re.MULTILINE,
    )
    match = pattern.search(text)
    if not match:
        raise RuntimeError("Could not locate site_file_path() in utils.py")
    return text[: match.start()] + f"\n\n{UTILS_BLOCK}\n" + text[match.end() :]


def _patch_payload(text: str) -> str:
    old_import = "from .utils import site_file_path"
    new_import = "from .utils import public_file_url, site_file_path"
    if old_import in text:
        text = text.replace(old_import, new_import, 1)
    elif new_import not in text:
        raise RuntimeError("Could not locate utils import in rich_menu_payload.py")

    old = '''    image_url = (doc.image or "").strip()\n    if image_url.startswith("/assets/repair_management/"):\n        relative = image_url.split("/assets/repair_management/", 1)[1]\n        path = Path(frappe.get_app_path("repair_management", "public", relative))\n    else:\n        path = site_file_path(image_url)\n    if not path.exists():\n        frappe.throw(f"ไม่พบไฟล์ภาพ: {path}")\n'''
    new = '''    image_reference = (doc.image or "").strip()\n    if image_reference.startswith("/assets/repair_management/"):\n        relative = image_reference.split("/assets/repair_management/", 1)[1]\n        image_url = public_file_url(image_reference)\n        path = Path(frappe.get_app_path("repair_management", "public", relative))\n    else:\n        image_url = public_file_url(image_reference)\n        path = site_file_path(image_url)\n    if not path.exists():\n        frappe.throw(f"ไม่พบไฟล์ภาพ: {image_url}\\nResolved path: {path}")\n'''
    if old in text:
        text = text.replace(old, new, 1)
    elif "image_reference = (doc.image or \"\").strip()" not in text:
        raise RuntimeError("Could not locate image_path() body in rich_menu_payload.py")
    return text


def _validate(path: Path, content: str) -> None:
    ast.parse(content, filename=str(path))


def _backup(files: list[Path], root: Path) -> None:
    for source in files:
        shutil.copy2(source, root / source.name)


def apply() -> dict:
    _package_root, utils_path, payload_path = _paths()
    missing = [str(path) for path in (utils_path, payload_path) if not path.exists()]
    if missing:
        frappe.throw(f"Required LINE integration file(s) not found: {', '.join(missing)}")

    original_utils = utils_path.read_text(encoding="utf-8")
    original_payload = payload_path.read_text(encoding="utf-8")
    patched_utils = _replace_site_file_path(original_utils)
    patched_payload = _patch_payload(original_payload)
    _validate(utils_path, patched_utils)
    _validate(payload_path, patched_payload)

    bench_root = Path(frappe.get_app_path("repair_management")).parents[2]
    backup_root = bench_root / "patch_backups" / f"{PATCH_NAME}-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    backup_root.mkdir(parents=True, exist_ok=False)
    _backup([utils_path, payload_path], backup_root)

    changed = []
    if patched_utils != original_utils:
        utils_path.write_text(patched_utils, encoding="utf-8")
        changed.append(str(utils_path))
    if patched_payload != original_payload:
        payload_path.write_text(patched_payload, encoding="utf-8")
        changed.append(str(payload_path))

    frappe.clear_cache()

    # Import after writing the source so the result reflects the patched implementation.
    importlib.invalidate_caches()
    sys.modules.pop("repair_management.integrations.line_sales_order_upload.rich_menu_payload", None)
    sys.modules.pop("repair_management.integrations.line_sales_order_upload.utils", None)
    from repair_management.integrations.line_sales_order_upload.utils import public_file_url, site_file_path

    sample_relative = "/files/EakThai_Default_RichMenu_2500x1686.jpg"
    sample_full = public_file_url(sample_relative)
    sample_path = site_file_path(sample_full)
    return {
        "status": "patched" if changed else "already_patched",
        "backup_directory": str(backup_root),
        "modified_files": changed,
        "sample_relative_url": sample_relative,
        "sample_full_url": sample_full,
        "sample_resolved_path": str(sample_path),
        "google_redirect_base_url": frappe.conf.get("google_redirect_base_url"),
        "next_steps": [
            "bench --site <site> clear-cache",
            "bench --site <site> clear-website-cache",
            "Restart bench start",
            "Run line_rich_menu_image_full_url.check.check",
            "Validate Default Rich Menu again",
        ],
    }
