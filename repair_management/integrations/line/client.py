from __future__ import annotations

from typing import Any

import frappe
import requests

LINE_REPLY_ENDPOINT = "https://api.line.me/v2/bot/message/reply"
DEFAULT_TIMEOUT_SECONDS = 15


def get_line_settings():
    settings = frappe.get_single("LINE Settings")
    if not settings.enabled:
        frappe.throw("LINE integration is disabled in LINE Settings")
    return settings


def get_channel_access_token(settings=None) -> str:
    settings = settings or get_line_settings()
    token = settings.get_password("channel_access_token")
    if not token:
        frappe.throw("LINE Channel Access Token is not configured")
    return token


def reply_messages(reply_token: str, messages: list[dict[str, Any]], settings=None) -> None:
    if not reply_token:
        frappe.throw("LINE reply token is missing")
    if not messages:
        frappe.throw("At least one LINE reply message is required")

    token = get_channel_access_token(settings)
    response = requests.post(
        LINE_REPLY_ENDPOINT,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        json={"replyToken": reply_token, "messages": messages},
        timeout=DEFAULT_TIMEOUT_SECONDS,
    )

    if response.status_code >= 400:
        detail = (response.text or "").strip()[:1000]
        frappe.throw(
            f"LINE reply failed with HTTP {response.status_code}: {detail}",
            title="LINE Messaging API Error",
        )


def reply_location_request(reply_token: str, reference_name: str | None = None, settings=None) -> None:
    document_text = f" สำหรับ {reference_name}" if reference_name else ""
    reply_messages(
        reply_token,
        [
            {
                "type": "text",
                "text": (
                    f"กำลังยืนยันการส่งสินค้า{document_text}\n"
                    "กรุณากดปุ่มด้านล่างเพื่อส่งตำแหน่งปัจจุบัน"
                ),
                "quickReply": {
                    "items": [
                        {
                            "type": "action",
                            "action": {
                                "type": "location",
                                "label": "ส่งตำแหน่ง",
                            },
                        }
                    ]
                },
            }
        ],
        settings=settings,
    )


def reply_text(reply_token: str, text: str, settings=None) -> None:
    reply_messages(
        reply_token,
        [{"type": "text", "text": text}],
        settings=settings,
    )

