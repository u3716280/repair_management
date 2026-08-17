from __future__ import annotations

import mimetypes
import time
from urllib.parse import quote

import frappe
import requests


class LineClient:
    def __init__(self, channel):
        self.channel = frappe.get_doc("LINE Channel", channel)
        self.token = self.channel.get_password("channel_access_token", raise_exception=False)
        if not self.token:
            frappe.throw("Missing LINE Channel Access Token")

    def request(
        self,
        method,
        path,
        api_data=False,
        json_data=None,
        data=None,
        content_type=None,
        accepted=(200, 201, 202, 204),
        timeout=30,
    ):
        headers = {"Authorization": "Bearer " + self.token}
        if content_type:
            headers["Content-Type"] = content_type
        base = "https://api-data.line.me" if api_data else "https://api.line.me"
        response = requests.request(
            method,
            base + path,
            headers=headers,
            json=json_data,
            data=data,
            timeout=timeout,
        )
        if response.status_code not in accepted:
            raise RuntimeError(f"LINE API {response.status_code}: {response.text[:500]}")
        return response

    def reply(self, token, messages):
        if token:
            self.request(
                "POST",
                "/v2/bot/message/reply",
                json_data={"replyToken": token, "messages": messages[:5]},
            )

    def push(self, user, messages):
        self.request(
            "POST",
            "/v2/bot/message/push",
            json_data={"to": user, "messages": messages[:5]},
        )

    def get_content(self, message_id):
        for i in range(5):
            response = self.request(
                "GET",
                f"/v2/bot/message/{message_id}/content",
                api_data=True,
                accepted=(200, 202),
                timeout=120,
            )
            if response.status_code == 200:
                return response.content, response.headers.get(
                    "Content-Type", "application/octet-stream"
                )
            time.sleep(3 * (i + 1))
        raise RuntimeError("Content not ready")

    def verify(self):
        return self.request("GET", "/v2/bot/richmenu/list").json()

    def create_rich_menu(self, payload):
        return self.request(
            "POST",
            "/v2/bot/richmenu",
            json_data=payload,
        ).json()["richMenuId"]

    def upload_image(self, rid, data, filename):
        self.request(
            "POST",
            f"/v2/bot/richmenu/{rid}/content",
            api_data=True,
            data=data,
            content_type=mimetypes.guess_type(filename)[0] or "image/jpeg",
            timeout=120,
        )

    def set_default(self, rid):
        self.request("POST", f"/v2/bot/user/all/richmenu/{rid}")

    def link_user(self, user, rid):
        self.request("POST", f"/v2/bot/user/{user}/richmenu/{rid}")

    def unlink_user(self, user):
        self.request(
            "DELETE",
            f"/v2/bot/user/{user}/richmenu",
            accepted=(200, 204, 404),
        )

    def get_user_menu(self, user):
        response = self.request(
            "GET",
            f"/v2/bot/user/{user}/richmenu",
            accepted=(200, 404),
        )
        return None if response.status_code == 404 else response.json().get("richMenuId")

    def get_profile(self, user_id):
        return self.request("GET", f"/v2/bot/profile/{user_id}").json()

    # Rich Menu Alias -----------------------------------------------------
    # Alias is navigation/deployment mapping only. It does not change
    # LINE Recipient authorization or the existing per-user link flow.

    def get_rich_menu_alias(self, alias_id):
        alias_path = quote(alias_id, safe="")
        response = self.request(
            "GET",
            f"/v2/bot/richmenu/alias/{alias_path}",
            accepted=(200, 404),
        )
        if response.status_code == 404:
            return None
        return response.json()

    def create_rich_menu_alias(self, alias_id, rich_menu_id):
        self.request(
            "POST",
            "/v2/bot/richmenu/alias",
            json_data={
                "richMenuAliasId": alias_id,
                "richMenuId": rich_menu_id,
            },
        )

    def update_rich_menu_alias(self, alias_id, rich_menu_id):
        alias_path = quote(alias_id, safe="")
        self.request(
            "POST",
            f"/v2/bot/richmenu/alias/{alias_path}",
            json_data={"richMenuId": rich_menu_id},
        )

    def delete_rich_menu_alias(self, alias_id):
        alias_path = quote(alias_id, safe="")
        self.request(
            "DELETE",
            f"/v2/bot/richmenu/alias/{alias_path}",
            accepted=(200, 404),
        )

    def upsert_rich_menu_alias(self, alias_id, rich_menu_id):
        current = self.get_rich_menu_alias(alias_id)
        if current is None:
            self.create_rich_menu_alias(alias_id, rich_menu_id)
            return {"status": "created", "richMenuAliasId": alias_id, "richMenuId": rich_menu_id}

        current_rich_menu_id = current.get("richMenuId")
        if current_rich_menu_id == rich_menu_id:
            return {"status": "unchanged", "richMenuAliasId": alias_id, "richMenuId": rich_menu_id}

        self.update_rich_menu_alias(alias_id, rich_menu_id)
        return {
            "status": "updated",
            "richMenuAliasId": alias_id,
            "richMenuId": rich_menu_id,
            "previousRichMenuId": current_rich_menu_id,
        }
