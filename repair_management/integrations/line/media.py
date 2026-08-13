from __future__ import annotations

import hashlib
import hmac
import io
import mimetypes
import subprocess
import tempfile
import time
from pathlib import Path
from urllib.parse import urlencode

import frappe
from PIL import Image, ImageOps

from repair_management.integrations.line.utils.public_url import public_base_url


_METHOD = "repair_management.integrations.line.media.get_media"


def _secret():
    value = frappe.local.conf.get("encryption_key") or frappe.local.conf.get("secret_key")
    if not value:
        frappe.throw("Site encryption_key is required for signed LINE media URLs")
    return str(value).encode("utf-8")


def _signature(file_name, expires, kind):
    payload = f"{file_name}|{int(expires)}|{kind}".encode("utf-8")
    return hmac.new(_secret(), payload, hashlib.sha256).hexdigest()


def signed_media_url(file_name, kind="original", ttl_seconds=900):
    expires = int(time.time()) + max(int(ttl_seconds), 60)
    token = _signature(file_name, expires, kind)
    query = urlencode({"file": file_name, "expires": expires, "kind": kind, "token": token})
    return f"{public_base_url()}/api/method/{_METHOD}?{query}"


def _file_bytes(file_doc):
    path = Path(frappe.get_site_path(file_doc.file_url.lstrip("/")))
    if not path.exists():
        # Frappe file_url uses /private/files/... and /files/...; resolve explicitly.
        if str(file_doc.file_url).startswith("/private/files/"):
            path = Path(frappe.get_site_path("private", "files", Path(file_doc.file_url).name))
        elif str(file_doc.file_url).startswith("/files/"):
            path = Path(frappe.get_site_path("public", "files", Path(file_doc.file_url).name))
    if not path.exists():
        frappe.throw("Media file is missing")
    return path.read_bytes(), path


def _image_preview(data):
    with Image.open(io.BytesIO(data)) as image:
        image = ImageOps.exif_transpose(image).convert("RGB")
        image.thumbnail((1200, 1200), Image.Resampling.LANCZOS)
        out = io.BytesIO()
        image.save(out, format="JPEG", quality=82, optimize=True)
        return out.getvalue()


def _video_preview(path):
    output = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as handle:
            output = Path(handle.name)
        cmd = [
            "ffmpeg", "-y", "-ss", "0.5", "-i", str(path),
            "-frames:v", "1", "-vf", "scale='min(1200,iw)':-2",
            "-q:v", "4", str(output),
        ]
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30)
        if result.returncode != 0 or not output.exists() or not output.stat().st_size:
            frappe.throw("Unable to create video preview")
        return output.read_bytes()
    finally:
        if output:
            try:
                output.unlink(missing_ok=True)
            except Exception:
                pass


@frappe.whitelist(allow_guest=True, methods=["GET"])
def get_media(file=None, expires=None, kind="original", token=None):
    try:
        expires_int = int(expires or 0)
    except (TypeError, ValueError):
        frappe.throw("Invalid media URL")
    if expires_int < int(time.time()):
        frappe.throw("Media URL has expired")
    if kind not in ("original", "preview"):
        frappe.throw("Invalid media kind")
    expected = _signature(file, expires_int, kind)
    if not token or not hmac.compare_digest(str(token), expected):
        frappe.throw("Invalid media token")
    if not file or not frappe.db.exists("File", file):
        frappe.throw("Media file does not exist")

    fdoc = frappe.get_doc("File", file)
    data, path = _file_bytes(fdoc)
    content_type = mimetypes.guess_type(fdoc.file_name or fdoc.file_url or "")[0] or "application/octet-stream"
    filename = fdoc.file_name or path.name

    if kind == "preview":
        if content_type.startswith("image/"):
            data = _image_preview(data)
        elif content_type.startswith("video/"):
            data = _video_preview(path)
        else:
            frappe.throw("Preview is only available for image/video media")
        content_type = "image/jpeg"
        filename = f"preview-{Path(filename).stem}.jpg"

    frappe.local.response.filename = filename
    frappe.local.response.filecontent = data
    frappe.local.response.type = "download"
    frappe.local.response.content_type = content_type
