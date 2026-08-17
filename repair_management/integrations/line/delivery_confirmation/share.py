from __future__ import annotations

import base64
import hashlib
import hmac
import io
import json
import time
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse

import frappe
from frappe.utils import get_datetime, get_url
from PIL import Image, ImageOps
from werkzeug.wrappers import Response


SHARE_TTL_SECONDS = 3600
SHARE_METHOD = "repair_management.integrations.line.delivery_confirmation.share.image"
SHARE_PATH = f"/api/method/{SHARE_METHOD}"
TOKEN_PURPOSE = "line-pod-image"
ORIGINAL_MAX_BYTES = 10 * 1024 * 1024
PREVIEW_MAX_BYTES = 950 * 1024


def _b64encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode((value + padding).encode("ascii"))


def _secret() -> bytes:
    conf = getattr(frappe, "conf", None) or {}
    value = conf.get("encryption_key") or conf.get("secret_key")
    if not value:
        frappe.throw("Site encryption_key is required for POD signed URLs", frappe.ValidationError)
    return str(value).encode("utf-8")


def _public_base_url() -> str:
    conf = getattr(frappe, "conf", None) or {}
    value = conf.get("google_redirect_base_url") or conf.get("host_name") or get_url()
    return str(value).rstrip("/")


def _sign_payload(payload: dict) -> str:
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    encoded = _b64encode(raw)
    signature = hmac.new(_secret(), encoded.encode("ascii"), hashlib.sha256).digest()
    return f"{encoded}.{_b64encode(signature)}"


def _decode_token(token: str, *, require_not_expired: bool = True) -> dict:
    try:
        encoded, supplied = str(token or "").split(".", 1)
        expected = hmac.new(_secret(), encoded.encode("ascii"), hashlib.sha256).digest()
        if not hmac.compare_digest(expected, _b64decode(supplied)):
            raise ValueError("bad_signature")
        payload = json.loads(_b64decode(encoded).decode("utf-8"))
    except Exception as exc:
        raise frappe.PermissionError("Invalid POD image token") from exc

    if payload.get("p") != TOKEN_PURPOSE:
        raise frappe.PermissionError("Invalid POD image token purpose")
    if payload.get("v") not in ("original", "preview"):
        raise frappe.PermissionError("Invalid POD image token variant")
    if require_not_expired and int(payload.get("exp") or 0) < int(time.time()):
        raise frappe.PermissionError("POD image token expired")
    return payload


def _token_for(confirmation_name: str, file_name: str, variant: str, expires_at: int) -> str:
    return _sign_payload(
        {
            "p": TOKEN_PURPOSE,
            "c": confirmation_name,
            "f": file_name,
            "v": variant,
            "exp": int(expires_at),
        }
    )


def create_image_urls(confirmation_name: str, file_name: str, ttl_seconds: int = SHARE_TTL_SECONDS) -> dict:
    expires_at = int(time.time()) + max(int(ttl_seconds or SHARE_TTL_SECONDS), 60)
    base = f"{_public_base_url()}{SHARE_PATH}"
    original_token = _token_for(confirmation_name, file_name, "original", expires_at)
    preview_token = _token_for(confirmation_name, file_name, "preview", expires_at)
    return {
        "original_content_url": f"{base}?{urlencode({'token': original_token})}",
        "preview_image_url": f"{base}?{urlencode({'token': preview_token})}",
        "expires_at": expires_at,
    }


def _expected_filename(confirmation, image_no: int) -> str:
    day_text = f"{get_datetime(confirmation.confirmation_datetime).day:02d}"
    return f"LINE-POD-{confirmation.sales_order}-{day_text}-{int(image_no):02d}.jpg"


def _assert_relationship(confirmation, file_doc) -> None:
    if confirmation.status != "Confirmed":
        raise frappe.PermissionError("POD is not confirmed")
    if not int(file_doc.is_private or 0):
        raise frappe.PermissionError("POD share endpoint only serves private files")
    if file_doc.attached_to_doctype != confirmation.attachment_doctype:
        raise frappe.PermissionError("POD file target mismatch")
    if file_doc.attached_to_name != confirmation.attachment_name:
        raise frappe.PermissionError("POD file target mismatch")

    first_no = int(confirmation.first_image_no or 0)
    last_no = int(confirmation.last_image_no or 0)
    if first_no <= 0 or last_no < first_no:
        raise frappe.PermissionError("POD image range is invalid")
    expected = {_expected_filename(confirmation, image_no) for image_no in range(first_no, last_no + 1)}
    if file_doc.file_name not in expected:
        raise frappe.PermissionError("File does not belong to this POD")


def _read_file(file_doc) -> bytes:
    path = Path(file_doc.get_full_path())
    if not path.exists() or not path.is_file():
        frappe.throw("POD image file is missing", frappe.DoesNotExistError)
    return path.read_bytes()


def _preview_bytes(raw: bytes) -> bytes:
    with Image.open(io.BytesIO(raw)) as source:
        image = ImageOps.exif_transpose(source).convert("RGB")
        image.thumbnail((1280, 1280), Image.Resampling.LANCZOS)

        quality = 80
        while True:
            out = io.BytesIO()
            image.save(out, format="JPEG", quality=quality, optimize=True)
            data = out.getvalue()
            if len(data) <= PREVIEW_MAX_BYTES:
                return data
            if quality > 45:
                quality -= 10
                continue
            width, height = image.size
            if width <= 480 and height <= 480:
                return data
            image.thumbnail((max(480, int(width * 0.8)), max(480, int(height * 0.8))), Image.Resampling.LANCZOS)
            quality = 70


def _response(data: bytes, *, max_age: int) -> Response:
    return Response(
        data,
        status=200,
        content_type="image/jpeg",
        headers={
            "Cache-Control": f"private, max-age={max(0, int(max_age))}",
            "Content-Disposition": 'inline; filename="pod.jpg"',
            "X-Content-Type-Options": "nosniff",
        },
    )


@frappe.whitelist(allow_guest=True)
def image(token: str):
    payload = _decode_token(token, require_not_expired=True)
    confirmation_name = payload.get("c")
    file_name = payload.get("f")
    if not confirmation_name or not file_name:
        raise frappe.PermissionError("Invalid POD image token")
    if not frappe.db.exists("Delivery Confirmation", confirmation_name):
        raise frappe.PermissionError("POD not found")
    if not frappe.db.exists("File", file_name):
        raise frappe.PermissionError("POD image not found")

    confirmation = frappe.get_doc("Delivery Confirmation", confirmation_name)
    file_doc = frappe.get_doc("File", file_name)
    _assert_relationship(confirmation, file_doc)
    raw = _read_file(file_doc)

    if payload["v"] == "original":
        if len(raw) > ORIGINAL_MAX_BYTES:
            frappe.throw("POD final image exceeds LINE image-message limit", frappe.ValidationError)
        data = raw
    else:
        data = _preview_bytes(raw)

    return _response(data, max_age=int(payload["exp"]) - int(time.time()))


def is_valid_pod_share_url(url: str) -> bool:
    """Return True only for a currently valid URL signed by this site for POD image sharing."""
    try:
        parsed = urlparse(str(url or ""))
        expected_base = urlparse(_public_base_url())
        if parsed.scheme != "https":
            return False
        if parsed.netloc.lower() != expected_base.netloc.lower():
            return False
        if parsed.path != SHARE_PATH:
            return False
        token = (parse_qs(parsed.query).get("token") or [""])[0]
        _decode_token(token, require_not_expired=True)
        return True
    except Exception:
        return False
