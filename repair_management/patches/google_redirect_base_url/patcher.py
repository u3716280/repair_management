from __future__ import annotations

import hashlib
import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

import frappe


PATCH_NAME = "google_redirect_base_url"

CALENDAR_OLD = "get_request_site_address(full_address=True)"
COMMON_OLD = "get_request_site_address(True)"

BASE_EXPRESSION = (
    '(frappe.conf.get("google_redirect_base_url") '
    'or get_request_site_address(True)).rstrip("/")'
)

CALENDAR_BASE_EXPRESSION = (
    "(frappe.conf.get('google_redirect_base_url') "
    "or get_request_site_address(full_address=True)).rstrip('/')"
)


def _bench_path() -> Path:
    return Path(frappe.utils.get_bench_path()).resolve()


def _site_name() -> str:
    return frappe.local.site


def _site_config_path() -> Path:
    return _bench_path() / "sites" / _site_name() / "site_config.json"


def _backup_root() -> Path:
    return _bench_path() / "patch_backups"


def _latest_pointer() -> Path:
    return _backup_root() / f"{PATCH_NAME}-LATEST"


def _calendar_path() -> Path:
    return (
        _bench_path()
        / "apps"
        / "frappe"
        / "frappe"
        / "integrations"
        / "doctype"
        / "google_calendar"
        / "google_calendar.py"
    )


def _google_oauth_path() -> Path:
    return (
        _bench_path()
        / "apps"
        / "frappe"
        / "frappe"
        / "integrations"
        / "google_oauth.py"
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_site_config() -> dict[str, Any]:
    config_path = _site_config_path()

    if not config_path.exists():
        frappe.throw(f"site_config.json was not found: {config_path}")

    return json.loads(config_path.read_text(encoding="utf-8"))


def _save_site_config(config: dict[str, Any]) -> None:
    _site_config_path().write_text(
        json.dumps(config, ensure_ascii=False, indent=1) + "\n",
        encoding="utf-8",
    )


def _validate_public_url(public_url: str) -> str:
    public_url = (public_url or "").strip().rstrip("/")

    if not public_url.startswith("https://"):
        frappe.throw("google_redirect_base_url must start with https://")

    if "127.0.0.1" in public_url or "localhost" in public_url:
        frappe.throw(
            "google_redirect_base_url must be a public HTTPS URL."
        )

    return public_url


def _target_files() -> list[Path]:
    targets = [_calendar_path(), _google_oauth_path()]

    missing = [str(path) for path in targets if not path.exists()]
    if missing:
        frappe.throw(
            "Required Frappe Google integration files were not found:\n"
            + "\n".join(missing)
        )

    return targets


def _patch_calendar(content: str) -> tuple[str, int]:
    if CALENDAR_BASE_EXPRESSION in content:
        return content, 0

    replacement_count = content.count(CALENDAR_OLD)

    if replacement_count:
        content = content.replace(
            CALENDAR_OLD,
            CALENDAR_BASE_EXPRESSION,
        )

    return content, replacement_count


def _patch_google_oauth(content: str) -> tuple[str, int]:
    if BASE_EXPRESSION in content:
        return content, 0

    replacement_count = content.count(COMMON_OLD)

    if replacement_count:
        content = content.replace(
            COMMON_OLD,
            BASE_EXPRESSION,
        )

    return content, replacement_count


def _patch_file(path: Path, content: str) -> tuple[str, int]:
    if path == _calendar_path():
        return _patch_calendar(content)

    if path == _google_oauth_path():
        return _patch_google_oauth(content)

    return content, 0


def _file_state(path: Path) -> dict[str, Any]:
    content = path.read_text(encoding="utf-8")

    if path == _calendar_path():
        old_count = content.count(CALENDAR_OLD) - content.count(
            CALENDAR_BASE_EXPRESSION
        )
    else:
        old_count = content.count(COMMON_OLD) - content.count(
            BASE_EXPRESSION
        )

    return {
        "path": str(path.relative_to(_bench_path())),
        "uses_google_redirect_base_url": (
            "google_redirect_base_url" in content
        ),
        "remaining_original_expressions": old_count,
    }


@frappe.whitelist()
def check() -> dict[str, Any]:
    config = _load_site_config()
    files = [_file_state(path) for path in _target_files()]

    return {
        "site": _site_name(),
        "bench": str(_bench_path()),
        "google_redirect_base_url": config.get(
            "google_redirect_base_url"
        ),
        "files": files,
        "is_fully_patched": all(
            item["uses_google_redirect_base_url"]
            and item["remaining_original_expressions"] == 0
            for item in files
        ),
        "coverage": {
            "google_calendar": str(
                _calendar_path().relative_to(_bench_path())
            ),
            "google_contacts_and_drive": str(
                _google_oauth_path().relative_to(_bench_path())
            ),
        },
    }


@frappe.whitelist()
def apply(
    public_url: str = "https://house147.eakthai.com",
) -> dict[str, Any]:
    public_url = _validate_public_url(public_url)
    bench_path = _bench_path()
    site_config_path = _site_config_path()
    targets = _target_files()

    pending: list[tuple[Path, str, str, int]] = []

    for target in targets:
        original = target.read_text(encoding="utf-8")
        patched, replacement_count = _patch_file(target, original)

        if replacement_count:
            pending.append(
                (target, original, patched, replacement_count)
            )

    config = _load_site_config()
    config["google_redirect_base_url"] = public_url

    if not pending:
        _save_site_config(config)
        frappe.clear_cache()

        return {
            "status": "already_patched",
            "google_redirect_base_url": public_url,
            "files": [_file_state(path) for path in targets],
        }

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_dir = _backup_root() / f"{PATCH_NAME}-{timestamp}"
    backup_dir.mkdir(parents=True, exist_ok=False)

    manifest: dict[str, Any] = {
        "patch_name": PATCH_NAME,
        "site": _site_name(),
        "bench": str(bench_path),
        "public_url": public_url,
        "created_at": timestamp,
        "files": [],
    }

    config_backup = backup_dir / site_config_path.relative_to(bench_path)
    config_backup.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(site_config_path, config_backup)

    for target, original, patched, replacement_count in pending:
        relative_path = target.relative_to(bench_path)
        backup_path = backup_dir / relative_path
        backup_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(target, backup_path)

        target.write_text(patched, encoding="utf-8")

        manifest["files"].append(
            {
                "path": str(relative_path),
                "replacements": replacement_count,
                "before_sha256": _sha256(backup_path),
                "after_sha256": _sha256(target),
            }
        )

    _save_site_config(config)

    manifest_path = backup_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    _backup_root().mkdir(parents=True, exist_ok=True)
    _latest_pointer().write_text(
        str(backup_dir) + "\n",
        encoding="utf-8",
    )

    frappe.clear_cache()

    return {
        "status": "patched",
        "google_redirect_base_url": public_url,
        "backup_directory": str(backup_dir),
        "patched_files": [
            entry["path"] for entry in manifest["files"]
        ],
        "coverage": {
            "google_calendar": str(
                _calendar_path().relative_to(bench_path)
            ),
            "google_contacts_and_drive": str(
                _google_oauth_path().relative_to(bench_path)
            ),
        },
        "next_steps": [
            f"bench --site {_site_name()} clear-cache",
            f"bench --site {_site_name()} clear-website-cache",
            "Restart bench start",
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
            frappe.throw(
                f"Latest backup pointer was not found: {pointer}"
            )

        backup_dir = Path(
            pointer.read_text(encoding="utf-8").strip()
        ).resolve()

    manifest_path = backup_dir / "manifest.json"
    if not manifest_path.exists():
        frappe.throw(f"Manifest was not found: {manifest_path}")

    manifest = json.loads(
        manifest_path.read_text(encoding="utf-8")
    )

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

    config_relative = (
        Path("sites") / manifest["site"] / "site_config.json"
    )
    config_backup = backup_dir / config_relative

    if config_backup.exists():
        shutil.copy2(
            config_backup,
            bench_path / config_relative,
        )
        restored_files.append(str(config_relative))

    frappe.clear_cache()

    return {
        "status": "restored",
        "backup_directory": str(backup_dir),
        "restored_files": restored_files,
        "next_steps": [
            f"bench --site {_site_name()} clear-cache",
            f"bench --site {_site_name()} clear-website-cache",
            "Restart bench start",
        ],
    }
