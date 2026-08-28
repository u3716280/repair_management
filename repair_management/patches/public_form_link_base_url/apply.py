from __future__ import annotations

import hashlib
import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

import frappe


PATCH_NAME = "public_form_link_base_url"

TARGET_RELATIVE = Path("apps") / "frappe" / "frappe" / "utils" / "data.py"

OLD_BLOCK = (
    'def get_url_to_form(doctype: str, name: str) -> str:\n'
    '\treturn get_url(uri=f"/app/{quoted(slug(doctype))}/{quoted(name)}")\n'
)

NEW_BLOCK = (
    'def get_url_to_form(doctype: str, name: str) -> str:\n'
    '\turl = get_url(uri=f"/app/{quoted(slug(doctype))}/{quoted(name)}")\n'
    '\tpublic_base = frappe.conf.get("google_redirect_base_url")\n'
    '\tif not public_base:\n'
    '\t\treturn url\n'
    '\n'
    '\tparsed = urlparse(url)\n'
    '\tpublic_parsed = urlparse(public_base)\n'
    '\tif not public_parsed.scheme or not public_parsed.netloc:\n'
    '\t\treturn url\n'
    '\n'
    '\treturn urlunparse(\n'
    '\t\t(public_parsed.scheme, public_parsed.netloc, parsed.path, parsed.params, parsed.query, parsed.fragment)\n'
    '\t)\n'
)


def _bench_path() -> Path:
    return Path(frappe.utils.get_bench_path()).resolve()


def _site_name() -> str:
    return frappe.local.site


def _target_path() -> Path:
    return _bench_path() / TARGET_RELATIVE


def _backup_root() -> Path:
    return _bench_path() / "patch_backups"


def _latest_pointer() -> Path:
    return _backup_root() / f"{PATCH_NAME}-LATEST"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _file_state(path: Path) -> dict[str, Any]:
    content = path.read_text(encoding="utf-8")
    return {
        "path": str(path.relative_to(_bench_path())),
        "is_patched": 'public_base = frappe.conf.get("google_redirect_base_url")' in content,
        "remaining_original_expressions": content.count(OLD_BLOCK),
    }


@frappe.whitelist()
def check() -> dict[str, Any]:
    """Report current patch status without changing anything.

    get_url_to_form() (and get_link_to_form(), which calls it) is used by ~144
    call sites across frappe/erpnext/hrms for every user-facing document link:
    delete/cancel "is linked with" errors, assignment & workflow notification
    emails, various ERPNext/HRMS validation messages, etc. All of them read
    site_config.host_name (pinned to http://127.0.0.1:8000 for wkhtmltopdf, see
    repair_management/patches/google_redirect_base_url) instead of the public
    domain. This patch fixes all of them from one place.

    Does NOT touch host_name or the wkhtmltopdf/PDF rendering path (which uses
    frappe.utils.get_host_name() -> bare get_url() with no uri - a different,
    unpatched code path).
    """
    target = _target_path()
    if not target.exists():
        frappe.throw(f"Target file was not found: {target}")

    return {
        "site": _site_name(),
        "bench": str(_bench_path()),
        "google_redirect_base_url": frappe.conf.get("google_redirect_base_url"),
        "host_name": frappe.conf.get("host_name"),
        "file": _file_state(target),
    }


@frappe.whitelist()
def apply() -> dict[str, Any]:
    target = _target_path()
    if not target.exists():
        frappe.throw(f"Target file was not found: {target}")

    original = target.read_text(encoding="utf-8")

    if 'public_base = frappe.conf.get("google_redirect_base_url")' in original:
        return {
            "status": "already_patched",
            "file": _file_state(target),
        }

    replacement_count = original.count(OLD_BLOCK)
    if not replacement_count:
        frappe.throw(
            "Could not locate get_url_to_form() in the expected form. "
            "frappe/utils/data.py may have changed upstream; patch needs updating."
        )

    patched = original.replace(OLD_BLOCK, NEW_BLOCK)

    bench_path = _bench_path()
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_dir = _backup_root() / f"{PATCH_NAME}-{timestamp}"
    backup_dir.mkdir(parents=True, exist_ok=False)

    backup_path = backup_dir / TARGET_RELATIVE
    backup_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(target, backup_path)

    target.write_text(patched, encoding="utf-8")

    manifest = {
        "patch_name": PATCH_NAME,
        "site": _site_name(),
        "bench": str(bench_path),
        "created_at": timestamp,
        "files": [
            {
                "path": str(TARGET_RELATIVE),
                "replacements": replacement_count,
                "before_sha256": _sha256(backup_path),
                "after_sha256": _sha256(target),
            }
        ],
    }
    manifest_path = backup_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    _backup_root().mkdir(parents=True, exist_ok=True)
    _latest_pointer().write_text(str(backup_dir) + "\n", encoding="utf-8")

    frappe.clear_cache()

    return {
        "status": "patched",
        "backup_directory": str(backup_dir),
        "file": _file_state(target),
        "next_steps": [
            f"bench --site {_site_name()} clear-cache",
            "bench restart (to reload the patched source into running workers)",
        ],
    }


@frappe.whitelist()
def revert(backup_directory: str | None = None) -> dict[str, Any]:
    bench_path = _bench_path()

    if backup_directory:
        backup_dir = Path(backup_directory).expanduser().resolve()
    else:
        pointer = _latest_pointer()
        if not pointer.exists():
            frappe.throw(f"Latest backup pointer was not found: {pointer}")
        backup_dir = Path(pointer.read_text(encoding="utf-8").strip()).resolve()

    manifest_path = backup_dir / "manifest.json"
    if not manifest_path.exists():
        frappe.throw(f"Manifest was not found: {manifest_path}")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    restored_files: list[str] = []
    for entry in manifest.get("files", []):
        relative_path = Path(entry["path"])
        source = backup_dir / relative_path
        destination = bench_path / relative_path

        if not source.exists():
            frappe.throw(f"Backup file was not found: {source}")

        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        restored_files.append(str(relative_path))

    frappe.clear_cache()

    return {
        "status": "restored",
        "backup_directory": str(backup_dir),
        "restored_files": restored_files,
        "next_steps": [
            f"bench --site {_site_name()} clear-cache",
            "bench restart (to reload the restored source into running workers)",
        ],
    }
