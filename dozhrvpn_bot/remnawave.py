from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from dozhrvpn_bot.config import Config


class RemnawaveError(RuntimeError):
    pass


class RemnawaveClient:
    def __init__(self, config: Config) -> None:
        self.base_url = self._normalize_base_url(config.remnawave_base_url)
        self.login_name = config.remnawave_login
        self.password = config.remnawave_password
        self.caddy_token = config.remnawave_caddy_token
        self.tag = config.remnawave_tag
        self.client = httpx.AsyncClient(base_url=self.base_url, timeout=20.0)
        self._bearer_token = config.remnawave_api_token

    async def close(self) -> None:
        await self.client.aclose()

    @staticmethod
    def _normalize_base_url(base_url: str) -> str:
        base_url = base_url.rstrip("/")
        if not base_url.endswith("/api"):
            base_url = f"{base_url}/api"
        return base_url

    async def _ensure_token(self) -> str:
        if self._bearer_token:
            return self._bearer_token
        if not self.login_name or not self.password:
            raise RemnawaveError(
                "Configure REMNAWAVE_API_TOKEN or REMNAWAVE_LOGIN/REMNAWAVE_PASSWORD."
            )
        response = await self.client.post(
            "/auth/login",
            json={"username": self.login_name, "password": self.password},
        )
        response.raise_for_status()
        payload = response.json()
        token = payload.get("response", {}).get("accessToken")
        if not token:
            raise RemnawaveError("Remnawave login succeeded without access token.")
        self._bearer_token = token
        return token

    async def _request(self, method: str, endpoint: str, **kwargs: Any) -> Any:
        headers = kwargs.pop("headers", {})
        token = await self._ensure_token()
        headers["Authorization"] = token if token.startswith("Bearer ") else f"Bearer {token}"
        if self.caddy_token:
            headers["X-Api-Key"] = self.caddy_token
        response = await self.client.request(method, endpoint, headers=headers, **kwargs)
        response.raise_for_status()
        payload = response.json()
        return payload.get("response")

    async def get_user_by_telegram_id(self, telegram_id: int) -> dict[str, Any] | None:
        response = await self._request("GET", f"/users/by-telegram-id/{telegram_id}")
        if not response:
            return None
        if isinstance(response, list):
            users = sorted(response, key=lambda item: item.get("expireAt") or "", reverse=True)
            return users[0] if users else None
        return response

    async def get_user_by_uuid(self, uuid: str) -> dict[str, Any] | None:
        try:
            return await self._request("GET", f"/users/{uuid}")
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                return None
            raise

    async def create_user(
        self,
        telegram_id: int,
        username: str,
        expire_at: datetime,
        description: str,
    ) -> dict[str, Any]:
        body = {
            "username": username,
            "status": "ACTIVE",
            "expireAt": expire_at.astimezone(UTC).isoformat(),
            "telegramId": telegram_id,
            "description": description,
            "trafficLimitBytes": 0,
        }
        if self.tag:
            body["tag"] = self.tag
        return await self._request("POST", "/users", json=body)

    async def update_user(
        self,
        uuid: str,
        expire_at: datetime,
        telegram_id: int,
        description: str,
    ) -> dict[str, Any]:
        body = {
            "uuid": uuid,
            "status": "ACTIVE",
            "expireAt": expire_at.astimezone(UTC).isoformat(),
            "telegramId": telegram_id,
            "description": description,
        }
        if self.tag:
            body["tag"] = self.tag
        return await self._request("PATCH", "/users", json=body)

    async def provision_subscription(
        self,
        *,
        telegram_id: int,
        local_uuid: str | None,
        current_expires_at: datetime | None,
        subscription_days: int,
        username_hint: str | None,
    ) -> dict[str, Any]:
        existing = None
        if local_uuid:
            existing = await self.get_user_by_uuid(local_uuid)
        if existing is None:
            existing = await self.get_user_by_telegram_id(telegram_id)

        now = datetime.now(UTC)
        base_expire = now
        if current_expires_at and current_expires_at > now:
            base_expire = current_expires_at
        if existing and existing.get("expireAt"):
            remote_expire = datetime.fromisoformat(existing["expireAt"])
            if remote_expire > base_expire:
                base_expire = remote_expire

        new_expire = base_expire + timedelta(days=subscription_days)
        description = f"VPN Telegram user {telegram_id}"

        if existing:
            return await self.update_user(
                uuid=existing["uuid"],
                expire_at=new_expire,
                telegram_id=telegram_id,
                description=description,
            )

        username = self._build_username(telegram_id, username_hint)
        return await self.create_user(
            telegram_id=telegram_id,
            username=username,
            expire_at=new_expire,
            description=description,
        )

    @staticmethod
    def _build_username(telegram_id: int, username_hint: str | None) -> str:
        if username_hint:
            sanitized = "".join(ch for ch in username_hint if ch.isalnum() or ch in {"_", "-"})
            if len(sanitized) >= 6:
                return sanitized[:36]
        return f"vpn_{telegram_id}"[:36]
