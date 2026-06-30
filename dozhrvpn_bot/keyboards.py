from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from dozhrvpn_bot.config import Config, Plan
from dozhrvpn_bot.ui import (
    BACK_BUTTON_TEXT,
    EMOJI_IDS,
    MENU_ADMIN,
    MENU_BONUSES,
    MENU_INSTRUCTIONS,
    MENU_PAYMENT,
    MENU_PROFILE,
)


def _truncate(value: str, limit: int = 36) -> str:
    if len(value) <= limit:
        return value
    return f"{value[: limit - 1]}…"


def _reply_button(text: str, *, icon: str | None = None, style: str | None = None) -> KeyboardButton:
    payload: dict[str, str] = {"text": text}
    if icon:
        payload["icon_custom_emoji_id"] = EMOJI_IDS[icon]
    if style:
        payload["style"] = style
    return KeyboardButton(**payload)


def _inline_button(
    builder: InlineKeyboardBuilder,
    text: str,
    *,
    icon: str | None = None,
    style: str | None = None,
    **kwargs: str | int,
) -> None:
    if icon:
        kwargs["icon_custom_emoji_id"] = EMOJI_IDS[icon]
    if style:
        kwargs["style"] = style
    builder.button(text=text, **kwargs)


def main_menu_keyboard(show_admin: bool = False) -> ReplyKeyboardMarkup:
    keyboard = [
        [
            _reply_button(MENU_PAYMENT, icon="wallet", style="primary"),
            _reply_button(MENU_PROFILE, icon="profile"),
        ],
        [
            _reply_button(MENU_INSTRUCTIONS, icon="file"),
            _reply_button(MENU_BONUSES, icon="gift"),
        ],
    ]
    if show_admin:
        keyboard.append([_reply_button(MENU_ADMIN, icon="settings")])

    return ReplyKeyboardMarkup(
        keyboard=keyboard,
        resize_keyboard=True,
        input_field_placeholder="Выберите раздел",
    )


def channel_gate_keyboard(config: Config) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    _inline_button(builder, "Подписаться", url=config.required_channel_url, icon="megaphone", style="primary")
    _inline_button(builder, "Проверить подписку", callback_data="check_channel", icon="check", style="success")
    builder.adjust(1)
    return builder.as_markup()


def payment_menu_keyboard(plans: tuple[Plan, ...]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for plan in plans:
        suffix = f" • {plan.badge}" if plan.badge else ""
        _inline_button(
            builder,
            text=f"{plan.title} • {plan.price_rub} ₽{suffix}",
            callback_data=f"buy:{plan.key}",
            icon="money",
        )
    builder.adjust(1)
    return builder.as_markup()


def payment_methods_keyboard(
    plan_key: str,
    methods: tuple[tuple[str, str], ...],
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for provider, title in methods:
        _inline_button(
            builder,
            text=title,
            callback_data=f"pay:{provider}:{plan_key}",
            icon="money_send",
            style="primary" if provider == "crypto_bot" else None,
        )
    _inline_button(builder, "К тарифам", callback_data="back_to_payment")
    builder.adjust(1)
    return builder.as_markup()


def custom_inline_keyboard(button_rows: list[list[dict[str, str]]]) -> InlineKeyboardMarkup | None:
    if not button_rows:
        return None
    builder = InlineKeyboardBuilder()
    widths: list[int] = []
    for row in button_rows:
        for button in row:
            builder.button(text=button["text"], url=button["url"])
        widths.append(len(row))
    builder.adjust(*widths)
    return builder.as_markup()


def invoice_keyboard(
    pay_url: str,
    order_id: int,
    extra_url: str | None = None,
    extra_label: str | None = None,
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    _inline_button(builder, "Оплатить", url=pay_url, icon="money_send", style="primary")
    if extra_url:
        _inline_button(builder, extra_label or "Доп. ссылка", url=extra_url, icon="apps")
    _inline_button(builder, "Проверить оплату", callback_data=f"check_order:{order_id}", icon="check", style="success")
    _inline_button(builder, "К тарифам", callback_data="back_to_payment")
    builder.adjust(1)
    return builder.as_markup()


def bonuses_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    _inline_button(builder, "Активировать промокод", callback_data="bonus:promo", icon="tag", style="primary")
    _inline_button(builder, "Реферальная ссылка", callback_data="bonus:referral", icon="people")
    _inline_button(builder, "Партнерская программа", callback_data="bonus:partner", icon="people_check")
    builder.adjust(1)
    return builder.as_markup()


def profile_keyboard(subscription_url: str | None) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if subscription_url:
        _inline_button(builder, "Subscription URL", url=subscription_url, icon="link")
    _inline_button(builder, "Обновить", callback_data="profile:refresh", icon="loading")
    builder.adjust(1)
    return builder.as_markup()


def instructions_keyboard(config: Config, subscription_url: str | None) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if subscription_url:
        _inline_button(builder, "Подписка", url=subscription_url, icon="link")
    if config.instruction_android_url:
        _inline_button(builder, "Android", url=config.instruction_android_url, icon="bot")
    if config.instruction_ios_url:
        _inline_button(builder, "iPhone", url=config.instruction_ios_url, icon="apps")
    if config.instruction_windows_url:
        _inline_button(builder, "Windows", url=config.instruction_windows_url, icon="apps")
    if config.instruction_macos_url:
        _inline_button(builder, "macOS", url=config.instruction_macos_url, icon="apps")
    _inline_button(builder, "Поддержка", url=config.support_url, icon="info")
    builder.adjust(2)
    return builder.as_markup()


def admin_panel_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    _inline_button(builder, "Сводка", callback_data="admin:stats", icon="chart")
    _inline_button(builder, "Пользователи", callback_data="admin:users", icon="people")
    _inline_button(builder, "Заказы", callback_data="admin:orders", icon="money")
    _inline_button(builder, "Промокоды", callback_data="admin:promos", icon="tag")
    _inline_button(builder, "Рассылки", callback_data="admin:broadcast", icon="megaphone")
    _inline_button(builder, "Настройки", callback_data="admin:settings", icon="settings")
    _inline_button(builder, "Обновить", callback_data="admin:home", icon="loading")
    builder.adjust(2, 2, 2, 1)
    return builder.as_markup()


def admin_users_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    _inline_button(builder, "Найти пользователя", callback_data="admin:users:search", icon="eye")
    _inline_button(builder, "Последние регистрации", callback_data="admin:users:recent", icon="calendar")
    _inline_button(builder, "В админку", callback_data="admin:home", icon="home")
    builder.adjust(1)
    return builder.as_markup()


def admin_orders_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    _inline_button(builder, "Найти заказ", callback_data="admin:orders:search", icon="eye")
    _inline_button(builder, "Последние заказы", callback_data="admin:orders:recent", icon="clock")
    _inline_button(builder, "В админку", callback_data="admin:home", icon="home")
    builder.adjust(1)
    return builder.as_markup()


def admin_promos_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    _inline_button(builder, "Создать промокод", callback_data="admin:promos:create", icon="pencil", style="primary")
    _inline_button(builder, "Все промокоды", callback_data="admin:promos:list", icon="file")
    _inline_button(builder, "В админку", callback_data="admin:home", icon="home")
    builder.adjust(1)
    return builder.as_markup()


def admin_broadcast_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    _inline_button(builder, "Разовая рассылка", callback_data="admin:broadcast:start", icon="megaphone", style="primary")
    _inline_button(builder, "Авторассылки", callback_data="admin:broadcast:auto", icon="calendar")
    _inline_button(builder, "В админку", callback_data="admin:home", icon="home")
    builder.adjust(1)
    return builder.as_markup()


def admin_prompt_cancel_keyboard(back_callback: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    _inline_button(builder, "Отмена", callback_data=back_callback, icon="cross", style="danger")
    builder.adjust(1)
    return builder.as_markup()


def admin_user_results_keyboard(users: list[dict], *, back_callback: str = "admin:users") -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for user in users:
        username = f"@{user['username']}" if user.get("username") else f"ID {user['telegram_id']}"
        _inline_button(
            builder,
            text=_truncate(username),
            callback_data=f"admin:user:{user['id']}",
            icon="profile",
        )
    _inline_button(builder, BACK_BUTTON_TEXT, callback_data=back_callback)
    builder.adjust(1)
    return builder.as_markup()


def admin_user_card_keyboard(user_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    _inline_button(builder, "Начислить дни", callback_data=f"admin:user:{user_id}:days", icon="gift", style="success")
    _inline_button(builder, "Установить скидку", callback_data=f"admin:user:{user_id}:discount", icon="money", style="primary")
    _inline_button(builder, "Синхронизировать", callback_data=f"admin:user:{user_id}:sync", icon="loading")
    _inline_button(builder, "Заказы пользователя", callback_data=f"admin:user:{user_id}:orders", icon="package")
    _inline_button(builder, "К пользователям", callback_data="admin:users")
    _inline_button(builder, "В админку", callback_data="admin:home", icon="home")
    builder.adjust(2, 2, 2)
    return builder.as_markup()


def admin_orders_list_keyboard(orders: list[dict], *, back_callback: str = "admin:orders") -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for order in orders:
        plan_name = _truncate(str(order.get("plan_name") or order.get("plan_key") or "заказ"), 24)
        _inline_button(
            builder,
            text=f"#{order['id']} • {plan_name}",
            callback_data=f"admin:order:{order['id']}",
            icon="money",
        )
    _inline_button(builder, BACK_BUTTON_TEXT, callback_data=back_callback)
    builder.adjust(1)
    return builder.as_markup()


def admin_order_card_keyboard(order_id: int, user_id: int, provider_label: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    _inline_button(
        builder,
        f"Проверить через {provider_label}",
        callback_data=f"admin:order:{order_id}:refresh",
        icon="loading",
    )
    _inline_button(builder, "Открыть пользователя", callback_data=f"admin:user:{user_id}", icon="profile")
    _inline_button(builder, "К заказам", callback_data="admin:orders")
    _inline_button(builder, "В админку", callback_data="admin:home", icon="home")
    builder.adjust(1)
    return builder.as_markup()


def admin_promos_list_keyboard(promos: list[dict]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for promo in promos:
        is_active = int(promo.get("is_active") or 0) == 1
        status = "активен" if is_active else "выключен"
        _inline_button(
            builder,
            text=_truncate(f"{promo['code']} • {status}", 32),
            callback_data=f"admin:promo:{promo['id']}",
            icon="check" if is_active else "cross",
        )
    _inline_button(builder, "К промокодам", callback_data="admin:promos")
    builder.adjust(1)
    return builder.as_markup()


def admin_promo_card_keyboard(promo_id: int, *, is_active: bool) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if is_active:
        _inline_button(
            builder,
            "Выключить промокод",
            callback_data=f"admin:promo:{promo_id}:disable",
            icon="cross",
            style="danger",
        )
    _inline_button(builder, "К списку", callback_data="admin:promos:list", icon="file")
    _inline_button(builder, "В админку", callback_data="admin:home", icon="home")
    builder.adjust(1)
    return builder.as_markup()


def admin_broadcast_preview_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    _inline_button(builder, "Запустить рассылку", callback_data="admin:broadcast:confirm", icon="check", style="success")
    _inline_button(builder, "Отменить", callback_data="admin:broadcast", icon="cross", style="danger")
    builder.adjust(1)
    return builder.as_markup()


def admin_auto_broadcasts_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    _inline_button(builder, "Создать авторассылку", callback_data="admin:broadcast:auto:create", icon="pencil", style="primary")
    _inline_button(builder, "К рассылкам", callback_data="admin:broadcast", icon="megaphone")
    _inline_button(builder, "В админку", callback_data="admin:home", icon="home")
    builder.adjust(1)
    return builder.as_markup()


def admin_auto_broadcasts_list_keyboard(campaigns: list[dict]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for campaign in campaigns:
        status = "активна" if int(campaign.get("is_active") or 0) == 1 else "выкл"
        _inline_button(
            builder,
            text=_truncate(f"{campaign['name']} • {status}", 32),
            callback_data=f"admin:broadcast:auto:{campaign['id']}",
            icon="calendar",
        )
    _inline_button(builder, "Создать авторассылку", callback_data="admin:broadcast:auto:create", icon="pencil", style="primary")
    _inline_button(builder, "К рассылкам", callback_data="admin:broadcast", icon="megaphone")
    builder.adjust(1)
    return builder.as_markup()


def admin_auto_broadcast_card_keyboard(campaign_id: int, *, is_active: bool) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if is_active:
        _inline_button(
            builder,
            "Отключить",
            callback_data=f"admin:broadcast:auto:{campaign_id}:toggle",
            icon="cross",
            style="danger",
        )
    else:
        _inline_button(
            builder,
            "Включить",
            callback_data=f"admin:broadcast:auto:{campaign_id}:toggle",
            icon="check",
            style="success",
        )
    _inline_button(
        builder,
        "Запустить сейчас",
        callback_data=f"admin:broadcast:auto:{campaign_id}:run",
        icon="loading",
        style="primary",
    )
    _inline_button(builder, "К авторассылкам", callback_data="admin:broadcast:auto", icon="calendar")
    builder.adjust(1)
    return builder.as_markup()


def admin_broadcast_save_campaign_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    _inline_button(
        builder,
        "Сохранить авторассылку",
        callback_data="admin:broadcast:auto:save",
        icon="check",
        style="success",
    )
    _inline_button(builder, "Отменить", callback_data="admin:broadcast:auto", icon="cross", style="danger")
    builder.adjust(1)
    return builder.as_markup()


def admin_settings_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    _inline_button(builder, "Название VPN", callback_data="admin:settings:brand", icon="pencil")
    _inline_button(builder, "Канал подписки", callback_data="admin:settings:channel", icon="megaphone")
    _inline_button(builder, "Реферальный бонус", callback_data="admin:settings:referral", icon="gift")
    _inline_button(builder, "Платежи", callback_data="admin:settings:payments", icon="money")
    _inline_button(builder, "Тарифы", callback_data="admin:settings:plans", icon="package")
    _inline_button(builder, "В админку", callback_data="admin:home", icon="home")
    builder.adjust(1)
    return builder.as_markup()


def admin_payment_settings_keyboard(
    *,
    crypto_bot_enabled: bool,
    yoomoney_enabled: bool,
    freekassa_enabled: bool,
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    _inline_button(
        builder,
        "Выключить Crypto Bot" if crypto_bot_enabled else "Включить Crypto Bot",
        callback_data="admin:settings:payments:crypto",
        icon="cross" if crypto_bot_enabled else "check",
        style="danger" if crypto_bot_enabled else "success",
    )
    _inline_button(
        builder,
        "Выключить YooMoney" if yoomoney_enabled else "Включить YooMoney",
        callback_data="admin:settings:payments:yoomoney",
        icon="cross" if yoomoney_enabled else "check",
        style="danger" if yoomoney_enabled else "success",
    )
    _inline_button(
        builder,
        "Выключить FreeKassa" if freekassa_enabled else "Включить FreeKassa",
        callback_data="admin:settings:payments:freekassa",
        icon="cross" if freekassa_enabled else "check",
        style="danger" if freekassa_enabled else "success",
    )
    _inline_button(builder, "К настройкам", callback_data="admin:settings", icon="settings")
    builder.adjust(1)
    return builder.as_markup()


def admin_plans_keyboard(plans: tuple[Plan, ...]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for plan in plans:
        _inline_button(
            builder,
            text=_truncate(f"{plan.title} • {plan.price_rub} ₽", 32),
            callback_data=f"admin:settings:plan:{plan.key}",
            icon="package",
        )
    _inline_button(builder, "К настройкам", callback_data="admin:settings", icon="settings")
    builder.adjust(1)
    return builder.as_markup()


def admin_plan_card_keyboard(plan_key: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    _inline_button(
        builder,
        "Изменить цену",
        callback_data=f"admin:settings:plan:{plan_key}:price",
        icon="money",
        style="primary",
    )
    _inline_button(builder, "К тарифам", callback_data="admin:settings:plans", icon="package")
    builder.adjust(1)
    return builder.as_markup()
