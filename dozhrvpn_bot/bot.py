from __future__ import annotations

import asyncio
import json
import logging
from contextlib import suppress
from decimal import Decimal, ROUND_HALF_UP
from html import escape
from typing import Any

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ChatMemberStatus, ParseMode
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import CallbackQuery, Message

from dozhrvpn_bot.config import (
    Config,
    Plan,
    apply_runtime_settings,
    load_config,
    parse_campaign_buttons,
    serialize_plans,
)
from dozhrvpn_bot.cryptopay import CryptoPayClient
from dozhrvpn_bot.database import Database, from_iso
from dozhrvpn_bot.freekassa import FreeKassaClient
from dozhrvpn_bot.keyboards import (
    admin_auto_broadcast_card_keyboard,
    admin_auto_broadcasts_keyboard,
    admin_auto_broadcasts_list_keyboard,
    admin_broadcast_keyboard,
    admin_broadcast_preview_keyboard,
    admin_broadcast_save_campaign_keyboard,
    admin_order_card_keyboard,
    admin_orders_keyboard,
    admin_orders_list_keyboard,
    admin_panel_keyboard,
    admin_payment_settings_keyboard,
    admin_plan_card_keyboard,
    admin_promo_card_keyboard,
    admin_promos_keyboard,
    admin_promos_list_keyboard,
    admin_prompt_cancel_keyboard,
    admin_settings_keyboard,
    admin_plans_keyboard,
    admin_user_card_keyboard,
    admin_user_results_keyboard,
    admin_users_keyboard,
    bonuses_keyboard,
    channel_gate_keyboard,
    custom_inline_keyboard,
    instructions_keyboard,
    invoice_keyboard,
    main_menu_keyboard,
    payment_methods_keyboard,
    payment_menu_keyboard,
    profile_keyboard,
)
from dozhrvpn_bot.payment_gateway import PaymentGateway, PaymentGatewayError
from dozhrvpn_bot.payments import (
    PAYMENT_PROVIDER_CRYPTO_BOT,
    available_payment_providers,
    payment_provider_choices,
    payment_provider_is_available,
    payment_provider_label,
)
from dozhrvpn_bot.remnawave import RemnawaveClient, RemnawaveError
from dozhrvpn_bot.texts import (
    admin_auto_broadcast_card_text,
    admin_auto_broadcasts_text,
    admin_broadcast_preview_text,
    admin_broadcast_text,
    admin_dashboard_text,
    admin_order_text,
    admin_orders_list_text,
    admin_orders_text,
    admin_payment_settings_text,
    admin_plan_text,
    admin_plans_text,
    admin_promo_text,
    admin_promos_list_text,
    admin_promos_text,
    admin_settings_text,
    admin_user_results_text,
    admin_user_text,
    admin_users_text,
    bonuses_text,
    channel_gate_text,
    instructions_text,
    invoice_text,
    partner_program_text,
    payment_methods_text,
    payment_text,
    payments_disabled_text,
    profile_text,
    promo_activation_prompt,
    welcome_text,
)
from dozhrvpn_bot.ui import MENU_ADMIN, MENU_BONUSES, MENU_INSTRUCTIONS, MENU_PAYMENT, MENU_PROFILE
from dozhrvpn_bot.yoomoney import YooMoneyClient


class PromoState(StatesGroup):
    waiting_for_code = State()


class AdminState(StatesGroup):
    waiting_for_user_query = State()
    waiting_for_bonus_days = State()
    waiting_for_discount = State()
    waiting_for_order_query = State()
    waiting_for_promo_code = State()
    waiting_for_promo_bonus_days = State()
    waiting_for_promo_discount = State()
    waiting_for_promo_max_uses = State()
    waiting_for_promo_description = State()
    waiting_for_brand_name = State()
    waiting_for_channel_id = State()
    waiting_for_channel_url = State()
    waiting_for_referral_reward_days = State()
    waiting_for_plan_price = State()
    waiting_for_broadcast_content = State()
    waiting_for_broadcast_buttons = State()
    waiting_for_broadcast_confirmation = State()
    waiting_for_campaign_name = State()
    waiting_for_campaign_interval = State()


def money_with_discount(base_amount: Decimal, discount_percent: int) -> Decimal:
    if discount_percent <= 0:
        return base_amount
    multiplier = Decimal(100 - discount_percent) / Decimal(100)
    return (base_amount * multiplier).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def is_admin(config: Config, telegram_id: int) -> bool:
    return telegram_id in config.admin_ids


async def is_subscribed(bot: Bot, config: Config, telegram_id: int) -> bool:
    if config.bypass_channel_gate:
        return True
    try:
        member = await bot.get_chat_member(config.required_channel_id, telegram_id)
    except Exception:
        return False
    return member.status in {
        ChatMemberStatus.MEMBER,
        ChatMemberStatus.ADMINISTRATOR,
        ChatMemberStatus.CREATOR,
    }


def build_referral_link(config: Config, ref_code: str) -> str:
    if config.bot_public_username:
        return f"https://t.me/{config.bot_public_username}?start=ref_{ref_code}"
    return f"ref_{ref_code}"


def describe_broadcast_message(message: Message) -> str:
    if message.photo:
        return "фото"
    if message.video:
        return "видео"
    if message.animation:
        return "анимация"
    if message.document:
        return "документ"
    if message.caption:
        return "медиа с подписью"
    return "текст"


def parse_broadcast_buttons(raw: str) -> list[list[dict[str, str]]]:
    normalized = raw.strip()
    if normalized.lower() in {"-", "нет", "none", "skip"}:
        return []

    rows: list[list[dict[str, str]]] = []
    current_row: list[dict[str, str]] = []

    for line in normalized.splitlines():
        stripped = line.strip()
        if not stripped:
            if current_row:
                rows.append(current_row)
                current_row = []
            continue

        parts = [chunk.strip() for chunk in stripped.split("|", 1)]
        if len(parts) != 2 or not parts[0] or not parts[1]:
            raise ValueError("Каждая кнопка должна быть в формате: Текст | https://example.com")
        if not parts[1].startswith(("http://", "https://")):
            raise ValueError("Для кнопок допускаются только ссылки http:// или https://")
        current_row.append({"text": parts[0], "url": parts[1]})

    if current_row:
        rows.append(current_row)

    return rows


async def send_broadcast_copy(
    *,
    bot: Bot,
    chat_id: int,
    source_chat_id: int,
    source_message_id: int,
    button_rows: list[list[dict[str, str]]] | None = None,
) -> None:
    await bot.copy_message(
        chat_id=chat_id,
        from_chat_id=source_chat_id,
        message_id=source_message_id,
        reply_markup=custom_inline_keyboard(button_rows or []),
    )


async def sync_remote_snapshot(
    db: Database,
    remnawave: RemnawaveClient,
    user_row: dict[str, Any],
) -> dict[str, Any]:
    remote = None
    if user_row.get("remnawave_uuid"):
        with suppress(Exception):
            remote = await remnawave.get_user_by_uuid(user_row["remnawave_uuid"])
    if remote is None:
        with suppress(Exception):
            remote = await remnawave.get_user_by_telegram_id(user_row["telegram_id"])

    if remote:
        expires_at = from_iso(remote.get("expireAt"))
        await db.update_subscription_snapshot(
            user_id=user_row["id"],
            remnawave_uuid=remote.get("uuid"),
            short_uuid=remote.get("shortUuid"),
            subscription_url=remote.get("subscriptionUrl"),
            expires_at=expires_at,
        )
        refreshed = await db.get_user_by_id(user_row["id"])
        return refreshed or user_row
    return user_row


async def activate_paid_order(
    *,
    db: Database,
    remnawave: RemnawaveClient,
    order: dict[str, Any],
    user_row: dict[str, Any],
    config: Config,
) -> dict[str, Any]:
    if order["status"] == "activated":
        return await db.get_user_by_id(user_row["id"]) or user_row

    current_expire = from_iso(user_row.get("subscription_expires_at"))
    bonus_days = await db.consume_bonus_days(user_row["id"])
    total_days = int(order["days"]) + bonus_days

    remote = await remnawave.provision_subscription(
        telegram_id=user_row["telegram_id"],
        local_uuid=user_row.get("remnawave_uuid"),
        current_expires_at=current_expire,
        subscription_days=total_days,
        username_hint=user_row.get("username"),
    )

    await db.update_subscription_snapshot(
        user_id=user_row["id"],
        remnawave_uuid=remote.get("uuid"),
        short_uuid=remote.get("shortUuid"),
        subscription_url=remote.get("subscriptionUrl"),
        expires_at=from_iso(remote.get("expireAt")),
    )
    await db.activate_order(int(order["id"]))

    if int(order.get("discount_percent") or 0) > 0:
        await db.clear_pending_discount(user_row["id"])

    await db.register_referral_reward(
        invited_user_id=user_row["id"],
        order_id=int(order["id"]),
        reward_days=config.referral_reward_days,
    )

    return await db.get_user_by_id(user_row["id"]) or user_row
def create_router(
    config: Config,
    db: Database,
    payment_gateway: PaymentGateway,
    remnawave: RemnawaveClient,
) -> Router:
    router = Router()

    def add_note(text: str, note: str | None = None) -> str:
        return f"{note}\n\n{text}" if note else text

    async def get_runtime_config() -> Config:
        settings = await db.get_settings()
        return apply_runtime_settings(config, settings)

    def find_plan(plans: tuple[Plan, ...], plan_key: str) -> Plan | None:
        return next((item for item in plans if item.key == plan_key), None)

    def payment_methods_available(runtime_config: Config) -> tuple[str, ...]:
        return available_payment_providers(runtime_config)

    async def send_main_menu(target: Message, runtime_config: Config) -> None:
        await target.answer(
            welcome_text(runtime_config, target.from_user.first_name),
            reply_markup=main_menu_keyboard(show_admin=is_admin(config, target.from_user.id)),
        )

    async def ensure_admin_access(target: Message | CallbackQuery) -> bool:
        if is_admin(config, target.from_user.id):
            return True
        if isinstance(target, CallbackQuery):
            await target.answer("Нет доступа к админке.", show_alert=True)
        else:
            await target.answer("Нет доступа к админке.")
        return False

    async def ensure_access(
        *,
        message: Message | None,
        callback: CallbackQuery | None,
        bot: Bot,
    ) -> Config | None:
        runtime_config = await get_runtime_config()
        actor_id = message.from_user.id if message else callback.from_user.id
        subscribed = await is_subscribed(bot, runtime_config, actor_id)
        await db.set_channel_member(actor_id, subscribed)
        if subscribed:
            return runtime_config

        target = message if message is not None else callback.message
        if target is not None:
            await target.answer(
                channel_gate_text(runtime_config),
                reply_markup=channel_gate_keyboard(runtime_config),
            )
        if callback:
            await callback.answer("Необходимо подтвердить подписку на канал.", show_alert=True)
        return None

    async def render_panel(
        target: Message | CallbackQuery,
        text: str,
        reply_markup: Any,
    ) -> None:
        if isinstance(target, CallbackQuery):
            if target.message is not None:
                try:
                    await target.message.edit_text(text, reply_markup=reply_markup)
                except TelegramBadRequest:
                    await target.message.answer(text, reply_markup=reply_markup)
            await target.answer()
            return
        await target.answer(text, reply_markup=reply_markup)

    async def show_admin_home(target: Message | CallbackQuery, note: str | None = None) -> None:
        runtime_config = await get_runtime_config()
        stats = await db.get_admin_dashboard()
        await render_panel(
            target,
            add_note(admin_dashboard_text(runtime_config, stats), note),
            admin_panel_keyboard(),
        )

    async def show_admin_users_section(target: Message | CallbackQuery, note: str | None = None) -> None:
        await render_panel(target, add_note(admin_users_text(), note), admin_users_keyboard())

    async def show_admin_orders_section(target: Message | CallbackQuery, note: str | None = None) -> None:
        await render_panel(target, add_note(admin_orders_text(), note), admin_orders_keyboard())

    async def show_admin_promos_section(target: Message | CallbackQuery, note: str | None = None) -> None:
        await render_panel(target, add_note(admin_promos_text(), note), admin_promos_keyboard())

    async def show_admin_broadcast_section(target: Message | CallbackQuery, note: str | None = None) -> None:
        total_users = len(await db.list_user_telegram_ids())
        await render_panel(
            target,
            add_note(admin_broadcast_text(total_users), note),
            admin_broadcast_keyboard(),
        )

    async def show_admin_settings_section(target: Message | CallbackQuery, note: str | None = None) -> None:
        runtime_config = await get_runtime_config()
        await render_panel(
            target,
            add_note(admin_settings_text(runtime_config), note),
            admin_settings_keyboard(),
        )

    async def show_admin_payment_settings(target: Message | CallbackQuery, note: str | None = None) -> None:
        runtime_config = await get_runtime_config()
        await render_panel(
            target,
            add_note(admin_payment_settings_text(runtime_config), note),
            admin_payment_settings_keyboard(
                crypto_bot_enabled=runtime_config.crypto_pay_enabled,
                yoomoney_enabled=runtime_config.yoomoney_enabled,
                freekassa_enabled=runtime_config.freekassa_enabled,
            ),
        )

    async def show_admin_plans_section(target: Message | CallbackQuery, note: str | None = None) -> None:
        runtime_config = await get_runtime_config()
        await render_panel(
            target,
            add_note(admin_plans_text(runtime_config), note),
            admin_plans_keyboard(runtime_config.plans),
        )

    async def show_admin_plan_card(
        target: Message | CallbackQuery,
        plan_key: str,
        note: str | None = None,
    ) -> None:
        runtime_config = await get_runtime_config()
        plan = find_plan(runtime_config.plans, plan_key)
        if not plan:
            await show_admin_plans_section(target, "Тариф не найден.")
            return
        await render_panel(
            target,
            add_note(admin_plan_text(plan), note),
            admin_plan_card_keyboard(plan.key),
        )

    async def show_admin_auto_broadcasts_section(target: Message | CallbackQuery, note: str | None = None) -> None:
        campaigns = await db.list_broadcast_campaigns(limit=20)
        await render_panel(
            target,
            add_note(admin_auto_broadcasts_text(campaigns), note),
            admin_auto_broadcasts_list_keyboard(campaigns) if campaigns else admin_auto_broadcasts_keyboard(),
        )

    async def show_admin_auto_broadcast_card(
        target: Message | CallbackQuery,
        campaign_id: int,
        note: str | None = None,
    ) -> None:
        campaign = await db.get_broadcast_campaign(campaign_id)
        if not campaign:
            await show_admin_auto_broadcasts_section(target, "Авторассылка не найдена.")
            return
        await render_panel(
            target,
            add_note(admin_auto_broadcast_card_text(campaign), note),
            admin_auto_broadcast_card_keyboard(campaign_id, is_active=int(campaign.get("is_active") or 0) == 1),
        )

    async def show_admin_user_card(
        target: Message | CallbackQuery,
        user_id: int,
        note: str | None = None,
    ) -> None:
        profile_stats = await db.get_user_admin_profile(user_id)
        if not profile_stats:
            await show_admin_users_section(target, "Пользователь не найден.")
            return
        await render_panel(
            target,
            add_note(admin_user_text(config, profile_stats), note),
            admin_user_card_keyboard(user_id),
        )

    async def show_admin_order_card(
        target: Message | CallbackQuery,
        order_id: int,
        note: str | None = None,
    ) -> None:
        order = await db.get_order(order_id)
        if not order:
            await show_admin_orders_section(target, "Заказ не найден.")
            return
        await render_panel(
            target,
            add_note(admin_order_text(order), note),
            admin_order_card_keyboard(
                int(order["id"]),
                int(order["user_id"]),
                payment_provider_label(str(order.get("payment_provider") or PAYMENT_PROVIDER_CRYPTO_BOT)),
            ),
        )

    async def show_admin_promo_card(
        target: Message | CallbackQuery,
        promo_id: int,
        note: str | None = None,
    ) -> None:
        promo = await db.get_promo(promo_id)
        if not promo:
            await show_admin_promos_section(target, "Промокод не найден.")
            return
        await render_panel(
            target,
            add_note(admin_promo_text(promo), note),
            admin_promo_card_keyboard(promo_id, is_active=int(promo.get("is_active") or 0) == 1),
        )

    async def show_admin_user_results(
        target: Message | CallbackQuery,
        query: str,
        users: list[dict[str, Any]],
        *,
        back_callback: str = "admin:users",
    ) -> None:
        await render_panel(
            target,
            admin_user_results_text(query, users),
            admin_user_results_keyboard(users, back_callback=back_callback),
        )

    async def show_admin_orders_list(
        target: Message | CallbackQuery,
        title: str,
        orders: list[dict[str, Any]],
        *,
        back_callback: str = "admin:orders",
    ) -> None:
        await render_panel(
            target,
            admin_orders_list_text(title, orders),
            admin_orders_list_keyboard(orders, back_callback=back_callback),
        )

    async def show_admin_promos_list(
        target: Message | CallbackQuery,
        promos: list[dict[str, Any]],
    ) -> None:
        await render_panel(
            target,
            admin_promos_list_text(promos),
            admin_promos_list_keyboard(promos),
        )

    async def sync_order_status(
        *,
        order_id: int,
        actor_telegram_id: int | None = None,
        enforce_owner: bool = True,
    ) -> dict[str, Any]:
        order = await db.get_order(order_id)
        if not order:
            return {"status": "not_found"}

        if enforce_owner and actor_telegram_id is not None and order["telegram_id"] != actor_telegram_id:
            return {"status": "forbidden", "order": order}

        user = await db.get_user_by_telegram_id(order["telegram_id"])
        if not user:
            return {"status": "user_not_found", "order": order}

        if order["status"] == "activated":
            user = await sync_remote_snapshot(db, remnawave, user)
            return {
                "status": "already_activated",
                "order": order,
                "user": user,
                "payment_provider": str(order.get("payment_provider") or PAYMENT_PROVIDER_CRYPTO_BOT),
            }

        payment_provider = str(order.get("payment_provider") or PAYMENT_PROVIDER_CRYPTO_BOT)
        payment_invoice_id = order.get("payment_invoice_id")
        payment_label = order.get("payment_label")

        if not payment_invoice_id and not payment_label:
            return {
                "status": "missing_invoice_id",
                "order": order,
                "user": user,
                "payment_provider": payment_provider,
            }

        try:
            invoice = await payment_gateway.get_invoice_status(
                payment_provider,
                invoice_id=None if payment_invoice_id in (None, "") else str(payment_invoice_id),
                label=None if payment_label in (None, "") else str(payment_label),
            )
        except PaymentGatewayError as exc:
            return {
                "status": "payment_error",
                "order": order,
                "user": user,
                "payment_provider": payment_provider,
                "error": str(exc),
            }

        if invoice is None:
            await db.expire_order(order_id)
            return {
                "status": "invoice_missing",
                "order": await db.get_order(order_id) or order,
                "user": user,
                "payment_provider": payment_provider,
            }

        status = str(invoice.get("status") or "pending")
        await db.mark_order_invoice_status(order_id, status, invoice.get("raw") or invoice)
        order = await db.get_order(order_id) or order

        if status == "paid":
            try:
                user = await sync_remote_snapshot(db, remnawave, user)
                runtime_config = await get_runtime_config()
                updated = await activate_paid_order(
                    db=db,
                    remnawave=remnawave,
                    order=order,
                    user_row=user,
                    config=runtime_config,
                )
            except RemnawaveError as exc:
                return {
                    "status": "remnawave_error",
                    "order": order,
                    "user": user,
                    "payment_provider": payment_provider,
                    "error": str(exc),
                    "invoice": invoice,
                }

            return {
                "status": "activated",
                "order": await db.get_order(order_id) or order,
                "user": updated,
                "payment_provider": payment_provider,
                "invoice": invoice,
            }

        if status == "expired":
            await db.expire_order(order_id)
            return {
                "status": "expired",
                "order": await db.get_order(order_id) or order,
                "user": user,
                "payment_provider": payment_provider,
                "invoice": invoice,
            }

        return {
            "status": "pending",
            "order": order,
            "user": user,
            "payment_provider": payment_provider,
            "invoice": invoice,
        }

    async def check_order_and_reply(
        bot: Bot,
        message: Message | None,
        callback: CallbackQuery | None,
        order_id: int,
    ) -> None:
        actor_id = callback.from_user.id if callback else message.from_user.id
        result = await sync_order_status(
            order_id=order_id,
            actor_telegram_id=actor_id,
            enforce_owner=True,
        )

        status = result["status"]
        if status == "not_found":
            if callback:
                await callback.answer("Заказ не найден.", show_alert=True)
            elif message:
                await message.answer("Заказ не найден.")
            return

        if status == "forbidden":
            if callback:
                await callback.answer("Это не ваш заказ.", show_alert=True)
            return

        if status == "user_not_found":
            if callback:
                await callback.answer("Пользователь заказа не найден.", show_alert=True)
            elif message:
                await message.answer("Пользователь заказа не найден.")
            return

        if status == "missing_invoice_id":
            text = "У заказа нет invoice ID. Создайте оплату заново."
            if callback:
                await callback.answer(text, show_alert=True)
            elif message:
                await message.answer(text)
            return

        if status == "payment_error":
            provider_label = payment_provider_label(str(result.get("payment_provider") or ""))
            text = f"{provider_label} вернул ошибку: <code>{escape(result['error'])}</code>"
            if callback:
                await callback.message.answer(text)
                await callback.answer()
            elif message:
                await message.answer(text)
            return

        if status == "invoice_missing":
            text = "Инвойс не найден или уже удалён."
            if callback:
                await callback.answer(text, show_alert=True)
            elif message:
                await message.answer(text)
            return

        if status == "remnawave_error":
            text = f"Оплата подтверждена, но Remnawave вернул ошибку: <code>{escape(result['error'])}</code>"
            if callback:
                await callback.message.answer(text)
                await callback.answer("Оплата подтверждена, активация не завершена.", show_alert=True)
            elif message:
                await message.answer(text)
            return

        if status in {"activated", "already_activated"}:
            updated = result["user"]
            expires_at = updated.get("subscription_expires_at") or "неизвестно"
            subscription_url = updated.get("remnawave_subscription_url") or "не выдана"
            text = (
                "✅ <b>Подписка активна</b>\n\n"
                f"{'Заказ уже был активирован ранее.' if status == 'already_activated' else 'Тариф успешно активирован.'}\n"
                f"📅 Активно до: <b>{escape(str(expires_at))}</b>\n"
                f"🔗 Subscription URL:\n<code>{escape(subscription_url)}</code>"
            )
            if callback:
                await callback.message.answer(
                    text,
                    reply_markup=profile_keyboard(updated.get("remnawave_subscription_url")),
                )
                await callback.answer("Подписка активирована.")
            elif message:
                await message.answer(
                    text,
                    reply_markup=profile_keyboard(updated.get("remnawave_subscription_url")),
                )
            return

        if status == "expired":
            text = "Срок счета истек. Создайте новый платеж."
        else:
            text = "Оплата пока не подтверждена. Повторите проверку через несколько секунд."

        if callback:
            await callback.answer(text, show_alert=True)
        elif message:
            await message.answer(text)

    @router.message(Command("start"))
    async def start_handler(message: Message, command: CommandObject, state: FSMContext) -> None:
        referrer_code = None
        order_to_check = None
        if command.args:
            if command.args.startswith("ref_"):
                referrer_code = command.args[4:].strip()
            elif command.args.startswith("paid_"):
                with suppress(ValueError):
                    order_to_check = int(command.args[5:].strip())

        await db.get_or_create_user(
            telegram_id=message.from_user.id,
            username=message.from_user.username,
            first_name=message.from_user.first_name,
            last_name=message.from_user.last_name,
            referrer_code=referrer_code,
        )
        await state.clear()

        runtime_config = await ensure_access(message=message, callback=None, bot=message.bot)
        if runtime_config is None:
            return

        await send_main_menu(message, runtime_config)

        if order_to_check:
            order = await db.get_order(order_to_check)
            if order and order["telegram_id"] == message.from_user.id:
                await check_order_and_reply(message.bot, message, None, order_to_check)

    @router.callback_query(F.data == "check_channel")
    async def check_channel_handler(callback: CallbackQuery) -> None:
        runtime_config = await ensure_access(message=None, callback=callback, bot=callback.bot)
        if runtime_config is not None:
            await callback.message.answer(
                "Подписка подтверждена. Меню доступно.",
                reply_markup=main_menu_keyboard(show_admin=is_admin(config, callback.from_user.id)),
            )
            await callback.answer()

    @router.message(Command("cancel"))
    async def cancel_handler(message: Message, state: FSMContext) -> None:
        current_state = await state.get_state()
        if current_state is None:
            return
        await state.clear()
        await message.answer(
            "Текущее действие отменено.",
            reply_markup=main_menu_keyboard(show_admin=is_admin(config, message.from_user.id)),
        )

    @router.message(Command("admin"))
    async def admin_panel_command(message: Message, state: FSMContext) -> None:
        if not await ensure_admin_access(message):
            return
        await state.clear()
        await show_admin_home(message)

    @router.message(F.text == MENU_ADMIN)
    async def admin_panel_button(message: Message, state: FSMContext) -> None:
        if not await ensure_admin_access(message):
            return
        await state.clear()
        await show_admin_home(message)

    @router.message(F.text == MENU_PAYMENT)
    async def payment_handler(message: Message) -> None:
        runtime_config = await ensure_access(message=message, callback=None, bot=message.bot)
        if runtime_config is None:
            return
        user = await db.get_user_by_telegram_id(message.from_user.id)
        if not user:
            return
        if not payment_methods_available(runtime_config):
            await message.answer(payments_disabled_text())
            return
        discount_percent = await db.get_pending_discount(user["id"])
        bonus_days = await db.peek_bonus_days(user["id"])
        await message.answer(
            payment_text(runtime_config, discount_percent, bonus_days),
            reply_markup=payment_menu_keyboard(runtime_config.plans),
        )

    @router.callback_query(F.data == "back_to_payment")
    async def back_to_payment_handler(callback: CallbackQuery) -> None:
        runtime_config = await get_runtime_config()
        user = await db.get_user_by_telegram_id(callback.from_user.id)
        if not user:
            await callback.answer()
            return
        if not payment_methods_available(runtime_config):
            await callback.message.answer(payments_disabled_text())
            await callback.answer()
            return
        discount_percent = await db.get_pending_discount(user["id"])
        bonus_days = await db.peek_bonus_days(user["id"])
        await callback.message.answer(
            payment_text(runtime_config, discount_percent, bonus_days),
            reply_markup=payment_menu_keyboard(runtime_config.plans),
        )
        await callback.answer()

    @router.callback_query(F.data.startswith("buy:"))
    async def buy_plan_handler(callback: CallbackQuery) -> None:
        runtime_config = await ensure_access(message=None, callback=callback, bot=callback.bot)
        if runtime_config is None:
            return

        user = await db.get_user_by_telegram_id(callback.from_user.id)
        if not user:
            await callback.answer("Профиль не найден.", show_alert=True)
            return

        plan_key = callback.data.split(":", 1)[1]
        if not payment_methods_available(runtime_config):
            await callback.answer("Оплата временно отключена.", show_alert=True)
            return

        plan = find_plan(runtime_config.plans, plan_key)
        if not plan:
            await callback.answer("Тариф не найден.", show_alert=True)
            return

        discount_percent = await db.get_pending_discount(user["id"])
        final_amount = money_with_discount(plan.price_rub, discount_percent)
        await callback.message.answer(
            payment_methods_text(plan.title, str(final_amount)),
            reply_markup=payment_methods_keyboard(plan.key, payment_provider_choices(runtime_config)),
        )
        await callback.answer()

    @router.callback_query(F.data.regexp(r"^pay:(crypto_bot|yoomoney|freekassa):[^:]+$"))
    async def buy_plan_with_provider_handler(callback: CallbackQuery) -> None:
        runtime_config = await ensure_access(message=None, callback=callback, bot=callback.bot)
        if runtime_config is None:
            return

        user = await db.get_user_by_telegram_id(callback.from_user.id)
        if not user:
            await callback.answer("Профиль не найден.", show_alert=True)
            return

        _, provider, plan_key = callback.data.split(":", 2)
        if not payment_provider_is_available(runtime_config, provider):
            await callback.answer("Этот способ оплаты сейчас недоступен.", show_alert=True)
            return

        plan = find_plan(runtime_config.plans, plan_key)
        if not plan:
            await callback.answer("Тариф не найден.", show_alert=True)
            return

        discount_percent = await db.get_pending_discount(user["id"])
        final_amount = money_with_discount(plan.price_rub, discount_percent)
        promo_code = "AUTO" if discount_percent > 0 else None

        order = await db.create_order(
            user_id=user["id"],
            plan_key=plan.key,
            plan_name=plan.title,
            days=plan.days,
            base_amount=str(plan.price_rub),
            final_amount=str(final_amount),
            currency_type=config.crypto_pay_currency_type if provider == PAYMENT_PROVIDER_CRYPTO_BOT else "fiat",
            fiat=config.crypto_pay_fiat if provider == PAYMENT_PROVIDER_CRYPTO_BOT else "RUB",
            asset=config.crypto_pay_asset if provider == PAYMENT_PROVIDER_CRYPTO_BOT else None,
            accepted_assets=config.crypto_pay_accepted_assets if provider == PAYMENT_PROVIDER_CRYPTO_BOT else None,
            promo_code=promo_code,
            discount_percent=discount_percent,
            payment_provider=provider,
        )

        try:
            invoice = await payment_gateway.create_invoice(
                provider,
                amount=str(final_amount),
                description=f"{runtime_config.brand_name} • {plan.title} • {plan.days} дней",
                order_id=int(order["id"]),
                user_id=user["telegram_id"],
            )
        except PaymentGatewayError as exc:
            provider_label = payment_provider_label(provider)
            await callback.message.answer(
                f"Не удалось создать счёт в {provider_label}: <code>{escape(str(exc))}</code>"
            )
            await callback.answer()
            return

        await db.update_order_invoice(int(order["id"]), invoice)
        await callback.message.answer(
            invoice_text(plan.title, plan.days, str(final_amount), int(order["id"]), payment_provider_label(provider)),
            reply_markup=invoice_keyboard(
                pay_url=str(invoice["pay_url"]),
                order_id=int(order["id"]),
                extra_url=invoice.get("extra_url"),
                extra_label="Mini App" if provider == PAYMENT_PROVIDER_CRYPTO_BOT else None,
            ),
        )
        await callback.answer("Счёт создан.")

    @router.callback_query(F.data.startswith("check_order:"))
    async def check_order_handler(callback: CallbackQuery) -> None:
        runtime_config = await ensure_access(message=None, callback=callback, bot=callback.bot)
        if runtime_config is None:
            return
        order_id = int(callback.data.split(":", 1)[1])
        await check_order_and_reply(callback.bot, None, callback, order_id)

    @router.message(F.text == MENU_PROFILE)
    async def profile_handler(message: Message) -> None:
        runtime_config = await ensure_access(message=message, callback=None, bot=message.bot)
        if runtime_config is None:
            return
        user = await db.get_user_by_telegram_id(message.from_user.id)
        if not user:
            return
        user = await sync_remote_snapshot(db, remnawave, user)
        profile_stats = await db.get_profile_stats(user["id"])
        await message.answer(
            profile_text(runtime_config, profile_stats),
            reply_markup=profile_keyboard(profile_stats["user"].get("remnawave_subscription_url")),
        )

    @router.callback_query(F.data == "profile:refresh")
    async def profile_refresh_handler(callback: CallbackQuery) -> None:
        runtime_config = await get_runtime_config()
        user = await db.get_user_by_telegram_id(callback.from_user.id)
        if not user:
            await callback.answer()
            return
        user = await sync_remote_snapshot(db, remnawave, user)
        profile_stats = await db.get_profile_stats(user["id"])
        await callback.message.answer(
            profile_text(runtime_config, profile_stats),
            reply_markup=profile_keyboard(profile_stats["user"].get("remnawave_subscription_url")),
        )
        await callback.answer("Профиль обновлен.")

    @router.message(F.text == MENU_INSTRUCTIONS)
    async def instructions_handler(message: Message) -> None:
        runtime_config = await ensure_access(message=message, callback=None, bot=message.bot)
        if runtime_config is None:
            return
        user = await db.get_user_by_telegram_id(message.from_user.id)
        if not user:
            return
        user = await sync_remote_snapshot(db, remnawave, user)
        await message.answer(
            instructions_text(runtime_config, user.get("remnawave_subscription_url")),
            reply_markup=instructions_keyboard(runtime_config, user.get("remnawave_subscription_url")),
        )

    @router.message(F.text == MENU_BONUSES)
    async def bonuses_handler(message: Message) -> None:
        runtime_config = await ensure_access(message=message, callback=None, bot=message.bot)
        if runtime_config is None:
            return
        user = await db.get_user_by_telegram_id(message.from_user.id)
        if not user:
            return
        profile_stats = await db.get_profile_stats(user["id"])
        promos = await db.recent_promos()
        referral_link = build_referral_link(runtime_config, user["ref_code"])
        await message.answer(
            bonuses_text(runtime_config, profile_stats, referral_link, promos),
            reply_markup=bonuses_keyboard(),
        )

    @router.callback_query(F.data == "bonus:promo")
    async def bonus_promo_handler(callback: CallbackQuery, state: FSMContext) -> None:
        await state.set_state(PromoState.waiting_for_code)
        await callback.message.answer(promo_activation_prompt())
        await callback.answer()

    @router.callback_query(F.data == "bonus:referral")
    async def bonus_referral_handler(callback: CallbackQuery) -> None:
        runtime_config = await get_runtime_config()
        user = await db.get_user_by_telegram_id(callback.from_user.id)
        if not user:
            await callback.answer()
            return
        profile_stats = await db.get_profile_stats(user["id"])
        referral_link = build_referral_link(runtime_config, user["ref_code"])
        promos = await db.recent_promos()
        await callback.message.answer(
            bonuses_text(runtime_config, profile_stats, referral_link, promos),
            reply_markup=bonuses_keyboard(),
        )
        await callback.answer()

    @router.callback_query(F.data == "bonus:partner")
    async def bonus_partner_handler(callback: CallbackQuery) -> None:
        runtime_config = await get_runtime_config()
        user = await db.get_user_by_telegram_id(callback.from_user.id)
        if not user:
            await callback.answer()
            return
        profile_stats = await db.get_profile_stats(user["id"])
        referral_link = build_referral_link(runtime_config, user["ref_code"])
        await callback.message.answer(partner_program_text(runtime_config, profile_stats, referral_link))
        await callback.answer()

    @router.message(PromoState.waiting_for_code, F.text)
    async def promo_code_handler(message: Message, state: FSMContext) -> None:
        user = await db.get_user_by_telegram_id(message.from_user.id)
        if not user:
            await state.clear()
            return

        code = message.text.strip()
        try:
            promo = await db.apply_promo_code(user["id"], code)
        except ValueError as exc:
            await message.answer(f"Ошибка активации: <code>{escape(str(exc))}</code>")
            return

        lines = ["Промокод активирован."]
        if int(promo["bonus_days"]) > 0:
            lines.append(f"Начислено бонусных дней: <b>{promo['bonus_days']}</b>")
        if int(promo["discount_percent"]) > 0:
            lines.append(f"Скидка на ближайшую оплату: <b>{promo['discount_percent']}%</b>")

        if int(promo["bonus_days"]) > 0:
            user = await sync_remote_snapshot(db, remnawave, user)
            if any(
                (
                    user.get("remnawave_uuid"),
                    user.get("remnawave_subscription_url"),
                    user.get("subscription_expires_at"),
                )
            ):
                bonus_days = await db.consume_bonus_days(user["id"])
                if bonus_days > 0:
                    try:
                        remote = await remnawave.provision_subscription(
                            telegram_id=user["telegram_id"],
                            local_uuid=user.get("remnawave_uuid"),
                            current_expires_at=from_iso(user.get("subscription_expires_at")),
                            subscription_days=bonus_days,
                            username_hint=user.get("username"),
                        )
                        await db.update_subscription_snapshot(
                            user_id=user["id"],
                            remnawave_uuid=remote.get("uuid"),
                            short_uuid=remote.get("shortUuid"),
                            subscription_url=remote.get("subscriptionUrl"),
                            expires_at=from_iso(remote.get("expireAt")),
                        )
                        lines.append("Бонусные дни сразу применены к текущей подписке.")
                    except RemnawaveError as exc:
                        await db.restore_bonus_balance(user["id"], bonus_days)
                        lines.append(
                            "Бонус сохранен в балансе, автоматическое применение не выполнено: "
                            f"<code>{escape(str(exc))}</code>"
                        )

        await message.answer("\n".join(lines))
        await state.clear()

    @router.callback_query(F.data == "admin:home")
    async def admin_home_callback(callback: CallbackQuery, state: FSMContext) -> None:
        if not await ensure_admin_access(callback):
            return
        await state.clear()
        await show_admin_home(callback)

    @router.callback_query(F.data == "admin:stats")
    async def admin_stats_callback(callback: CallbackQuery, state: FSMContext) -> None:
        if not await ensure_admin_access(callback):
            return
        await state.clear()
        await show_admin_home(callback)

    @router.callback_query(F.data == "admin:settings")
    async def admin_settings_callback(callback: CallbackQuery, state: FSMContext) -> None:
        if not await ensure_admin_access(callback):
            return
        await state.clear()
        await show_admin_settings_section(callback)

    @router.callback_query(F.data == "admin:settings:brand")
    async def admin_settings_brand_prompt(callback: CallbackQuery, state: FSMContext) -> None:
        if not await ensure_admin_access(callback):
            return
        await state.set_state(AdminState.waiting_for_brand_name)
        await callback.message.answer(
            "Отправьте новое название VPN.",
            reply_markup=admin_prompt_cancel_keyboard("admin:settings"),
        )
        await callback.answer()

    @router.message(AdminState.waiting_for_brand_name, F.text)
    async def admin_settings_brand_input(message: Message, state: FSMContext) -> None:
        if not await ensure_admin_access(message):
            await state.clear()
            return
        value = message.text.strip()
        if not value:
            await message.answer("Название не может быть пустым.")
            return
        await db.set_setting("brand_name", value)
        await state.clear()
        await show_admin_settings_section(message, "Название обновлено.")

    @router.callback_query(F.data == "admin:settings:channel")
    async def admin_settings_channel_prompt(callback: CallbackQuery, state: FSMContext) -> None:
        if not await ensure_admin_access(callback):
            return
        await state.set_state(AdminState.waiting_for_channel_id)
        await callback.message.answer(
            "Отправьте ID или username канала для проверки подписки. Например: <code>@channel_name</code>",
            reply_markup=admin_prompt_cancel_keyboard("admin:settings"),
        )
        await callback.answer()

    @router.message(AdminState.waiting_for_channel_id, F.text)
    async def admin_settings_channel_id_input(message: Message, state: FSMContext) -> None:
        if not await ensure_admin_access(message):
            await state.clear()
            return
        value = message.text.strip()
        if not value:
            await message.answer("ID канала не может быть пустым.")
            return
        await state.update_data(new_channel_id=value)
        await state.set_state(AdminState.waiting_for_channel_url)
        await message.answer("Отправьте ссылку на канал. Например: <code>https://t.me/channel_name</code>")

    @router.message(AdminState.waiting_for_channel_url, F.text)
    async def admin_settings_channel_url_input(message: Message, state: FSMContext) -> None:
        if not await ensure_admin_access(message):
            await state.clear()
            return
        value = message.text.strip()
        if not value.startswith(("http://", "https://")):
            await message.answer("Нужна полная ссылка на канал.")
            return
        data = await state.get_data()
        await db.set_setting("required_channel_id", str(data["new_channel_id"]))
        await db.set_setting("required_channel_url", value)
        await state.clear()
        await show_admin_settings_section(message, "Канал подписки обновлен.")

    @router.callback_query(F.data == "admin:settings:referral")
    async def admin_settings_referral_prompt(callback: CallbackQuery, state: FSMContext) -> None:
        if not await ensure_admin_access(callback):
            return
        await state.set_state(AdminState.waiting_for_referral_reward_days)
        await callback.message.answer(
            "Введите количество бонусных дней за первого оплаченного реферала.",
            reply_markup=admin_prompt_cancel_keyboard("admin:settings"),
        )
        await callback.answer()

    @router.message(AdminState.waiting_for_referral_reward_days, F.text)
    async def admin_settings_referral_input(message: Message, state: FSMContext) -> None:
        if not await ensure_admin_access(message):
            await state.clear()
            return
        try:
            days = int(message.text.strip())
        except ValueError:
            await message.answer("Нужно отправить целое число.")
            return
        if days < 0:
            await message.answer("Значение не может быть отрицательным.")
            return
        await db.set_setting("referral_reward_days", str(days))
        await state.clear()
        await show_admin_settings_section(message, "Реферальный бонус обновлен.")

    @router.callback_query(F.data == "admin:settings:payments")
    async def admin_settings_payments_callback(callback: CallbackQuery, state: FSMContext) -> None:
        if not await ensure_admin_access(callback):
            return
        await state.clear()
        await show_admin_payment_settings(callback)

    @router.callback_query(F.data == "admin:settings:payments:crypto")
    async def admin_settings_payments_crypto_toggle(callback: CallbackQuery, state: FSMContext) -> None:
        if not await ensure_admin_access(callback):
            return
        await state.clear()
        runtime_config = await get_runtime_config()
        await db.set_setting("crypto_pay_enabled", "0" if runtime_config.crypto_pay_enabled else "1")
        await show_admin_payment_settings(callback, "Состояние Crypto Bot обновлено.")

    @router.callback_query(F.data == "admin:settings:payments:yoomoney")
    async def admin_settings_payments_yoomoney_toggle(callback: CallbackQuery, state: FSMContext) -> None:
        if not await ensure_admin_access(callback):
            return
        await state.clear()
        runtime_config = await get_runtime_config()
        await db.set_setting("yoomoney_enabled", "0" if runtime_config.yoomoney_enabled else "1")
        await show_admin_payment_settings(callback, "Состояние YooMoney обновлено.")

    @router.callback_query(F.data == "admin:settings:payments:freekassa")
    async def admin_settings_payments_freekassa_toggle(callback: CallbackQuery, state: FSMContext) -> None:
        if not await ensure_admin_access(callback):
            return
        await state.clear()
        runtime_config = await get_runtime_config()
        await db.set_setting("freekassa_enabled", "0" if runtime_config.freekassa_enabled else "1")
        await show_admin_payment_settings(callback, "Состояние FreeKassa обновлено.")

    @router.callback_query(F.data == "admin:settings:plans")
    async def admin_settings_plans_callback(callback: CallbackQuery, state: FSMContext) -> None:
        if not await ensure_admin_access(callback):
            return
        await state.clear()
        await show_admin_plans_section(callback)

    @router.callback_query(F.data.regexp(r"^admin:settings:plan:[^:]+$"))
    async def admin_settings_plan_card_callback(callback: CallbackQuery, state: FSMContext) -> None:
        if not await ensure_admin_access(callback):
            return
        await state.clear()
        plan_key = callback.data.rsplit(":", 1)[1]
        await show_admin_plan_card(callback, plan_key)

    @router.callback_query(F.data.regexp(r"^admin:settings:plan:[^:]+:price$"))
    async def admin_settings_plan_price_prompt(callback: CallbackQuery, state: FSMContext) -> None:
        if not await ensure_admin_access(callback):
            return
        plan_key = callback.data.split(":")[3]
        await state.set_state(AdminState.waiting_for_plan_price)
        await state.update_data(target_plan_key=plan_key)
        await callback.message.answer(
            "Отправьте новую цену в рублях. Допускается формат <code>499</code> или <code>499.00</code>.",
            reply_markup=admin_prompt_cancel_keyboard(f"admin:settings:plan:{plan_key}"),
        )
        await callback.answer()

    @router.message(AdminState.waiting_for_plan_price, F.text)
    async def admin_settings_plan_price_input(message: Message, state: FSMContext) -> None:
        if not await ensure_admin_access(message):
            await state.clear()
            return
        raw = message.text.strip().replace(",", ".")
        try:
            value = Decimal(raw).quantize(Decimal("0.01"))
        except Exception:
            await message.answer("Не удалось распознать цену.")
            return
        if value <= 0:
            await message.answer("Цена должна быть больше нуля.")
            return

        data = await state.get_data()
        target_plan_key = str(data["target_plan_key"])
        runtime_config = await get_runtime_config()
        updated_plans = []
        plan_found = False
        for plan in runtime_config.plans:
            if plan.key == target_plan_key:
                updated_plans.append(type(plan)(key=plan.key, title=plan.title, days=plan.days, price_rub=value, badge=plan.badge))
                plan_found = True
            else:
                updated_plans.append(plan)
        if not plan_found:
            await state.clear()
            await show_admin_plans_section(message, "Тариф не найден.")
            return

        await db.set_setting("plans_json", serialize_plans(tuple(updated_plans)))
        await state.clear()
        await show_admin_plan_card(message, target_plan_key, "Цена тарифа обновлена.")

    @router.callback_query(F.data == "admin:users")
    async def admin_users_callback(callback: CallbackQuery, state: FSMContext) -> None:
        if not await ensure_admin_access(callback):
            return
        await state.clear()
        await show_admin_users_section(callback)

    @router.callback_query(F.data == "admin:users:search")
    async def admin_user_search_prompt(callback: CallbackQuery, state: FSMContext) -> None:
        if not await ensure_admin_access(callback):
            return
        await state.set_state(AdminState.waiting_for_user_query)
        await callback.message.answer(
            "Отправьте Telegram ID, @username, внутренний ID или реф-код пользователя.",
            reply_markup=admin_prompt_cancel_keyboard("admin:users"),
        )
        await callback.answer()

    @router.callback_query(F.data == "admin:users:recent")
    async def admin_recent_users_callback(callback: CallbackQuery, state: FSMContext) -> None:
        if not await ensure_admin_access(callback):
            return
        await state.clear()
        users = await db.list_recent_users(limit=10)
        await show_admin_user_results(
            callback,
            "последние регистрации",
            users,
            back_callback="admin:users",
        )

    @router.message(AdminState.waiting_for_user_query, F.text)
    async def admin_user_search_input(message: Message, state: FSMContext) -> None:
        if not await ensure_admin_access(message):
            await state.clear()
            return
        query = message.text.strip()
        users = await db.search_users(query, limit=10)
        await state.clear()
        await show_admin_user_results(message, query, users, back_callback="admin:users")

    @router.callback_query(F.data.regexp(r"^admin:user:\d+:days$"))
    async def admin_user_days_prompt(callback: CallbackQuery, state: FSMContext) -> None:
        if not await ensure_admin_access(callback):
            return
        user_id = int(callback.data.split(":")[2])
        await state.set_state(AdminState.waiting_for_bonus_days)
        await state.update_data(admin_target_user_id=user_id)
        await callback.message.answer(
            "Введите, сколько бонусных дней начислить пользователю. Только положительное число.",
            reply_markup=admin_prompt_cancel_keyboard(f"admin:user:{user_id}"),
        )
        await callback.answer()

    @router.message(AdminState.waiting_for_bonus_days, F.text)
    async def admin_user_days_input(message: Message, state: FSMContext) -> None:
        if not await ensure_admin_access(message):
            await state.clear()
            return
        try:
            days = int(message.text.strip())
        except ValueError:
            await message.answer("Нужно отправить целое число дней.")
            return
        if days <= 0:
            await message.answer("Количество дней должно быть больше нуля.")
            return

        data = await state.get_data()
        user_id = int(data["admin_target_user_id"])
        await db.credit_bonus_days(user_id, days)
        await state.clear()
        await show_admin_user_card(
            message,
            user_id,
            f"Начислено <b>{days}</b> бонусных дней. Баланс пользователя обновлен.",
        )

    @router.callback_query(F.data.regexp(r"^admin:user:\d+:discount$"))
    async def admin_user_discount_prompt(callback: CallbackQuery, state: FSMContext) -> None:
        if not await ensure_admin_access(callback):
            return
        user_id = int(callback.data.split(":")[2])
        await state.set_state(AdminState.waiting_for_discount)
        await state.update_data(admin_target_user_id=user_id)
        await callback.message.answer(
            "Введите скидку в процентах от 0 до 100. Значение 0 очистит скидку.",
            reply_markup=admin_prompt_cancel_keyboard(f"admin:user:{user_id}"),
        )
        await callback.answer()

    @router.message(AdminState.waiting_for_discount, F.text)
    async def admin_user_discount_input(message: Message, state: FSMContext) -> None:
        if not await ensure_admin_access(message):
            await state.clear()
            return
        try:
            discount_percent = int(message.text.strip())
        except ValueError:
            await message.answer("Нужно отправить целое число от 0 до 100.")
            return
        if discount_percent < 0 or discount_percent > 100:
            await message.answer("Скидка должна быть в диапазоне от 0 до 100.")
            return

        data = await state.get_data()
        user_id = int(data["admin_target_user_id"])
        await db.set_pending_discount(user_id, discount_percent)
        await state.clear()
        note = (
            "Скидка очищена."
            if discount_percent == 0
            else f"Пользователю установлена скидка <b>{discount_percent}%</b> на следующую оплату."
        )
        await show_admin_user_card(message, user_id, note)

    @router.callback_query(F.data.regexp(r"^admin:user:\d+:sync$"))
    async def admin_user_sync_callback(callback: CallbackQuery, state: FSMContext) -> None:
        if not await ensure_admin_access(callback):
            return
        await state.clear()
        user_id = int(callback.data.split(":")[2])
        user = await db.get_user_by_id(user_id)
        if not user:
            await show_admin_users_section(callback, "Пользователь не найден.")
            return
        await sync_remote_snapshot(db, remnawave, user)
        await show_admin_user_card(
            callback,
            user_id,
            "Локальные данные пользователя синхронизированы с Remnawave.",
        )

    @router.callback_query(F.data.regexp(r"^admin:user:\d+:orders$"))
    async def admin_user_orders_callback(callback: CallbackQuery, state: FSMContext) -> None:
        if not await ensure_admin_access(callback):
            return
        await state.clear()
        user_id = int(callback.data.split(":")[2])
        user = await db.get_user_by_id(user_id)
        if not user:
            await show_admin_users_section(callback, "Пользователь не найден.")
            return
        orders = await db.list_user_orders(user_id, limit=10)
        title = f"Заказы пользователя {user['telegram_id']}"
        await show_admin_orders_list(
            callback,
            title,
            orders,
            back_callback=f"admin:user:{user_id}",
        )

    @router.callback_query(F.data.regexp(r"^admin:user:\d+$"))
    async def admin_user_card_callback(callback: CallbackQuery, state: FSMContext) -> None:
        if not await ensure_admin_access(callback):
            return
        await state.clear()
        user_id = int(callback.data.split(":")[2])
        await show_admin_user_card(callback, user_id)

    @router.callback_query(F.data == "admin:orders")
    async def admin_orders_callback(callback: CallbackQuery, state: FSMContext) -> None:
        if not await ensure_admin_access(callback):
            return
        await state.clear()
        await show_admin_orders_section(callback)

    @router.callback_query(F.data == "admin:orders:search")
    async def admin_order_search_prompt(callback: CallbackQuery, state: FSMContext) -> None:
        if not await ensure_admin_access(callback):
            return
        await state.set_state(AdminState.waiting_for_order_query)
        await callback.message.answer(
            "Отправьте номер заказа, Telegram ID или часть названия тарифа.",
            reply_markup=admin_prompt_cancel_keyboard("admin:orders"),
        )
        await callback.answer()

    @router.callback_query(F.data == "admin:orders:recent")
    async def admin_recent_orders_callback(callback: CallbackQuery, state: FSMContext) -> None:
        if not await ensure_admin_access(callback):
            return
        await state.clear()
        orders = await db.list_recent_orders(limit=10)
        await show_admin_orders_list(callback, "Последние заказы", orders, back_callback="admin:orders")

    @router.message(AdminState.waiting_for_order_query, F.text)
    async def admin_order_search_input(message: Message, state: FSMContext) -> None:
        if not await ensure_admin_access(message):
            await state.clear()
            return
        query = message.text.strip()
        orders = await db.search_orders(query, limit=10)
        await state.clear()
        await show_admin_orders_list(message, f"Результаты по запросу: {query}", orders, back_callback="admin:orders")

    @router.callback_query(F.data.regexp(r"^admin:order:\d+:refresh$"))
    async def admin_order_refresh_callback(callback: CallbackQuery, state: FSMContext) -> None:
        if not await ensure_admin_access(callback):
            return
        await state.clear()
        order_id = int(callback.data.split(":")[2])
        result = await sync_order_status(order_id=order_id, enforce_owner=False)
        status = result["status"]
        provider_label = payment_provider_label(
            str(result.get("payment_provider") or PAYMENT_PROVIDER_CRYPTO_BOT)
        )

        if status == "not_found":
            await show_admin_orders_section(callback, "Заказ не найден.")
            return

        note_map = {
            "activated": "Заказ подтвержден. Подписка активирована.",
            "already_activated": "Заказ уже был активирован ранее.",
            "pending": f"Оплата пока не найдена в {provider_label}.",
            "expired": "Срок инвойса истек. Заказ помечен как expired.",
            "missing_invoice_id": "У заказа отсутствует invoice ID.",
            "invoice_missing": f"Инвойс не найден или удален в {provider_label}.",
            "user_not_found": "Пользователь заказа не найден в локальной базе.",
        }
        note = note_map.get(status)
        if status == "payment_error":
            note = f"{provider_label} вернул ошибку: <code>{escape(result['error'])}</code>"
        elif status == "remnawave_error":
            note = f"Оплата подтверждена, Remnawave вернул ошибку: <code>{escape(result['error'])}</code>"

        await show_admin_order_card(callback, order_id, note)

    @router.callback_query(F.data.regexp(r"^admin:order:\d+$"))
    async def admin_order_card_callback(callback: CallbackQuery, state: FSMContext) -> None:
        if not await ensure_admin_access(callback):
            return
        await state.clear()
        order_id = int(callback.data.split(":")[2])
        await show_admin_order_card(callback, order_id)

    @router.callback_query(F.data == "admin:promos")
    async def admin_promos_callback(callback: CallbackQuery, state: FSMContext) -> None:
        if not await ensure_admin_access(callback):
            return
        await state.clear()
        await show_admin_promos_section(callback)

    @router.callback_query(F.data == "admin:promos:list")
    async def admin_promos_list_callback(callback: CallbackQuery, state: FSMContext) -> None:
        if not await ensure_admin_access(callback):
            return
        await state.clear()
        promos = await db.list_promos(limit=20)
        await show_admin_promos_list(callback, promos)

    @router.callback_query(F.data == "admin:promos:create")
    async def admin_promo_create_prompt(callback: CallbackQuery, state: FSMContext) -> None:
        if not await ensure_admin_access(callback):
            return
        await state.set_state(AdminState.waiting_for_promo_code)
        await callback.message.answer(
            "Введите код промокода. Например: <code>SPRING30</code>",
            reply_markup=admin_prompt_cancel_keyboard("admin:promos"),
        )
        await callback.answer()

    @router.message(AdminState.waiting_for_promo_code, F.text)
    async def admin_promo_code_input(message: Message, state: FSMContext) -> None:
        if not await ensure_admin_access(message):
            await state.clear()
            return
        code = message.text.strip().upper()
        if not code or " " in code:
            await message.answer("Код должен быть одной строкой без пробелов.")
            return
        await state.update_data(promo_code=code)
        await state.set_state(AdminState.waiting_for_promo_bonus_days)
        await message.answer("Введите, сколько бонусных дней даёт промокод. Можно 0.")

    @router.message(AdminState.waiting_for_promo_bonus_days, F.text)
    async def admin_promo_bonus_days_input(message: Message, state: FSMContext) -> None:
        if not await ensure_admin_access(message):
            await state.clear()
            return
        try:
            bonus_days = int(message.text.strip())
        except ValueError:
            await message.answer("Нужно отправить целое число 0 или больше.")
            return
        if bonus_days < 0:
            await message.answer("Бонусные дни не могут быть отрицательными.")
            return
        await state.update_data(promo_bonus_days=bonus_days)
        await state.set_state(AdminState.waiting_for_promo_discount)
        await message.answer("Введите скидку в процентах от 0 до 100.")

    @router.message(AdminState.waiting_for_promo_discount, F.text)
    async def admin_promo_discount_input(message: Message, state: FSMContext) -> None:
        if not await ensure_admin_access(message):
            await state.clear()
            return
        try:
            discount_percent = int(message.text.strip())
        except ValueError:
            await message.answer("Нужно отправить целое число от 0 до 100.")
            return
        if discount_percent < 0 or discount_percent > 100:
            await message.answer("Скидка должна быть в диапазоне от 0 до 100.")
            return
        await state.update_data(promo_discount_percent=discount_percent)
        await state.set_state(AdminState.waiting_for_promo_max_uses)
        await message.answer("Введите лимит активаций. 0 означает без лимита.")

    @router.message(AdminState.waiting_for_promo_max_uses, F.text)
    async def admin_promo_max_uses_input(message: Message, state: FSMContext) -> None:
        if not await ensure_admin_access(message):
            await state.clear()
            return
        try:
            max_uses = int(message.text.strip())
        except ValueError:
            await message.answer("Нужно отправить целое число 0 или больше.")
            return
        if max_uses < 0:
            await message.answer("Лимит активаций не может быть отрицательным.")
            return
        await state.update_data(promo_max_uses=max_uses)
        await state.set_state(AdminState.waiting_for_promo_description)
        await message.answer("Отправьте описание промокода или символ <code>-</code>, чтобы пропустить.")

    @router.message(AdminState.waiting_for_promo_description, F.text)
    async def admin_promo_description_input(message: Message, state: FSMContext) -> None:
        if not await ensure_admin_access(message):
            await state.clear()
            return
        description_raw = message.text.strip()
        description = None if description_raw in {"-", "нет", "none", "None"} else description_raw
        data = await state.get_data()
        code = data["promo_code"]
        await db.create_promo(
            code=code,
            bonus_days=int(data["promo_bonus_days"]),
            discount_percent=int(data["promo_discount_percent"]),
            max_uses=int(data["promo_max_uses"]),
            description=description,
        )
        await state.clear()

        promos = await db.list_promos(limit=20)
        promo = next((item for item in promos if item["code"] == code), None)
        if promo is not None:
            await show_admin_promo_card(message, int(promo["id"]), "Промокод сохранен.")
            return
        await show_admin_promos_section(message, f"Промокод <code>{escape(code)}</code> сохранен.")

    @router.callback_query(F.data.regexp(r"^admin:promo:\d+:disable$"))
    async def admin_promo_disable_callback(callback: CallbackQuery, state: FSMContext) -> None:
        if not await ensure_admin_access(callback):
            return
        await state.clear()
        promo_id = int(callback.data.split(":")[2])
        promo = await db.get_promo(promo_id)
        if not promo:
            await show_admin_promos_section(callback, "Промокод не найден.")
            return
        await db.disable_promo(str(promo["code"]))
        await show_admin_promo_card(callback, promo_id, "Промокод отключен.")

    @router.callback_query(F.data.regexp(r"^admin:promo:\d+$"))
    async def admin_promo_card_callback(callback: CallbackQuery, state: FSMContext) -> None:
        if not await ensure_admin_access(callback):
            return
        await state.clear()
        promo_id = int(callback.data.split(":")[2])
        await show_admin_promo_card(callback, promo_id)

    @router.callback_query(F.data == "admin:broadcast")
    async def admin_broadcast_callback(callback: CallbackQuery, state: FSMContext) -> None:
        if not await ensure_admin_access(callback):
            return
        await state.clear()
        await show_admin_broadcast_section(callback)

    @router.callback_query(F.data == "admin:broadcast:start")
    async def admin_broadcast_start_callback(callback: CallbackQuery, state: FSMContext) -> None:
        if not await ensure_admin_access(callback):
            return
        await state.set_state(AdminState.waiting_for_broadcast_content)
        await state.update_data(broadcast_mode="manual")
        await callback.message.answer(
            "Отправьте сообщение для рассылки. Поддерживаются текст, фото, видео, анимация и документы.",
            reply_markup=admin_prompt_cancel_keyboard("admin:broadcast"),
        )
        await callback.answer()

    @router.callback_query(F.data == "admin:broadcast:auto")
    async def admin_auto_broadcasts_callback(callback: CallbackQuery, state: FSMContext) -> None:
        if not await ensure_admin_access(callback):
            return
        await state.clear()
        await show_admin_auto_broadcasts_section(callback)

    @router.callback_query(F.data == "admin:broadcast:auto:create")
    async def admin_auto_broadcast_create_callback(callback: CallbackQuery, state: FSMContext) -> None:
        if not await ensure_admin_access(callback):
            return
        await state.set_state(AdminState.waiting_for_broadcast_content)
        await state.update_data(broadcast_mode="auto")
        await callback.message.answer(
            "Отправьте сообщение для авторассылки. Поддерживаются текст, фото, видео, анимация и документы.",
            reply_markup=admin_prompt_cancel_keyboard("admin:broadcast:auto"),
        )
        await callback.answer()

    @router.message(AdminState.waiting_for_broadcast_content)
    async def admin_broadcast_content_input(message: Message, state: FSMContext) -> None:
        if not await ensure_admin_access(message):
            await state.clear()
            return
        if not any((message.text, message.caption, message.photo, message.video, message.animation, message.document)):
            await message.answer("Этот тип сообщения не поддерживается для рассылки.")
            return
        data = await state.get_data()
        mode = str(data.get("broadcast_mode") or "manual")
        await state.update_data(
            broadcast_source_chat_id=message.chat.id,
            broadcast_source_message_id=message.message_id,
            broadcast_summary=describe_broadcast_message(message),
        )
        await state.set_state(AdminState.waiting_for_broadcast_buttons)
        await message.answer(
            "Если нужны кнопки, отправьте их в формате:\n"
            "<code>Текст | https://example.com</code>\n\n"
            "Пустая строка разделяет ряды. Отправьте <code>-</code>, если кнопки не нужны.",
            reply_markup=admin_prompt_cancel_keyboard("admin:broadcast:auto" if mode == "auto" else "admin:broadcast"),
        )

    @router.message(AdminState.waiting_for_broadcast_buttons, F.text)
    async def admin_broadcast_buttons_input(message: Message, state: FSMContext) -> None:
        if not await ensure_admin_access(message):
            await state.clear()
            return
        try:
            button_rows = parse_broadcast_buttons(message.text)
        except ValueError as exc:
            await message.answer(escape(str(exc)))
            return

        data = await state.get_data()
        buttons_json = json.dumps(button_rows, ensure_ascii=False) if button_rows else None
        await state.update_data(broadcast_buttons_json=buttons_json)

        recipients = await db.list_user_telegram_ids()
        summary = str(data.get("broadcast_summary") or "сообщение")
        buttons_count = sum(len(row) for row in button_rows)
        mode = str(data.get("broadcast_mode") or "manual")

        if mode == "auto":
            await state.set_state(AdminState.waiting_for_campaign_name)
            await message.answer("Отправьте название авторассылки для админки.")
            return

        await state.set_state(AdminState.waiting_for_broadcast_confirmation)
        await message.answer(
            admin_broadcast_preview_text(summary, len(recipients), buttons_count),
            reply_markup=admin_broadcast_preview_keyboard(),
        )
        await send_broadcast_copy(
            bot=message.bot,
            chat_id=message.chat.id,
            source_chat_id=int(data["broadcast_source_chat_id"]),
            source_message_id=int(data["broadcast_source_message_id"]),
            button_rows=button_rows,
        )

    @router.message(AdminState.waiting_for_campaign_name, F.text)
    async def admin_auto_broadcast_name_input(message: Message, state: FSMContext) -> None:
        if not await ensure_admin_access(message):
            await state.clear()
            return
        name = message.text.strip()
        if not name:
            await message.answer("Название не может быть пустым.")
            return
        await state.update_data(campaign_name=name)
        await state.set_state(AdminState.waiting_for_campaign_interval)
        await message.answer("Введите интервал запуска в часах. Например: <code>24</code> или <code>72</code>.")

    @router.message(AdminState.waiting_for_campaign_interval, F.text)
    async def admin_auto_broadcast_interval_input(message: Message, state: FSMContext) -> None:
        if not await ensure_admin_access(message):
            await state.clear()
            return
        try:
            interval_hours = int(message.text.strip())
        except ValueError:
            await message.answer("Нужно отправить целое число часов.")
            return
        if interval_hours <= 0:
            await message.answer("Интервал должен быть больше нуля.")
            return

        data = await state.get_data()
        button_rows = parse_campaign_buttons(data.get("broadcast_buttons_json"))
        recipients = await db.list_user_telegram_ids()
        await state.update_data(campaign_interval_hours=interval_hours)
        await state.set_state(AdminState.waiting_for_broadcast_confirmation)
        await message.answer(
            admin_broadcast_preview_text(
                str(data.get("broadcast_summary") or "сообщение"),
                len(recipients),
                sum(len(row) for row in button_rows),
            ),
            reply_markup=admin_broadcast_save_campaign_keyboard(),
        )
        await send_broadcast_copy(
            bot=message.bot,
            chat_id=message.chat.id,
            source_chat_id=int(data["broadcast_source_chat_id"]),
            source_message_id=int(data["broadcast_source_message_id"]),
            button_rows=button_rows,
        )

    @router.message(AdminState.waiting_for_broadcast_confirmation)
    async def admin_broadcast_confirmation_wait(message: Message, state: FSMContext) -> None:
        if not await ensure_admin_access(message):
            await state.clear()
            return
        data = await state.get_data()
        mode = str(data.get("broadcast_mode") or "manual")
        if mode == "auto":
            await message.answer("Предпросмотр готов. Используйте кнопку сохранения под ним.")
            return
        await message.answer("Предпросмотр готов. Используйте кнопку запуска под ним.")

    @router.callback_query(F.data == "admin:broadcast:confirm")
    async def admin_broadcast_confirm_callback(callback: CallbackQuery, state: FSMContext) -> None:
        if not await ensure_admin_access(callback):
            return
        data = await state.get_data()
        source_chat_id = data.get("broadcast_source_chat_id")
        source_message_id = data.get("broadcast_source_message_id")
        if not source_chat_id or not source_message_id:
            await state.clear()
            await show_admin_broadcast_section(callback, "Подготовленное сообщение не найдено.")
            return

        recipients = await db.list_user_telegram_ids()
        button_rows = parse_campaign_buttons(data.get("broadcast_buttons_json"))
        success_count = 0
        failed_count = 0
        await callback.answer("Рассылка запущена.")

        for telegram_id in recipients:
            try:
                await send_broadcast_copy(
                    bot=callback.bot,
                    chat_id=telegram_id,
                    source_chat_id=int(source_chat_id),
                    source_message_id=int(source_message_id),
                    button_rows=button_rows,
                )
                success_count += 1
            except Exception as exc:
                retry_after = getattr(exc, "retry_after", None)
                if retry_after:
                    await asyncio.sleep(float(retry_after))
                    try:
                        await send_broadcast_copy(
                            bot=callback.bot,
                            chat_id=telegram_id,
                            source_chat_id=int(source_chat_id),
                            source_message_id=int(source_message_id),
                            button_rows=button_rows,
                        )
                        success_count += 1
                        await asyncio.sleep(0.05)
                        continue
                    except Exception:
                        failed_count += 1
                else:
                    failed_count += 1
            await asyncio.sleep(0.05)

        await state.clear()
        await show_admin_broadcast_section(
            callback,
            f"Рассылка завершена. Успешно: <b>{success_count}</b>, ошибок: <b>{failed_count}</b>.",
        )

    @router.callback_query(F.data == "admin:broadcast:auto:save")
    async def admin_auto_broadcast_save_callback(callback: CallbackQuery, state: FSMContext) -> None:
        if not await ensure_admin_access(callback):
            return
        data = await state.get_data()
        source_chat_id = data.get("broadcast_source_chat_id")
        source_message_id = data.get("broadcast_source_message_id")
        campaign_name = data.get("campaign_name")
        interval_hours = data.get("campaign_interval_hours")
        if not all((source_chat_id, source_message_id, campaign_name, interval_hours)):
            await state.clear()
            await show_admin_auto_broadcasts_section(callback, "Не удалось сохранить авторассылку.")
            return

        campaign = await db.create_broadcast_campaign(
            name=str(campaign_name),
            source_chat_id=int(source_chat_id),
            source_message_id=int(source_message_id),
            buttons_json=data.get("broadcast_buttons_json"),
            interval_hours=int(interval_hours),
        )
        await state.clear()
        await show_admin_auto_broadcast_card(callback, int(campaign["id"]), "Авторассылка сохранена.")

    @router.callback_query(F.data.regexp(r"^admin:broadcast:auto:\d+$"))
    async def admin_auto_broadcast_card_callback(callback: CallbackQuery, state: FSMContext) -> None:
        if not await ensure_admin_access(callback):
            return
        await state.clear()
        campaign_id = int(callback.data.split(":")[3])
        await show_admin_auto_broadcast_card(callback, campaign_id)

    @router.callback_query(F.data.regexp(r"^admin:broadcast:auto:\d+:toggle$"))
    async def admin_auto_broadcast_toggle_callback(callback: CallbackQuery, state: FSMContext) -> None:
        if not await ensure_admin_access(callback):
            return
        await state.clear()
        campaign_id = int(callback.data.split(":")[3])
        campaign = await db.get_broadcast_campaign(campaign_id)
        if not campaign:
            await show_admin_auto_broadcasts_section(callback, "Авторассылка не найдена.")
            return
        await db.set_broadcast_campaign_active(campaign_id, int(campaign.get("is_active") or 0) != 1)
        await show_admin_auto_broadcast_card(callback, campaign_id, "Статус авторассылки обновлен.")

    @router.callback_query(F.data.regexp(r"^admin:broadcast:auto:\d+:run$"))
    async def admin_auto_broadcast_run_callback(callback: CallbackQuery, state: FSMContext) -> None:
        if not await ensure_admin_access(callback):
            return
        await state.clear()
        campaign_id = int(callback.data.split(":")[3])
        campaign = await db.get_broadcast_campaign(campaign_id)
        if not campaign:
            await show_admin_auto_broadcasts_section(callback, "Авторассылка не найдена.")
            return
        await db.schedule_broadcast_campaign_now(campaign_id)
        await show_admin_auto_broadcast_card(callback, campaign_id, "Авторассылка поставлена в ближайший запуск.")

    @router.message(Command("promo_add"))
    async def admin_add_promo(message: Message) -> None:
        if not is_admin(config, message.from_user.id):
            return
        parts = (message.text or "").split(maxsplit=5)
        if len(parts) < 5:
            await message.answer(
                "Формат: <code>/promo_add CODE BONUS_DAYS DISCOUNT_PERCENT MAX_USES [DESCRIPTION]</code>"
            )
            return
        _, code, bonus_days, discount_percent, max_uses, *rest = parts
        description = rest[0] if rest else None
        await db.create_promo(
            code=code,
            bonus_days=int(bonus_days),
            discount_percent=int(discount_percent),
            max_uses=int(max_uses),
            description=description,
        )
        await message.answer(f"Промокод <code>{escape(code.upper())}</code> сохранён.")

    @router.message(Command("promo_disable"))
    async def admin_disable_promo(message: Message) -> None:
        if not is_admin(config, message.from_user.id):
            return
        parts = (message.text or "").split(maxsplit=1)
        if len(parts) < 2:
            await message.answer("Формат: <code>/promo_disable CODE</code>")
            return
        disabled = await db.disable_promo(parts[1].strip())
        await message.answer("Промокод выключен." if disabled else "Промокод не найден.")

    @router.message(Command("give_days"))
    async def admin_give_days(message: Message) -> None:
        if not is_admin(config, message.from_user.id):
            return
        parts = (message.text or "").split()
        if len(parts) != 3:
            await message.answer("Формат: <code>/give_days TELEGRAM_ID DAYS</code>")
            return
        telegram_id = int(parts[1])
        days = int(parts[2])
        user = await db.get_user_by_telegram_id(telegram_id)
        if not user:
            await message.answer("Пользователь не найден.")
            return
        await db.credit_bonus_days(user["id"], days)
        await message.answer(f"Начислено <b>{days}</b> бонусных дней пользователю <code>{telegram_id}</code>.")

    @router.message(Command("order_check"))
    async def admin_order_check(message: Message) -> None:
        if not is_admin(config, message.from_user.id):
            return
        parts = (message.text or "").split()
        if len(parts) != 2:
            await message.answer("Формат: <code>/order_check ORDER_ID</code>")
            return
        order_id = int(parts[1])
        order = await db.get_order(order_id)
        if not order:
            await message.answer("Заказ не найден.")
            return
        invoice_id = order.get("payment_invoice_id")
        provider_label = payment_provider_label(str(order.get("payment_provider") or PAYMENT_PROVIDER_CRYPTO_BOT))
        await message.answer(
            "🧾 Заказ\n"
            f"ID: <code>{order['id']}</code>\n"
            f"Пользователь: <code>{order['telegram_id']}</code>\n"
            f"Провайдер: <b>{escape(provider_label)}</b>\n"
            f"Статус заказа: <b>{escape(order['status'])}</b>\n"
            f"Статус инвойса: <b>{escape(str(order.get('payment_status') or '-'))}</b>\n"
            f"Invoice ID: <code>{escape(str(invoice_id or '-'))}</code>"
        )

    return router


async def auto_broadcast_worker(bot: Bot, db: Database) -> None:
    logger = logging.getLogger(__name__)
    while True:
        campaigns = await db.list_due_broadcast_campaigns()
        for campaign in campaigns:
            recipients = await db.list_user_telegram_ids()
            button_rows = parse_campaign_buttons(campaign.get("buttons_json"))
            success_count = 0
            failed_count = 0

            for telegram_id in recipients:
                try:
                    await send_broadcast_copy(
                        bot=bot,
                        chat_id=telegram_id,
                        source_chat_id=int(campaign["source_chat_id"]),
                        source_message_id=int(campaign["source_message_id"]),
                        button_rows=button_rows,
                    )
                    success_count += 1
                except Exception as exc:
                    retry_after = getattr(exc, "retry_after", None)
                    if retry_after:
                        await asyncio.sleep(float(retry_after))
                        try:
                            await send_broadcast_copy(
                                bot=bot,
                                chat_id=telegram_id,
                                source_chat_id=int(campaign["source_chat_id"]),
                                source_message_id=int(campaign["source_message_id"]),
                                button_rows=button_rows,
                            )
                            success_count += 1
                            await asyncio.sleep(0.05)
                            continue
                        except Exception:
                            failed_count += 1
                    else:
                        failed_count += 1
                await asyncio.sleep(0.05)

            await db.mark_broadcast_campaign_sent(
                int(campaign["id"]),
                success_count=success_count,
                failed_count=failed_count,
            )
            logger.info(
                "Auto broadcast #%s completed: success=%s failed=%s",
                campaign["id"],
                success_count,
                failed_count,
            )

        await asyncio.sleep(60)


async def run_bot() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )

    config = load_config()
    db = Database(config.database_url)
    await db.connect()

    bot = Bot(
        token=config.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    crypto_bot = CryptoPayClient(config)
    yoomoney = YooMoneyClient(config)
    freekassa = FreeKassaClient(config)
    payment_gateway = PaymentGateway(
        crypto_bot=crypto_bot,
        yoomoney=yoomoney,
        freekassa=freekassa,
    )
    remnawave = RemnawaveClient(config)

    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(create_router(config, db, payment_gateway, remnawave))
    broadcast_task = asyncio.create_task(auto_broadcast_worker(bot, db))

    try:
        await bot.delete_webhook(drop_pending_updates=True)
        await dp.start_polling(bot)
    finally:
        broadcast_task.cancel()
        with suppress(asyncio.CancelledError):
            await broadcast_task
        await crypto_bot.close()
        await yoomoney.close()
        await freekassa.close()
        await remnawave.close()
        await db.close()
        await bot.session.close()


def main() -> None:
    asyncio.run(run_bot())
