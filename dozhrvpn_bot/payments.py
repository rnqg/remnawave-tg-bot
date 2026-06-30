from __future__ import annotations

from collections.abc import Sequence

from dozhrvpn_bot.config import Config

PAYMENT_PROVIDER_CRYPTO_BOT = "crypto_bot"
PAYMENT_PROVIDER_YOOMONEY = "yoomoney"
PAYMENT_PROVIDER_FREEKASSA = "freekassa"

PAYMENT_PROVIDER_LABELS = {
    PAYMENT_PROVIDER_CRYPTO_BOT: "Crypto Bot",
    PAYMENT_PROVIDER_YOOMONEY: "YooMoney",
    PAYMENT_PROVIDER_FREEKASSA: "FreeKassa",
}


def payment_provider_label(provider: str) -> str:
    return PAYMENT_PROVIDER_LABELS.get(provider, provider)


def payment_provider_enabled(config: Config, provider: str) -> bool:
    if provider == PAYMENT_PROVIDER_CRYPTO_BOT:
        return config.crypto_pay_enabled
    if provider == PAYMENT_PROVIDER_YOOMONEY:
        return config.yoomoney_enabled
    if provider == PAYMENT_PROVIDER_FREEKASSA:
        return config.freekassa_enabled
    return False


def payment_provider_configured(config: Config, provider: str) -> bool:
    if provider == PAYMENT_PROVIDER_CRYPTO_BOT:
        return bool(config.crypto_pay_token)
    if provider == PAYMENT_PROVIDER_YOOMONEY:
        return bool(config.yoomoney_wallet and config.yoomoney_token)
    if provider == PAYMENT_PROVIDER_FREEKASSA:
        return bool(
            config.freekassa_shop_id
            and config.freekassa_api_key
            and config.freekassa_payment_system_id
            and config.freekassa_payer_email
        )
    return False


def payment_provider_is_available(config: Config, provider: str) -> bool:
    return payment_provider_enabled(config, provider) and payment_provider_configured(config, provider)


def payment_provider_states(config: Config) -> tuple[dict[str, object], ...]:
    providers = (
        PAYMENT_PROVIDER_CRYPTO_BOT,
        PAYMENT_PROVIDER_YOOMONEY,
        PAYMENT_PROVIDER_FREEKASSA,
    )
    return tuple(
        {
            "key": provider,
            "title": payment_provider_label(provider),
            "enabled": payment_provider_enabled(config, provider),
            "configured": payment_provider_configured(config, provider),
            "available": payment_provider_is_available(config, provider),
        }
        for provider in providers
    )


def available_payment_providers(config: Config) -> tuple[str, ...]:
    return tuple(
        str(item["key"])
        for item in payment_provider_states(config)
        if bool(item["available"])
    )


def has_available_payment_providers(config: Config) -> bool:
    return bool(available_payment_providers(config))


def payment_provider_choices(config: Config) -> tuple[tuple[str, str], ...]:
    return tuple(
        (str(item["key"]), str(item["title"]))
        for item in payment_provider_states(config)
        if bool(item["available"])
    )


def build_payment_status_line(statuses: Sequence[dict[str, object]]) -> str:
    lines: list[str] = []
    for item in statuses:
        title = str(item["title"])
        enabled = bool(item["enabled"])
        configured = bool(item["configured"])
        if enabled and configured:
            state = "включен"
        elif enabled and not configured:
            state = "включен, но не настроен"
        elif configured:
            state = "выключен"
        else:
            state = "не настроен"
        lines.append(f"{title}: <b>{state}</b>")
    return "\n".join(lines)
