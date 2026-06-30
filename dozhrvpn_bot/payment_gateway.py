from __future__ import annotations

from typing import Any

from dozhrvpn_bot.cryptopay import CryptoPayClient, CryptoPayError
from dozhrvpn_bot.freekassa import FreeKassaClient, FreeKassaError
from dozhrvpn_bot.payments import (
    PAYMENT_PROVIDER_CRYPTO_BOT,
    PAYMENT_PROVIDER_FREEKASSA,
    PAYMENT_PROVIDER_YOOMONEY,
)
from dozhrvpn_bot.yoomoney import YooMoneyClient, YooMoneyError


class PaymentGatewayError(RuntimeError):
    pass


class PaymentGateway:
    def __init__(
        self,
        *,
        crypto_bot: CryptoPayClient,
        yoomoney: YooMoneyClient,
        freekassa: FreeKassaClient,
    ) -> None:
        self.crypto_bot = crypto_bot
        self.yoomoney = yoomoney
        self.freekassa = freekassa

    async def create_invoice(
        self,
        provider: str,
        *,
        amount: str,
        description: str,
        order_id: int,
        user_id: int,
    ) -> dict[str, Any]:
        try:
            if provider == PAYMENT_PROVIDER_CRYPTO_BOT:
                return await self.crypto_bot.create_invoice(
                    amount=amount,
                    description=description,
                    order_id=order_id,
                    user_id=user_id,
                )
            if provider == PAYMENT_PROVIDER_YOOMONEY:
                return await self.yoomoney.create_invoice(
                    amount=amount,
                    description=description,
                    order_id=order_id,
                    user_id=user_id,
                )
            if provider == PAYMENT_PROVIDER_FREEKASSA:
                return await self.freekassa.create_invoice(
                    amount=amount,
                    description=description,
                    order_id=order_id,
                    user_id=user_id,
                )
        except (CryptoPayError, YooMoneyError, FreeKassaError) as exc:
            raise PaymentGatewayError(str(exc)) from exc

        raise PaymentGatewayError(f"Неизвестный провайдер оплаты: {provider}")

    async def get_invoice_status(
        self,
        provider: str,
        *,
        invoice_id: str | None,
        label: str | None,
    ) -> dict[str, Any] | None:
        try:
            if provider == PAYMENT_PROVIDER_CRYPTO_BOT:
                if not invoice_id:
                    return None
                return await self.crypto_bot.get_invoice_status(int(invoice_id))
            if provider == PAYMENT_PROVIDER_YOOMONEY:
                if not label:
                    return None
                return await self.yoomoney.get_invoice_status(label)
            if provider == PAYMENT_PROVIDER_FREEKASSA:
                lookup = label or invoice_id
                if not lookup:
                    return None
                return await self.freekassa.get_invoice_status(lookup)
        except (CryptoPayError, YooMoneyError, FreeKassaError) as exc:
            raise PaymentGatewayError(str(exc)) from exc

        raise PaymentGatewayError(f"Неизвестный провайдер оплаты: {provider}")
