
from __future__ import annotations

import hashlib
import hmac
import os
import time
from urllib.parse import urlencode

import frappe
from frappe.utils import cint, get_url


def _get_media_secret() -> str:
    settings = frappe.get_single("LINE Settings")
    secret = settings.get_password("media_signing_secret")
    if not secret:
        frappe.throw("Media Signing Secret is not configured in LINE Settings")
    return secret


def _signature(file_name: str, expires: int) -> str:
    payload = f"{file_name}|{expires}".encode("utf-8")
    return hmac.new(_get_media_secret().encode("utf-8"), payload, hashlib.sha256).hexdigest()


def get_signed_file_url(file_name: str, ttl_seconds: int | None = None) -> str:
    settings = frappe.get_single("LINE Settings")
    ttl = max(cint(ttl_seconds or settings.signed_url_expiry_seconds or 3600), 300)
    expires = int(time.time()) + ttl
    query = urlencode(
        {
            "file": file_name,
            "expires": expires,
            "signature": _signature(file_name, expires),
        }
    )

    base_url = (
        frappe.conf.get("google_redirect_base_url")
        or frappe.conf.get("host_name")
        or get_url()
    ).rstrip("/")

    return f"{base_url}/api/method/repair_management.integrations.line.media.get_file?{query}"


@frappe.whitelist(allow_guest=True, methods=["GET"])
def get_file(file: str | None = None, expires: str | None = None, signature: str | None = None):
    file_name = (file or "").strip()
    expiry = cint(expires)
    supplied_signature = (signature or "").strip()

    if not file_name or not expiry or not supplied_signature:
        return _deny(400, "Missing signed file parameters")
    if expiry < int(time.time()):
        return _deny(410, "Signed file URL has expired")

    expected = _signature(file_name, expiry)
    if not hmac.compare_digest(expected, supplied_signature):
        return _deny(403, "Invalid signed file URL")

    if not frappe.db.exists("File", file_name):
        return _deny(404, "File not found")

    file_doc = frappe.get_doc("File", file_name)
    if file_doc.attached_to_doctype != "LINE Delivery Confirmation":
        return _deny(403, "File is not a LINE delivery confirmation attachment")

    full_path = file_doc.get_full_path()
    if not os.path.isfile(full_path):
        return _deny(404, "File content not found")

    with open(full_path, "rb") as handle:
        content = handle.read()

    frappe.local.response.filename = file_doc.file_name
    frappe.local.response.filecontent = content
    frappe.local.response.type = "download"
    frappe.local.response.display_content_as = "inline"
    return None


def _deny(status_code: int, message: str):
    frappe.local.response["http_status_code"] = status_code
    return {"ok": False, "error": message}
