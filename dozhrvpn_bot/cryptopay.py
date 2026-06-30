from __future__ import annotations

import json
from typing import Any

import httpx

from dozhrvpn_bot.config import Config
from dozhrvpn_bot.payments import PAYMENT_PROVIDER_CRYPTO_BOT


class CryptoPayError(RuntimeError):
    pass


class CryptoPayClient:
    def __init__(self, config: Config) -> None:
        self.base_url = config.crypto_pay_base_url.rstrip("/")
        self.token = config.crypto_pay_token
        self.currency_type = config.crypto_pay_currency_type
        self.fiat = config.crypto_pay_fiat
        self.asset = config.crypto_pay_asset
        self.accepted_assets = config.crypto_pay_accepted_assets
        self.swap_to = config.crypto_pay_swap_to
        self.expires_in = config.crypto_pay_expires_in
        self.bot_public_username = config.bot_public_username
        self.client = (
            httpx.AsyncClient(
                base_url=f"{self.base_url}/api/",
                headers={"Crypto-Pay-API-Token": self.token},
                timeout=20.0,
            )
            if self.token
            else None
        )

    async def close(self) -> None:
        if self.client is not None:
            await self.client.aclose()

    async def _request(self, method: str, endpoint: str, **kwargs: Any) -> Any:
        if self.client is None:
            raise CryptoPayError("Crypto Bot не настроен.")
        response = await self.client.request(method, endpoint, **kwargs)
        response.raise_for_status()
        payload = response.json()
        if not payload.get("ok"):
            raise CryptoPayError(payload.get("error", "Unknown Crypto Pay API error"))
        return payload.get("result")

    async def create_invoice(
        self,
        amount: str,
        description: str,
        order_id: int,
        user_id: int,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "currency_type": self.currency_type,
            "amount": amount,
            "description": description,
            "hidden_message": "Оплата получена. Вернитесь в бот и выполните проверку статуса.",
            "payload": json.dumps({"order_id": order_id, "user_id": user_id}, ensure_ascii=False),
            "expires_in": self.expires_in,
            "allow_comments": False,
            "allow_anonymous": True,
        }

        if self.currency_type == "fiat":
            if not self.fiat:
                raise CryptoPayError("CRYPTO_PAY_FIAT must be set for fiat invoices.")
            body["fiat"] = self.fiat
            if self.accepted_assets:
                body["accepted_assets"] = self.accepted_assets
        else:
            if not self.asset:
                raise CryptoPayError("CRYPTO_PAY_ASSET must be set for crypto invoices.")
            body["asset"] = self.asset

        if self.swap_to:
            body["swap_to"] = self.swap_to

        if self.bot_public_username:
            body["paid_btn_name"] = "openBot"
            body["paid_btn_url"] = f"https://t.me/{self.bot_public_username}?start=paid_{order_id}"

        invoice = await self._request("POST", "createInvoice", json=body)
        return {
            "provider": PAYMENT_PROVIDER_CRYPTO_BOT,
            "invoice_id": str(invoice["invoice_id"]),
            "label": invoice.get("hash"),
            "pay_url": invoice["bot_invoice_url"],
            "extra_url": invoice.get("mini_app_invoice_url"),
            "web_app_url": invoice.get("web_app_invoice_url"),
            "status": self._normalize_status(invoice.get("status")),
            "provider_status": invoice.get("status"),
            "raw": invoice,
        }

    async def get_invoice_status(self, invoice_id: int) -> dict[str, Any] | None:
        result = await self._request("GET", "getInvoices", params={"invoice_ids": str(invoice_id)})
        if not result:
            return None
        if isinstance(result, list):
            invoice = result[0] if result else None
        else:
            items = result.get("items") or result.get("invoices") or result
            if isinstance(items, list):
                invoice = items[0] if items else None
            else:
                invoice = items
        if invoice is None:
            return None
        return {
            "provider": PAYMENT_PROVIDER_CRYPTO_BOT,
            "invoice_id": str(invoice.get("invoice_id")),
            "status": self._normalize_status(invoice.get("status")),
            "provider_status": invoice.get("status"),
            "raw": invoice,
        }

    @staticmethod
    def _normalize_status(status: str | None) -> str:
        if status == "paid":
            return "paid"
        if status == "expired":
            return "expired"
        return "pending"
