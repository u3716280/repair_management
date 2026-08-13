from __future__ import annotations

from typing import Any
from urllib.parse import urlencode

import frappe
import requests

LINE_REPLY_ENDPOINT = "https://api.line.me/v2/bot/message/reply"
LINE_PUSH_ENDPOINT = "https://api.line.me/v2/bot/message/push"
LINE_CONTENT_ENDPOINT = "https://api-data.line.me/v2/bot/message/{message_id}/content"
LINE_CONTENT_PREVIEW_ENDPOINT = "https://api-data.line.me/v2/bot/message/{message_id}/content/preview"
DEFAULT_TIMEOUT_SECONDS = 20
CONTENT_TIMEOUT_SECONDS = 45


def get_line_account(account_or_name):
    if not account_or_name:
        frappe.throw("LINE Account is required")

    account = (
        frappe.get_doc("LINE Account", account_or_name)
        if isinstance(account_or_name, str)
        else account_or_name
    )
    if not account.enabled:
        frappe.throw(f"LINE Account {account.name} is disabled")
    return account


def get_channel_access_token(account_or_name) -> str:
    account = get_line_account(account_or_name)
    token = account.get_password("channel_access_token")
    if not token:
        frappe.throw(f"Channel Access Token is missing in LINE Account {account.name}")
    return token


def _headers(account_or_name, *, content_type: str | None = "application/json") -> dict[str, str]:
    headers = {"Authorization": f"Bearer {get_channel_access_token(account_or_name)}"}
    if content_type:
        headers["Content-Type"] = content_type
    return headers


def _raise_line_error(response: requests.Response, operation: str) -> None:
    if response.status_code < 400:
        return
    detail = (response.text or "").strip()[:2000]
    frappe.throw(
        f"{operation} failed with HTTP {response.status_code}: {detail}",
        title="LINE Messaging API Error",
    )


def reply_messages(reply_token: str, messages: list[dict[str, Any]], account_or_name) -> None:
    if not reply_token:
        frappe.throw("LINE reply token is missing")
    if not messages:
        frappe.throw("At least one LINE reply message is required")

    response = requests.post(
        LINE_REPLY_ENDPOINT,
        headers=_headers(account_or_name),
        json={"replyToken": reply_token, "messages": messages[:5]},
        timeout=DEFAULT_TIMEOUT_SECONDS,
    )
    _raise_line_error(response, "LINE reply")


def push_messages(
    to: str,
    messages: list[dict[str, Any]],
    account_or_name,
    *,
    retry_key: str | None = None,
) -> tuple[int, str]:
    if not to:
        frappe.throw("LINE push destination is missing")
    if not messages:
        frappe.throw("At least one LINE push message is required")

    headers = _headers(account_or_name)
    if retry_key:
        headers["X-Line-Retry-Key"] = retry_key

    response = requests.post(
        LINE_PUSH_ENDPOINT,
        headers=headers,
        json={"to": to, "messages": messages[:5]},
        timeout=DEFAULT_TIMEOUT_SECONDS,
    )
    _raise_line_error(response, "LINE push")
    return response.status_code, (response.text or "")[:2000]


def download_message_content(message_id: str, account_or_name) -> tuple[bytes, str]:
    if not message_id:
        frappe.throw("LINE image message ID is missing")

    response = requests.get(
        LINE_CONTENT_ENDPOINT.format(message_id=message_id),
        headers=_headers(account_or_name, content_type=None),
        timeout=CONTENT_TIMEOUT_SECONDS,
    )
    _raise_line_error(response, "LINE content download")
    content_type = (response.headers.get("Content-Type") or "application/octet-stream").split(";", 1)[0].lower()
    return response.content, content_type


def download_message_preview(message_id: str, account_or_name) -> tuple[bytes, str]:
    if not message_id:
        frappe.throw("LINE image message ID is missing")

    response = requests.get(
        LINE_CONTENT_PREVIEW_ENDPOINT.format(message_id=message_id),
        headers=_headers(account_or_name, content_type=None),
        timeout=CONTENT_TIMEOUT_SECONDS,
    )
    _raise_line_error(response, "LINE preview download")
    content_type = (response.headers.get("Content-Type") or "image/jpeg").split(";", 1)[0].lower()
    return response.content, content_type


def reply_location_request(
    reply_token: str,
    reference_name: str | None,
    account_or_name,
    *,
    action_label: str = "ยืนยันสถานะ",
) -> None:
    reference_text = f"\nเอกสาร: {reference_name}" if reference_name else ""
    reply_messages(
        reply_token,
        [
            {
                "type": "text",
                "text": f"{action_label}{reference_text}\nกรุณากดปุ่มด้านล่างเพื่อส่งตำแหน่งปัจจุบัน",
                "quickReply": {
                    "items": [
                        {
                            "type": "action",
                            "action": {"type": "location", "label": "ส่งตำแหน่ง"},
                        }
                    ]
                },
            }
        ],
        account_or_name,
    )


def reply_image_request(
    reply_token: str,
    reference_name: str | None,
    account_or_name,
    *,
    action_label: str = "ยืนยันสถานะ",
    location_received: bool = True,
) -> None:
    reference_text = f"\nเอกสาร: {reference_name}" if reference_name else ""
    prefix = "รับตำแหน่งเรียบร้อยแล้ว\n" if location_received else ""
    reply_messages(
        reply_token,
        [
            {
                "type": "text",
                "text": f"{prefix}{action_label}{reference_text}\nกรุณาถ่ายรูปหรือเลือกรูป",
                "quickReply": {
                    "items": [
                        {
                            "type": "action",
                            "action": {"type": "camera", "label": "ถ่ายรูป"},
                        },
                        {
                            "type": "action",
                            "action": {"type": "cameraRoll", "label": "เลือกรูป"},
                        },
                    ]
                },
            }
        ],
        account_or_name,
    )


def reply_reference_request(
    reply_token: str,
    reference_doctype: str,
    account_or_name,
    *,
    prompt: str | None = None,
) -> None:
    message = prompt or f"กรุณาส่งเลขที่ {reference_doctype} ที่ต้องการอ้างอิง"
    reply_text(reply_token, message, account_or_name)


def reply_pending_media_classification(
    reply_token: str,
    pending_media_name: str,
    actions: list[dict[str, str]],
    account_or_name,
) -> None:
    items: list[dict[str, Any]] = []
    for action in actions[:12]:
        action_code = (action.get("action_code") or "").strip()
        label = (action.get("action_label") or action_code or "ระบุประเภท")[:20]
        if not action_code:
            continue
        data = urlencode(
            {
                "action": "classify_media",
                "media": pending_media_name,
                "target_action": action_code,
            }
        )
        items.append(
            {
                "type": "action",
                "action": {
                    "type": "postback",
                    "label": label,
                    "data": data,
                    "displayText": label,
                },
            }
        )

    items.append(
        {
            "type": "action",
            "action": {
                "type": "postback",
                "label": "ยกเลิกรูปนี้",
                "data": urlencode({"action": "discard_media", "media": pending_media_name}),
                "displayText": "ยกเลิกรูปนี้",
            },
        }
    )

    reply_messages(
        reply_token,
        [
            {
                "type": "text",
                "text": "ได้รับรูปแล้ว แต่ยังไม่ทราบว่ารูปนี้ใช้กับรายการใด กรุณาเลือกประเภท",
                "quickReply": {"items": items[:13]},
            }
        ],
        account_or_name,
    )


def reply_text(reply_token: str, text: str, account_or_name) -> None:
    reply_messages(reply_token, [{"type": "text", "text": text}], account_or_name)
