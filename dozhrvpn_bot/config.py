from __future__ import annotations

import json
import os
from dataclasses import dataclass, replace
from decimal import Decimal, InvalidOperation
from typing import Any

from dotenv import load_dotenv


@dataclass(frozen=True, slots=True)
class Plan:
    key: str
    title: str
    days: int
    price_rub: Decimal
    badge: str = ""


@dataclass(frozen=True, slots=True)
class Config:
    bot_token: str
    bot_public_username: str | None
    admin_ids: tuple[int, ...]
    database_url: str
    bypass_channel_gate: bool
    brand_name: str
    required_channel_id: str
    required_channel_url: str
    support_url: str
    support_label: str
    partner_program_text: str
    referral_reward_days: int
    plans: tuple[Plan, ...]
    remnawave_base_url: str
    remnawave_api_token: str | None
    remnawave_login: str | None
    remnawave_password: str | None
    remnawave_caddy_token: str | None
    remnawave_tag: str | None
    crypto_pay_token: str | None
    crypto_pay_base_url: str
    crypto_pay_currency_type: str
    crypto_pay_fiat: str | None
    crypto_pay_asset: str | None
    crypto_pay_accepted_assets: str | None
    crypto_pay_swap_to: str | None
    crypto_pay_expires_in: int
    crypto_pay_enabled: bool
    yoomoney_wallet: str | None
    yoomoney_token: str | None
    yoomoney_quickpay_base_url: str
    yoomoney_api_base_url: str
    yoomoney_payment_type: str
    yoomoney_success_url: str | None
    yoomoney_enabled: bool
    freekassa_shop_id: int | None
    freekassa_api_key: str | None
    freekassa_base_url: str
    freekassa_payment_system_id: int | None
    freekassa_currency: str
    freekassa_payer_email: str | None
    freekassa_enabled: bool
    instruction_android_url: str | None
    instruction_ios_url: str | None
    instruction_windows_url: str | None
    instruction_macos_url: str | None


def _parse_admin_ids(raw: str | None) -> tuple[int, ...]:
    if not raw:
        return tuple()
    return tuple(int(chunk.strip()) for chunk in raw.split(",") if chunk.strip())


def _parse_bool(raw: str | None, default: bool) -> bool:
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _parse_plans(raw: str | None) -> tuple[Plan, ...]:
    if not raw:
        raw = json.dumps(
            [
                {
                    "key": "month",
                    "title": "1 месяц",
                    "days": 30,
                    "price_rub": "399",
                    "badge": "🔥 Хит",
                },
                {
                    "key": "quarter",
                    "title": "3 месяца",
                    "days": 90,
                    "price_rub": "999",
                    "badge": "💎 Выгодно",
                },
            ]
        )

    try:
        items = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("PLANS_JSON must be a valid JSON array.") from exc

    plans: list[Plan] = []
    for item in items:
        try:
            plans.append(
                Plan(
                    key=str(item["key"]),
                    title=str(item["title"]),
                    days=int(item["days"]),
                    price_rub=Decimal(str(item["price_rub"])),
                    badge=str(item.get("badge", "")),
                )
            )
        except (KeyError, TypeError, ValueError, InvalidOperation) as exc:
            raise ValueError(f"Invalid plan config: {item!r}") from exc

    if not plans:
        raise ValueError("PLANS_JSON must contain at least one plan.")

    return tuple(plans)


def serialize_plans(plans: tuple[Plan, ...]) -> str:
    return json.dumps(
        [
            {
                "key": plan.key,
                "title": plan.title,
                "days": plan.days,
                "price_rub": str(plan.price_rub),
                "badge": plan.badge,
            }
            for plan in plans
        ],
        ensure_ascii=False,
    )


def apply_runtime_settings(config: Config, settings: dict[str, str]) -> Config:
    brand_name = settings.get("brand_name") or config.brand_name
    required_channel_id = settings.get("required_channel_id") or config.required_channel_id
    required_channel_url = settings.get("required_channel_url") or config.required_channel_url
    referral_reward_days_raw = settings.get("referral_reward_days")
    plans_raw = settings.get("plans_json")
    crypto_pay_enabled_raw = settings.get("crypto_pay_enabled")
    yoomoney_enabled_raw = settings.get("yoomoney_enabled")
    freekassa_enabled_raw = settings.get("freekassa_enabled")

    referral_reward_days = config.referral_reward_days
    if referral_reward_days_raw:
        try:
            referral_reward_days = int(referral_reward_days_raw)
        except ValueError:
            referral_reward_days = config.referral_reward_days

    plans = config.plans
    if plans_raw:
        try:
            plans = _parse_plans(plans_raw)
        except ValueError:
            plans = config.plans

    return replace(
        config,
        brand_name=brand_name,
        required_channel_id=required_channel_id,
        required_channel_url=required_channel_url,
        referral_reward_days=referral_reward_days,
        plans=plans,
        crypto_pay_enabled=_parse_bool(crypto_pay_enabled_raw, config.crypto_pay_enabled),
        yoomoney_enabled=_parse_bool(yoomoney_enabled_raw, config.yoomoney_enabled),
        freekassa_enabled=_parse_bool(freekassa_enabled_raw, config.freekassa_enabled),
    )


def parse_campaign_buttons(raw: str | None) -> list[list[dict[str, Any]]]:
    if not raw:
        return []
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(payload, list):
        return []
    rows: list[list[dict[str, Any]]] = []
    for row in payload:
        if not isinstance(row, list):
            continue
        parsed_row: list[dict[str, Any]] = []
        for button in row:
            if not isinstance(button, dict):
                continue
            text = str(button.get("text") or "").strip()
            url = str(button.get("url") or "").strip()
            if text and url:
                parsed_row.append({"text": text, "url": url})
        if parsed_row:
            rows.append(parsed_row)
    return rows


def load_config() -> Config:
    load_dotenv()

    bot_token = os.getenv("BOT_TOKEN")
    if not bot_token:
        raise ValueError("BOT_TOKEN is required.")

    database_url = (os.getenv("DATABASE_URL") or "").strip()
    if not database_url:
        raise ValueError("DATABASE_URL is required.")

    bypass_channel_gate = _parse_bool(os.getenv("BYPASS_CHANNEL_GATE"), False)

    required_channel_id = os.getenv("REQUIRED_CHANNEL_ID")
    required_channel_url = os.getenv("REQUIRED_CHANNEL_URL")
    if not required_channel_id or not required_channel_url:
        if bypass_channel_gate:
            required_channel_id = required_channel_id or "@your_channel"
            required_channel_url = required_channel_url or "https://t.me/your_channel"
        else:
            raise ValueError("REQUIRED_CHANNEL_ID and REQUIRED_CHANNEL_URL are required.")

    remnawave_base_url = os.getenv("REMNAWAVE_BASE_URL")
    if not remnawave_base_url:
        raise ValueError("REMNAWAVE_BASE_URL is required.")

    return Config(
        bot_token=bot_token,
        bot_public_username=(os.getenv("BOT_PUBLIC_USERNAME") or "").lstrip("@") or None,
        admin_ids=_parse_admin_ids(os.getenv("ADMIN_IDS")),
        database_url=database_url,
        bypass_channel_gate=bypass_channel_gate,
        brand_name=os.getenv("BRAND_NAME", "VPN Bot"),
        required_channel_id=required_channel_id,
        required_channel_url=required_channel_url,
        support_url=os.getenv("SUPPORT_URL", "https://t.me/your_support"),
        support_label=os.getenv("SUPPORT_LABEL", "@your_support"),
        partner_program_text=os.getenv(
            "PARTNER_PROGRAM_TEXT",
            "Партнерская программа доступна по запросу через поддержку.",
        ),
        referral_reward_days=int(os.getenv("REFERRAL_REWARD_DAYS", "7")),
        plans=_parse_plans(os.getenv("PLANS_JSON")),
        remnawave_base_url=remnawave_base_url,
        remnawave_api_token=os.getenv("REMNAWAVE_API_TOKEN") or None,
        remnawave_login=os.getenv("REMNAWAVE_LOGIN") or None,
        remnawave_password=os.getenv("REMNAWAVE_PASSWORD") or None,
        remnawave_caddy_token=os.getenv("REMNAWAVE_CADDY_TOKEN") or None,
        remnawave_tag=os.getenv("REMNAWAVE_TAG") or None,
        crypto_pay_token=os.getenv("CRYPTO_PAY_TOKEN") or None,
        crypto_pay_base_url=os.getenv("CRYPTO_PAY_BASE_URL", "https://pay.crypt.bot"),
        crypto_pay_currency_type=os.getenv("CRYPTO_PAY_CURRENCY_TYPE", "fiat"),
        crypto_pay_fiat=os.getenv("CRYPTO_PAY_FIAT") or None,
        crypto_pay_asset=os.getenv("CRYPTO_PAY_ASSET") or None,
        crypto_pay_accepted_assets=os.getenv("CRYPTO_PAY_ACCEPTED_ASSETS") or None,
        crypto_pay_swap_to=os.getenv("CRYPTO_PAY_SWAP_TO") or None,
        crypto_pay_expires_in=int(os.getenv("CRYPTO_PAY_EXPIRES_IN", "3600")),
        crypto_pay_enabled=_parse_bool(os.getenv("CRYPTO_PAY_ENABLED"), True),
        yoomoney_wallet=os.getenv("YOOMONEY_WALLET") or None,
        yoomoney_token=os.getenv("YOOMONEY_TOKEN") or None,
        yoomoney_quickpay_base_url=os.getenv("YOOMONEY_QUICKPAY_BASE_URL", "https://yoomoney.ru/quickpay/confirm"),
        yoomoney_api_base_url=os.getenv("YOOMONEY_API_BASE_URL", "https://yoomoney.ru/api"),
        yoomoney_payment_type=os.getenv("YOOMONEY_PAYMENT_TYPE", "AC"),
        yoomoney_success_url=os.getenv("YOOMONEY_SUCCESS_URL") or None,
        yoomoney_enabled=_parse_bool(os.getenv("YOOMONEY_ENABLED"), False),
        freekassa_shop_id=int(os.getenv("FREEKASSA_SHOP_ID")) if os.getenv("FREEKASSA_SHOP_ID") else None,
        freekassa_api_key=os.getenv("FREEKASSA_API_KEY") or None,
        freekassa_base_url=os.getenv("FREEKASSA_BASE_URL", "https://api.fk.life/v1"),
        freekassa_payment_system_id=(
            int(os.getenv("FREEKASSA_PAYMENT_SYSTEM_ID"))
            if os.getenv("FREEKASSA_PAYMENT_SYSTEM_ID")
            else None
        ),
        freekassa_currency=os.getenv("FREEKASSA_CURRENCY", "RUB"),
        freekassa_payer_email=os.getenv("FREEKASSA_PAYER_EMAIL") or None,
        freekassa_enabled=_parse_bool(os.getenv("FREEKASSA_ENABLED"), False),
        instruction_android_url=os.getenv("INSTRUCTION_ANDROID_URL") or None,
        instruction_ios_url=os.getenv("INSTRUCTION_IOS_URL") or None,
        instruction_windows_url=os.getenv("INSTRUCTION_WINDOWS_URL") or None,
        instruction_macos_url=os.getenv("INSTRUCTION_MACOS_URL") or None,
    )
