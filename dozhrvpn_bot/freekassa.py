from __future__ import annotations

import hashlib
import hmac
import time
from datetime import UTC, datetime
from typing import Any

import httpx

from dozhrvpn_bot.config import Config
from dozhrvpn_bot.payments import PAYMENT_PROVIDER_FREEKASSA


class FreeKassaError(RuntimeError):
    pass


class FreeKassaClient:
    def __init__(self, config: Config) -> None:
        self.shop_id = config.freekassa_shop_id
        self.api_key = config.freekassa_api_key
        self.base_url = config.freekassa_base_url.rstrip("/")
        self.payment_system_id = config.freekassa_payment_system_id
        self.currency = config.freekassa_currency
        self.payer_email = config.freekassa_payer_email
        self.client = (
            httpx.AsyncClient(
                base_url=f"{self.base_url}/",
                timeout=20.0,
            )
            if self.api_key and self.shop_id
            else None
        )

    async def close(self) -> None:
        if self.client is not None:
            await self.client.aclose()

    async def create_invoice(
        self,
        *,
        amount: str,
        description: str,
        order_id: int,
        user_id: int,
    ) -> dict[str, Any]:
        self._ensure_ready()
        payload = {
            "shopId": self.shop_id,
            "nonce": self._nonce(),
            "paymentId": str(order_id),
            "i": self.payment_system_id,
            "email": self.payer_email,
            "amount": amount,
            "currency": self.currency,
            "us_user": str(user_id),
            "us_order": str(order_id),
            "us_desc": self._sanitize_extra(description),
        }
        response = await self._request("orders/create", payload)
        return {
            "provider": PAYMENT_PROVIDER_FREEKASSA,
            "invoice_id": str(response["orderId"]),
            "label": str(order_id),
            "pay_url": response["location"],
            "extra_url": None,
            "status": "pending",
            "provider_status": "pending",
            "raw": response,
        }

    async def get_invoice_status(self, payment_id: str) -> dict[str, Any] | None:
        self._ensure_ready()
        response = await self._request(
            "orders",
            {
                "shopId": self.shop_id,
                "nonce": self._nonce(),
                "paymentId": payment_id,
            },
        )
        orders = response.get("orders") or []
        if not orders:
            return None

        order = orders[0]
        provider_status = str(order.get("status", "0"))
        paid_at = self._to_iso(order.get("date"))
        return {
            "provider": PAYMENT_PROVIDER_FREEKASSA,
            "invoice_id": str(order.get("fk_order_id") or ""),
            "status": self._normalize_status(provider_status),
            "provider_status": provider_status,
            "paid_at": paid_at if provider_status == "1" else None,
            "raw": order,
        }

    async def _request(self, endpoint: str, payload: dict[str, Any]) -> dict[str, Any]:
        if self.client is None:
            raise FreeKassaError("FreeKassa не настроена.")
        body = dict(payload)
        body["signature"] = self._sign(body)
        response = await self.client.post(endpoint, json=body)
        response.raise_for_status()
        data = response.json()
        if data.get("type") != "success":
            raise FreeKassaError(data.get("message") or "Unknown FreeKassa API error")
        return data

    def _sign(self, payload: dict[str, Any]) -> str:
        if not self.api_key:
            raise FreeKassaError("FreeKassa не настроена: отсутствует API ключ.")
        pieces = [str(payload[key]) for key in sorted(payload)]
        raw = "|".join(pieces).encode("utf-8")
        return hmac.new(self.api_key.encode("utf-8"), raw, hashlib.sha256).hexdigest()

    def _ensure_ready(self) -> None:
        if not self.shop_id:
            raise FreeKassaError("FreeKassa не настроена: отсутствует shop id.")
        if not self.api_key:
            raise FreeKassaError("FreeKassa не настроена: отсутствует API ключ.")
        if not self.payment_system_id:
            raise FreeKassaError("FreeKassa не настроена: отсутствует id платежной системы.")
        if not self.payer_email:
            raise FreeKassaError("FreeKassa не настроена: отсутствует FREEKASSA_PAYER_EMAIL.")

    @staticmethod
    def _nonce() -> int:
        return time.time_ns()

    @staticmethod
    def _normalize_status(status: str) -> str:
        if status == "1":
            return "paid"
        if status in {"6", "8", "9"}:
            return "expired"
        return "pending"

    @staticmethod
    def _sanitize_extra(value: str) -> str:
        allowed = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_")
        return "".join(char if char in allowed else "-" for char in value)[:64] or "vpn-order"

    @staticmethod
    def _to_iso(value: str | None) -> str | None:
        if not value:
            return None
        parsed = datetime.strptime(value, "%Y-%m-%d %H:%M:%S").replace(tzinfo=UTC)
        return parsed.isoformat()
