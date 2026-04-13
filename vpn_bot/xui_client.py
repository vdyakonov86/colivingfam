from __future__ import annotations

import json
import logging
import secrets
import uuid
from typing import Any
from urllib.parse import urljoin

import httpx

from vpn_bot.config import Settings

logger = logging.getLogger(__name__)


class XuiApiError(Exception):
    pass


def _rand_sub_id(length: int = 16) -> str:
    alphabet = "abcdefghijklmnopqrstuvwxyz0123456789"
    return "".join(secrets.choice(alphabet) for _ in range(length))


class XuiClient:
    """Minimal 3x-ui panel client (session cookie, VLESS add/del client)."""

    def __init__(self, settings: Settings) -> None:
        self._s = settings
        self._client: httpx.AsyncClient | None = None

    @property
    def base(self) -> str:
        return self._s.xui_base_url.rstrip("/")

    async def _ensure_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.base,
                verify=self._s.xui_verify_tls,
                timeout=httpx.Timeout(60.0),
                follow_redirects=True,
            )
        return self._client

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def login(self) -> None:
        client = await self._ensure_client()
        resp = await client.post(
            "/login",
            data={
                "username": self._s.xui_username,
                "password": self._s.xui_password,
            },
        )
        if resp.status_code >= 400:
            raise XuiApiError(f"login HTTP {resp.status_code}: {resp.text[:500]}")
        try:
            data = resp.json()
        except json.JSONDecodeError as e:
            raise XuiApiError(f"login invalid JSON: {e}") from e
        if not data.get("success", False):
            raise XuiApiError(f"login failed: {data.get('msg', data)}")

    async def _post_json(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        client = await self._ensure_client()
        resp = await client.post(path, json=payload)
        if resp.status_code == 401 or resp.status_code == 404:
            await self.login()
            resp = await client.post(path, json=payload)
        text = resp.text.strip()
        if not text:
            if resp.status_code < 400:
                return {"success": True}
            raise XuiApiError(f"{path} empty body, HTTP {resp.status_code}")
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            raise XuiApiError(f"{path} non-JSON ({resp.status_code}): {text[:500]}")
        if resp.status_code >= 400 and not data.get("success"):
            raise XuiApiError(f"{path} HTTP {resp.status_code}: {data}")
        return data

    def subscription_url(self, sub_id: str) -> str:
        sub_id = sub_id.strip()
        base_sub = (self._s.subscription_base_url or "").strip()
        if base_sub:
            return urljoin(base_sub.rstrip("/") + "/", sub_id)
        return urljoin(self.base + "/", f"sub/{sub_id}")

    def new_vless_client_row(self, email: str, *, tg_id: int = 0) -> tuple[dict[str, Any], str, str]:
        """Build one VLESS client object for 3x-ui. Returns (client_dict, client_uuid, sub_id)."""
        client_uuid = str(uuid.uuid4())
        sub_id = _rand_sub_id(16)
        fl = self._s.xui_vless_flow or ""
        client_obj: dict[str, Any] = {
            "id": client_uuid,
            "email": email,
            "security": "",
            "password": "",
            "flow": fl,
            "encryption": "none",
            "limitIp": 0,
            "totalGB": 0,
            "expiryTime": 0,
            "enable": True,
            "tgId": tg_id,
            "subId": sub_id,
            "comment": "",
        }
        return client_obj, client_uuid, sub_id

    async def add_vless_client(
        self,
        email: str,
        *,
        tg_id: int = 0,
    ) -> tuple[str, str, str]:
        """Create client in configured inbound. Returns (email, client_uuid, sub_id)."""
        client_obj, client_uuid, sub_id = self.new_vless_client_row(email, tg_id=tg_id)
        settings_str = json.dumps({"clients": [client_obj]}, separators=(",", ":"))
        payload: dict[str, Any] = {
            "id": self._s.xui_inbound_id,
            "settings": settings_str,
        }
        data = await self._post_json("/panel/api/inbounds/addClient", payload)
        if data.get("success") is False:
            raise XuiApiError(data.get("msg", data))
        return email, client_uuid, sub_id

    async def delete_client(self, client_uuid: str) -> None:
        path = f"/panel/api/inbounds/{self._s.xui_inbound_id}/delClient/{client_uuid}"
        client = await self._ensure_client()
        resp = await client.post(path)
        if resp.status_code in (401, 404):
            await self.login()
            resp = await client.post(path)
        text = resp.text.strip()
        if not text:
            if resp.status_code < 400:
                return
            raise XuiApiError(f"delClient empty body HTTP {resp.status_code}")
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            raise XuiApiError(f"delClient non-JSON: {text[:500]}")
        if not data.get("success", False):
            raise XuiApiError(data.get("msg", data))
