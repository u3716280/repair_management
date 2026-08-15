from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass

import frappe
import requests

LINE_ID_TOKEN_VERIFY_URL = "https://api.line.me/oauth2/v2.1/verify"


@dataclass(frozen=True)
class AttendanceAuthContext:
    channel_name: str
    integration_user: str
    default_company: str
    recipient_name: str
    line_user_id: str


def _get_channel(channel_name: str):
    if not channel_name:
        frappe.throw("LINE MINI App configuration is missing.", frappe.ValidationError)

    channel = frappe.db.get_value(
        "LINE Channel",
        channel_name,
        [
            "name",
            "enabled",
            "integration_user",
            "default_company",
            "mini_app_channel_id",
            "mini_app_liff_id",
        ],
        as_dict=True,
    )
    if not channel or not channel.enabled:
        frappe.throw("LINE Channel is not available.", frappe.PermissionError)
    if not channel.mini_app_channel_id or not channel.mini_app_liff_id:
        frappe.throw("LINE MINI App configuration is incomplete.", frappe.ValidationError)
    if not channel.integration_user or not channel.default_company:
        frappe.throw("LINE attendance configuration is incomplete.", frappe.ValidationError)
    return channel


def _verify_id_token(id_token: str, mini_app_channel_id: str) -> dict:
    if not id_token:
        frappe.throw("LINE Login is required.", frappe.AuthenticationError)

    try:
        response = requests.post(
            LINE_ID_TOKEN_VERIFY_URL,
            data={"id_token": id_token, "client_id": mini_app_channel_id},
            timeout=10,
        )
    except requests.RequestException:
        frappe.throw("Unable to verify LINE Login.", frappe.AuthenticationError)

    if response.status_code != 200:
        frappe.throw("LINE Login verification failed.", frappe.AuthenticationError)

    payload = response.json()
    if not payload.get("sub"):
        frappe.throw("LINE Login verification failed.", frappe.AuthenticationError)
    return payload


def _get_authorized_recipient(channel_name: str, line_user_id: str):
    recipients = frappe.get_all(
        "LINE Recipient",
        filters={
            "line_channel": channel_name,
            "recipient_type": "User",
            "enabled": 1,
            "allow_mark_attendance": 1,
        },
        or_filters={"line_user_id": line_user_id, "recipient_id": line_user_id},
        fields=["name", "line_user_id", "recipient_id"],
        limit_page_length=2,
    )
    if not recipients:
        frappe.throw("ไม่มีสิทธิ์ใช้งาน", frappe.PermissionError)
    if len(recipients) > 1:
        frappe.throw("LINE Recipient configuration is ambiguous.", frappe.ValidationError)
    return recipients[0]


def authenticate(id_token: str, channel_name: str) -> AttendanceAuthContext:
    channel = _get_channel(channel_name)
    payload = _verify_id_token(id_token, channel.mini_app_channel_id)
    line_user_id = payload["sub"]

    #frappe.throw(
    #    frappe.as_json({
    #        "channel_name": channel.name,
    #        "line_user_id_from_login": line_user_id,
    #        "mini_app_channel_id": channel.mini_app_channel_id,
    #    })
    #)


    recipient = _get_authorized_recipient(channel.name, line_user_id)

    if not frappe.db.get_value("User", channel.integration_user, "enabled"):
        frappe.throw("LINE Integration User is disabled.", frappe.PermissionError)

    return AttendanceAuthContext(
        channel_name=channel.name,
        integration_user=channel.integration_user,
        default_company=channel.default_company,
        recipient_name=recipient.name,
        line_user_id=line_user_id,
    )


@contextmanager
def as_integration_user(auth: AttendanceAuthContext):
    previous_user = frappe.session.user
    frappe.set_user(auth.integration_user)
    try:
        yield
    finally:
        frappe.set_user(previous_user)
