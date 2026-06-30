from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlencode

import httpx

from dozhrvpn_bot.config import Config
from dozhrvpn_bot.payments import PAYMENT_PROVIDER_YOOMONEY


class YooMoneyError(RuntimeError):
    pass


class YooMoneyClient:
    def __init__(self, config: Config) -> None:
        self.wallet = config.yoomoney_wallet
        self.token = config.yoomoney_token
        self.quickpay_base_url = config.yoomoney_quickpay_base_url.rstrip("/")
        self.api_base_url = config.yoomoney_api_base_url.rstrip("/")
        self.payment_type = config.yoomoney_payment_type
        self.success_url = config.yoomoney_success_url
        self.client = (
            httpx.AsyncClient(
                base_url=f"{self.api_base_url}/",
                headers={"Authorization": f"Bearer {self.token}"},
                timeout=20.0,
            )
            if self.token
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
        if not self.wallet:
            raise YooMoneyError("YooMoney не настроен: отсутствует номер кошелька.")

        label = f"vpnbot:{order_id}:{user_id}"
        params = {
            "receiver": self.wallet,
            "quickpay-form": "shop",
            "targets": description,
            "paymentType": self.payment_type,
            "sum": amount,
            "label": label,
        }
        if self.success_url:
            params["successURL"] = self.success_url

        pay_url = f"{self.quickpay_base_url}?{urlencode(params)}"
        payload = {
            "label": label,
            "pay_url": pay_url,
            "payment_type": self.payment_type,
            "receiver": self.wallet,
            "amount": amount,
            "description": description,
        }
        return {
            "provider": PAYMENT_PROVIDER_YOOMONEY,
            "invoice_id": label,
            "label": label,
            "pay_url": pay_url,
            "extra_url": None,
            "status": "pending",
            "provider_status": "pending",
            "raw": payload,
        }

    async def get_invoice_status(self, label: str) -> dict[str, Any] | None:
        if self.client is None:
            raise YooMoneyError("YooMoney не настроен: отсутствует OAuth токен.")

        response = await self.client.post(
            "operation-history",
            data={"label": label, "records": "10", "details": "true"},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        response.raise_for_status()
        payload = response.json()
        if payload.get("error"):
            raise YooMoneyError(payload.get("error_description") or payload["error"])

        operations = payload.get("operations") or []
        if not operations:
            return {
                "provider": PAYMENT_PROVIDER_YOOMONEY,
                "invoice_id": label,
                "status": "pending",
                "provider_status": "pending",
                "raw": payload,
            }

        operation = next(
            (item for item in operations if str(item.get("status")) == "success"),
            operations[0],
        )
        provider_status = str(operation.get("status") or "pending")
        paid_at = operation.get("datetime")
        if paid_at:
            paid_at = self._to_iso(paid_at)
        return {
            "provider": PAYMENT_PROVIDER_YOOMONEY,
            "invoice_id": label,
            "status": self._normalize_status(provider_status),
            "provider_status": provider_status,
            "paid_at": paid_at,
            "raw": operation,
        }

    @staticmethod
    def _normalize_status(status: str) -> str:
        if status == "success":
            return "paid"
        if status in {"refused", "canceled"}:
            return "expired"
        return "pending"

    @staticmethod
    def _to_iso(value: str) -> str:
        normalized = value.replace("Z", "+00:00")
        parsed = datetime.fromisoformat(normalized)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC).isoformat()
