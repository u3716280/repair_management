from __future__ import annotations

import hashlib
import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

import frappe


PATCH_NAME = "delete_doc_public_link"

TARGET_RELATIVE = Path("apps") / "frappe" / "frappe" / "model" / "delete_doc.py"

OLD_BLOCK = (
    'def raise_link_exists_exception(doc, reference_doctype, reference_docname, row=""):\n'
    "\tdoc_link = get_link_to_form(doc.doctype, doc.name, doc.name)\n"
    "\treference_link = get_link_to_form(reference_doctype, reference_docname, reference_docname)\n"
)

NEW_BLOCK = (
    "def _public_url_to_form(doctype, name):\n"
    '\t"""Build a form link honouring google_redirect_base_url over site_config.host_name.\n'
    "\n"
    "\tfrappe.utils.get_url_to_form() (via get_url()) reads site_config.host_name, which on\n"
    "\tthis site is intentionally pinned to a loopback address for wkhtmltopdf. User-facing\n"
    "\tlinks (e.g. the LinkExistsError message below) should use the public site URL instead.\n"
    '\t"""\n'
    "\tfrom urllib.parse import urlsplit, urlunsplit\n"
    "\n"
    "\tfrom frappe.utils.data import get_url_to_form\n"
    "\n"
    "\turl = get_url_to_form(doctype, name)\n"
    '\tpublic_base = frappe.conf.get("google_redirect_base_url")\n'
    "\tif not public_base:\n"
    "\t\treturn url\n"
    "\n"
    "\tparsed = urlsplit(url)\n"
    "\tpublic_parsed = urlsplit(public_base)\n"
    "\tif not public_parsed.scheme or not public_parsed.netloc:\n"
    "\t\treturn url\n"
    "\n"
    "\treturn urlunsplit((public_parsed.scheme, public_parsed.netloc, parsed.path, parsed.query, parsed.fragment))\n"
    "\n"
    "\n"
    'def raise_link_exists_exception(doc, reference_doctype, reference_docname, row=""):\n'
    '\tdoc_link = f\'<a href="{_public_url_to_form(doc.doctype, doc.name)}">{doc.name}</a>\'\n'
    "\treference_link = ("
    "\n\t\tf'<a href=\"{_public_url_to_form(reference_doctype, reference_docname)}\">"
    "{reference_docname}</a>'\n"
    "\t)\n"
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
        "is_patched": "_public_url_to_form" in content,
        "remaining_original_expressions": content.count(OLD_BLOCK),
    }


@frappe.whitelist()
def check() -> dict[str, Any]:
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

    if "_public_url_to_form" in original:
        return {
            "status": "already_patched",
            "file": _file_state(target),
        }

    replacement_count = original.count(OLD_BLOCK)
    if not replacement_count:
        frappe.throw(
            "Could not locate raise_link_exists_exception() in the expected form. "
            "frappe/model/delete_doc.py may have changed upstream; patch needs updating."
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
            "Restart bench start (or bench restart)",
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
            "Restart bench start (or bench restart)",
        ],
    }
