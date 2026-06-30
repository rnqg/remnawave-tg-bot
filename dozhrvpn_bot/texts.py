from __future__ import annotations

from datetime import UTC, datetime
from html import escape

from dozhrvpn_bot.config import Config, Plan
from dozhrvpn_bot.database import from_iso
from dozhrvpn_bot.payments import build_payment_status_line, payment_provider_label
from dozhrvpn_bot.ui import tg_emoji


def welcome_text(config: Config, first_name: str | None) -> str:
    name = escape(first_name or "пользователь")
    return (
        f"{tg_emoji('lock', '🔒')} <b>{escape(config.brand_name)}</b>\n\n"
        f"Профиль: <b>{name}</b>\n"
        "Через бот доступна оплата, получение subscription URL, инструкции и бонусные функции.\n\n"
        "Выберите нужный раздел в меню."
    )


def channel_gate_text(config: Config) -> str:
    return (
        f"{tg_emoji('megaphone', '📣')} <b>Требуется подписка на канал</b>\n\n"
        f"Канал для проверки: <b>{escape(config.required_channel_id)}</b>\n\n"
        "Подпишитесь и нажмите кнопку проверки."
    )


def payment_text(config: Config, discount_percent: int, bonus_days: int) -> str:
    extra = []
    if discount_percent > 0:
        extra.append(f"{tg_emoji('tag', '🏷')} Скидка на ближайшую оплату: <b>{discount_percent}%</b>.")
    if bonus_days > 0:
        extra.append(f"{tg_emoji('gift', '🎁')} Бонусные дни в резерве: <b>{bonus_days}</b>.")

    extra_body = "\n".join(extra)
    extra_text = f"\n\n{extra_body}" if extra_body else ""
    return (
        f"{tg_emoji('money', '🪙')} <b>Тарифы {escape(config.brand_name)}</b>\n\n"
        "Выберите тариф, затем удобный способ оплаты. После оплаты статус проверяется по кнопке подтверждения."
        f"{extra_text}"
    )


def payment_methods_text(plan_name: str, amount: str) -> str:
    return (
        f"{tg_emoji('money_send', '💸')} <b>Способ оплаты</b>\n\n"
        f"Тариф: <b>{escape(plan_name)}</b>\n"
        f"Сумма: <b>{escape(amount)} ₽</b>\n\n"
        "Выберите платежный метод."
    )


def payments_disabled_text() -> str:
    return (
        f"{tg_emoji('cross', '❌')} <b>Оплата временно недоступна</b>\n\n"
        "Платежные методы отключены в настройках. Повторите попытку позже или обратитесь в поддержку."
    )


def invoice_text(plan_name: str, days: int, amount: str, order_id: int, provider_name: str) -> str:
    return (
        f"{tg_emoji('file', '📁')} <b>Счет сформирован</b>\n\n"
        f"Тариф: <b>{escape(plan_name)}</b>\n"
        f"Период: <b>{days} дней</b>\n"
        f"Сумма: <b>{escape(amount)} ₽</b>\n"
        f"Способ оплаты: <b>{escape(provider_name)}</b>\n"
        f"Заказ: <code>#{order_id}</code>\n\n"
        "1. Откройте оплату.\n"
        "2. После оплаты вернитесь в бот.\n"
        "3. Нажмите кнопку проверки статуса."
    )


def _days_left(expires_at_raw: str | None) -> tuple[int, str]:
    expires_at = from_iso(expires_at_raw)
    if not expires_at:
        return 0, "нет активной подписки"
    now = datetime.now(UTC)
    delta = expires_at - now
    days = max(0, int(delta.total_seconds() // 86400))
    return days, expires_at.astimezone(UTC).strftime("%d.%m.%Y %H:%M UTC")


def profile_text(config: Config, profile_stats: dict) -> str:
    user = profile_stats["user"]
    days_left, expires = _days_left(user.get("subscription_expires_at"))
    username = f"@{escape(user['username'])}" if user.get("username") else "не указан"
    subscription_url = user.get("remnawave_subscription_url") or "будет доступен после оплаты"
    return (
        f"{tg_emoji('profile', '👤')} <b>Профиль {escape(config.brand_name)}</b>\n\n"
        f"Telegram ID: <code>{user['telegram_id']}</code>\n"
        f"Username: <b>{username}</b>\n"
        f"{tg_emoji('tag', '🏷')} Реферальный код: <code>{user['ref_code']}</code>\n"
        f"{tg_emoji('clock', '⏰')} Остаток дней: <b>{days_left}</b>\n"
        f"{tg_emoji('calendar', '📅')} Активно до: <b>{expires}</b>\n"
        f"{tg_emoji('gift', '🎁')} Бонусные дни: <b>{user['bonus_days_balance']}</b>\n"
        f"{tg_emoji('money', '🪙')} Скидка на следующую оплату: <b>{user['pending_discount_percent']}%</b>\n"
        f"{tg_emoji('people', '👥')} Приглашено: <b>{profile_stats['referrals_total']}</b>\n"
        f"{tg_emoji('check', '✅')} Оплативших рефералов: <b>{profile_stats['paid_referrals']}</b>\n"
        f"{tg_emoji('package', '📦')} Активированных заказов: <b>{profile_stats['paid_orders']}</b>\n\n"
        f"{tg_emoji('link', '🔗')} Subscription URL:\n<code>{escape(subscription_url)}</code>"
    )


def instructions_text(config: Config, subscription_url: str | None) -> str:
    link_part = (
        f"{tg_emoji('link', '🔗')} Subscription URL:\n<code>{escape(subscription_url)}</code>\n\n"
        if subscription_url
        else f"{tg_emoji('link', '🔗')} Subscription URL появится после первой успешной оплаты.\n\n"
    )
    return (
        f"{tg_emoji('file', '📁')} <b>Инструкции и поддержка</b>\n\n"
        f"{link_part}"
        "1. Откройте инструкцию для своей платформы.\n"
        "2. Импортируйте subscription URL в клиент.\n"
        "3. При проблемах используйте поддержку.\n\n"
        f"{tg_emoji('info', 'ℹ')} Поддержка: {escape(config.support_label)}"
    )


def bonuses_text(config: Config, profile_stats: dict, referral_link: str, promos: list[dict]) -> str:
    promo_lines = []
    for promo in promos:
        parts = [f"<code>{promo['code']}</code>"]
        if int(promo["discount_percent"]) > 0:
            parts.append(f"{promo['discount_percent']}% скидки")
        if int(promo["bonus_days"]) > 0:
            parts.append(f"+{promo['bonus_days']} дн.")
        if promo.get("description"):
            parts.append(escape(promo["description"]))
        promo_lines.append(" • ".join(parts))
    promo_block = "\n".join(promo_lines) if promo_lines else "Публичные промокоды отсутствуют."
    return (
        f"{tg_emoji('gift', '🎁')} <b>Бонусы и рефералы</b>\n\n"
        f"{tg_emoji('people', '👥')} Реферальная ссылка:\n<code>{escape(referral_link)}</code>\n\n"
        f"{tg_emoji('people_check', '👤')} Вознаграждение за первого оплаченного реферала: "
        f"<b>+{config.referral_reward_days} дней</b>\n"
        f"{tg_emoji('chart', '📊')} Оплативших рефералов: <b>{profile_stats['paid_referrals']}</b>\n"
        f"{tg_emoji('gift', '🎁')} Всего начислено бонусных дней: "
        f"<b>{profile_stats['user']['total_bonus_days_earned']}</b>\n\n"
        f"{tg_emoji('tag', '🏷')} Доступные промокоды:\n{promo_block}"
    )


def partner_program_text(config: Config, profile_stats: dict, referral_link: str) -> str:
    return (
        f"{tg_emoji('people_check', '👤')} <b>Партнерская программа</b>\n\n"
        f"{escape(config.partner_program_text)}\n\n"
        f"{tg_emoji('link', '🔗')} Партнерская ссылка:\n<code>{escape(referral_link)}</code>\n"
        f"{tg_emoji('people', '👥')} Приглашено: <b>{profile_stats['referrals_total']}</b>\n"
        f"{tg_emoji('check', '✅')} Оплативших: <b>{profile_stats['paid_referrals']}</b>\n"
        f"{tg_emoji('gift', '🎁')} Начислено дней: <b>{profile_stats['user']['total_bonus_days_earned']}</b>"
    )


def promo_activation_prompt() -> str:
    return (
        f"{tg_emoji('tag', '🏷')} <b>Активация промокода</b>\n\n"
        "Отправьте код одним сообщением."
    )


def _format_amount(value: float | int | str | None) -> str:
    if value in (None, ""):
        return "0.00"
    try:
        return f"{float(value):.2f}"
    except (TypeError, ValueError):
        return escape(str(value))


def _format_short_date(value: str | None) -> str:
    parsed = from_iso(value)
    if not parsed:
        return "не указано"
    return parsed.astimezone(UTC).strftime("%d.%m.%Y %H:%M UTC")


def _payment_states(config: Config) -> tuple[dict[str, object], ...]:
    return (
        {
            "title": "Crypto Bot",
            "enabled": config.crypto_pay_enabled,
            "configured": bool(config.crypto_pay_token),
        },
        {
            "title": "YooMoney",
            "enabled": config.yoomoney_enabled,
            "configured": bool(config.yoomoney_wallet and config.yoomoney_token),
        },
        {
            "title": "FreeKassa",
            "enabled": config.freekassa_enabled,
            "configured": bool(
                config.freekassa_shop_id
                and config.freekassa_api_key
                and config.freekassa_payment_system_id
                and config.freekassa_payer_email
            ),
        },
    )


def admin_dashboard_text(config: Config, stats: dict) -> str:
    recent_orders = stats.get("recent_orders") or []
    if recent_orders:
        recent_block = "\n".join(
            (
                f"• <code>#{order['id']}</code> • <code>{order['telegram_id']}</code> • "
                f"{escape(order['plan_name'])} • {escape(str(order['final_amount']))} ₽ • "
                f"{escape(order['status'])}/{escape(str(order.get('payment_status') or '-'))}"
            )
            for order in recent_orders
        )
    else:
        recent_block = "Нет заказов."

    return (
        f"{tg_emoji('settings', '⚙️')} <b>Админ-панель {escape(config.brand_name)}</b>\n\n"
        f"{tg_emoji('people', '👥')} Пользователи: <b>{stats['total_users']}</b>\n"
        f"За 24 часа: <b>{stats['users_24h']}</b>\n"
        f"{tg_emoji('calendar', '📅')} За 7 дней: <b>{stats['users_7d']}</b>\n\n"
        f"{tg_emoji('check', '✅')} Активные подписки: <b>{stats['active_subscriptions']}</b>\n"
        f"{tg_emoji('cross', '❌')} Истекшие подписки: <b>{stats['expired_subscriptions']}</b>\n\n"
        f"{tg_emoji('file', '📁')} Заказы: <b>{stats['total_orders']}</b>\n"
        f"{tg_emoji('clock', '⏰')} Pending: <b>{stats['pending_orders']}</b>\n"
        f"{tg_emoji('money_receive', '🏧')} Paid без активации: <b>{stats['paid_not_activated']}</b>\n"
        f"{tg_emoji('check', '✅')} Активировано: <b>{stats['activated_orders']}</b>\n\n"
        f"{tg_emoji('money', '🪙')} Выручка: <b>{_format_amount(stats['total_revenue'])} ₽</b>\n"
        f"{tg_emoji('tag', '🏷')} Активные промокоды: <b>{stats['active_promos']}</b>\n"
        f"{tg_emoji('gift', '🎁')} Активации промокодов: <b>{stats['promo_redemptions']}</b>\n"
        f"{tg_emoji('people_check', '👤')} Начислено по рефералам: "
        f"<b>{stats['referral_reward_days']} дней</b>\n\n"
        f"Последние заказы:\n{recent_block}"
    )


def admin_users_text() -> str:
    return (
        f"{tg_emoji('people', '👥')} <b>Пользователи</b>\n\n"
        "Доступен поиск по Telegram ID, @username, внутреннему ID и реферальному коду."
    )


def admin_user_results_text(query: str, users: list[dict]) -> str:
    if not users:
        return (
            f"{tg_emoji('people', '👥')} <b>Пользователи</b>\n\n"
            f"По запросу <code>{escape(query)}</code> совпадений нет."
        )

    lines = []
    for user in users:
        username = f"@{escape(user['username'])}" if user.get("username") else "без username"
        lines.append(f"• <code>{user['telegram_id']}</code> • {username} • ref <code>{escape(user['ref_code'])}</code>")

    return (
        f"{tg_emoji('people', '👥')} <b>Результаты поиска</b>\n\n"
        f"Запрос: <code>{escape(query)}</code>\n\n"
        + "\n".join(lines)
    )


def admin_user_text(config: Config, profile_stats: dict) -> str:
    user = profile_stats["user"]
    days_left, expires = _days_left(user.get("subscription_expires_at"))
    username = f"@{escape(user['username'])}" if user.get("username") else "не указан"
    full_name = " ".join(part for part in [user.get("first_name"), user.get("last_name")] if part) or "не указано"
    recent_orders = profile_stats.get("recent_orders") or []
    orders_block = (
        "\n".join(
            (
                f"• <code>#{order['id']}</code> • {escape(order['plan_name'])} • "
                f"{escape(str(order['final_amount']))} ₽ • {escape(order['status'])}"
            )
            for order in recent_orders
        )
        if recent_orders
        else "Нет заказов."
    )
    subscription_url = user.get("remnawave_subscription_url") or "не выдан"
    return (
        f"{tg_emoji('profile', '👤')} <b>Карточка пользователя {escape(config.brand_name)}</b>\n\n"
        f"Внутренний ID: <code>{user['id']}</code>\n"
        f"Telegram ID: <code>{user['telegram_id']}</code>\n"
        f"Username: <b>{username}</b>\n"
        f"Имя: <b>{escape(full_name)}</b>\n"
        f"{tg_emoji('tag', '🏷')} Реферальный код: <code>{user['ref_code']}</code>\n"
        f"{tg_emoji('calendar', '📅')} Регистрация: <b>{_format_short_date(user.get('joined_at'))}</b>\n"
        f"{tg_emoji('eye', '👁')} Последняя активность: <b>{_format_short_date(user.get('last_seen_at'))}</b>\n\n"
        f"{tg_emoji('clock', '⏰')} Остаток дней: <b>{days_left}</b>\n"
        f"{tg_emoji('calendar', '📅')} Активно до: <b>{expires}</b>\n"
        f"{tg_emoji('gift', '🎁')} Бонусный баланс: <b>{user['bonus_days_balance']}</b>\n"
        f"{tg_emoji('money', '🪙')} Скидка: <b>{user['pending_discount_percent']}%</b>\n"
        f"{tg_emoji('package', '📦')} Заказов всего: <b>{profile_stats['orders_total']}</b>\n"
        f"{tg_emoji('check', '✅')} Активированных заказов: <b>{profile_stats['paid_orders']}</b>\n"
        f"{tg_emoji('money_receive', '🏧')} Сумма оплат: <b>{_format_amount(profile_stats['spent_total'])} ₽</b>\n"
        f"{tg_emoji('people', '👥')} Приглашено: <b>{profile_stats['referrals_total']}</b>\n"
        f"{tg_emoji('people_check', '👤')} Оплативших рефералов: <b>{profile_stats['paid_referrals']}</b>\n\n"
        f"{tg_emoji('link', '🔗')} Subscription URL:\n<code>{escape(subscription_url)}</code>\n\n"
        f"Последние заказы:\n{orders_block}"
    )


def admin_orders_text() -> str:
    return (
        f"{tg_emoji('money', '🪙')} <b>Заказы</b>\n\n"
        "Доступен поиск по номеру заказа, Telegram ID и названию тарифа."
    )


def admin_orders_list_text(title: str, orders: list[dict]) -> str:
    if not orders:
        return f"{tg_emoji('money', '🪙')} <b>{escape(title)}</b>\n\nЗаказы не найдены."
    lines = []
    for order in orders:
        lines.append(
            f"• <code>#{order['id']}</code> • <code>{order['telegram_id']}</code> • "
            f"{escape(order['plan_name'])} • {escape(str(order['final_amount']))} ₽ • "
            f"{escape(order['status'])}/{escape(str(order.get('payment_status') or '-'))}"
        )
    return f"{tg_emoji('money', '🪙')} <b>{escape(title)}</b>\n\n" + "\n".join(lines)


def admin_order_text(order: dict) -> str:
    promo_code = order.get("promo_code") or "нет"
    invoice_id = order.get("payment_invoice_id") or "-"
    invoice_status = order.get("payment_status") or "-"
    provider_name = payment_provider_label(str(order.get("payment_provider") or "crypto_bot"))
    return (
        f"{tg_emoji('file', '📁')} <b>Карточка заказа</b>\n\n"
        f"Заказ: <code>#{order['id']}</code>\n"
        f"{tg_emoji('profile', '👤')} Telegram ID: <code>{order['telegram_id']}</code>\n"
        f"{tg_emoji('package', '📦')} Тариф: <b>{escape(order['plan_name'])}</b>\n"
        f"{tg_emoji('calendar', '📅')} Период: <b>{order['days']} дней</b>\n"
        f"{tg_emoji('money', '🪙')} Базовая сумма: <b>{escape(str(order['base_amount']))} ₽</b>\n"
        f"{tg_emoji('money_receive', '🏧')} Итог: <b>{escape(str(order['final_amount']))} ₽</b>\n"
        f"{tg_emoji('tag', '🏷')} Промокод: <b>{escape(str(promo_code))}</b>\n"
        f"Скидка: <b>{order['discount_percent']}%</b>\n"
        f"Провайдер: <b>{escape(provider_name)}</b>\n"
        f"{tg_emoji('upload', '⬆️')} Invoice ID: <code>{escape(str(invoice_id))}</code>\n"
        f"{tg_emoji('info', 'ℹ')} Статус инвойса: <b>{escape(str(invoice_status))}</b>\n"
        f"Статус заказа: <b>{escape(order['status'])}</b>\n"
        f"{tg_emoji('clock', '⏰')} Создан: <b>{_format_short_date(order.get('created_at'))}</b>\n"
        f"Оплачен: <b>{_format_short_date(order.get('paid_at'))}</b>\n"
        f"{tg_emoji('check', '✅')} Активирован: <b>{_format_short_date(order.get('activated_at'))}</b>"
    )


def admin_promos_text() -> str:
    return (
        f"{tg_emoji('tag', '🏷')} <b>Промокоды</b>\n\n"
        "Создание, просмотр и отключение промокодов доступны из этого раздела."
    )


def admin_promos_list_text(promos: list[dict]) -> str:
    if not promos:
        return f"{tg_emoji('tag', '🏷')} <b>Промокоды</b>\n\nПромокоды отсутствуют."
    lines = []
    for promo in promos:
        status = "активен" if int(promo.get("is_active") or 0) == 1 else "выключен"
        max_uses = "∞" if int(promo.get("max_uses") or 0) == 0 else str(promo["max_uses"])
        lines.append(
            " • ".join(
                [
                    f"<code>{promo['code']}</code>",
                    f"{promo['bonus_days']} дн.",
                    f"{promo['discount_percent']}%",
                    f"{promo['redemptions_count']}/{max_uses}",
                    status,
                ]
            )
        )
    return f"{tg_emoji('tag', '🏷')} <b>Список промокодов</b>\n\n" + "\n".join(lines)


def admin_promo_text(promo: dict) -> str:
    max_uses = "без лимита" if int(promo.get("max_uses") or 0) == 0 else str(promo["max_uses"])
    status = "активен" if int(promo.get("is_active") or 0) == 1 else "выключен"
    description = escape(promo["description"]) if promo.get("description") else "нет"
    return (
        f"{tg_emoji('tag', '🏷')} <b>Карточка промокода</b>\n\n"
        f"ID: <code>{promo['id']}</code>\n"
        f"{tg_emoji('tag', '🏷')} Код: <code>{promo['code']}</code>\n"
        f"{tg_emoji('gift', '🎁')} Бонусные дни: <b>{promo['bonus_days']}</b>\n"
        f"{tg_emoji('money', '🪙')} Скидка: <b>{promo['discount_percent']}%</b>\n"
        f"{tg_emoji('chart', '📊')} Использований: <b>{promo['redemptions_count']}</b>\n"
        f"Лимит: <b>{max_uses}</b>\n"
        f"{tg_emoji('info', 'ℹ')} Статус: <b>{status}</b>\n"
        f"Описание: <b>{description}</b>\n"
        f"{tg_emoji('clock', '⏰')} Создан: <b>{_format_short_date(promo.get('created_at'))}</b>"
    )


def admin_broadcast_text(total_users: int) -> str:
    return (
        f"{tg_emoji('megaphone', '📣')} <b>Рассылки</b>\n\n"
        f"Получателей в базе: <b>{total_users}</b>\n\n"
        "Поддерживаются текст, фото, видео, анимация и документы. "
        "Форматирование сохраняется. При необходимости можно добавить кастомные URL-кнопки."
    )


def admin_broadcast_preview_text(summary: str, total_users: int, buttons_count: int) -> str:
    return (
        f"{tg_emoji('megaphone', '📣')} <b>Предпросмотр рассылки</b>\n\n"
        f"Получателей: <b>{total_users}</b>\n"
        f"Контент: <b>{escape(summary)}</b>\n"
        f"Кнопок: <b>{buttons_count}</b>\n\n"
        "Ниже отправлен реальный предпросмотр сообщения."
    )


def admin_settings_text(config: Config) -> str:
    return (
        f"{tg_emoji('settings', '⚙️')} <b>Настройки</b>\n\n"
        f"Название VPN: <b>{escape(config.brand_name)}</b>\n"
        f"Канал подписки: <b>{escape(config.required_channel_id)}</b>\n"
        f"Ссылка на канал: <code>{escape(config.required_channel_url)}</code>\n"
        f"Реферальный бонус: <b>{config.referral_reward_days} дней</b>\n\n"
        f"Платежи:\n"
        f"{build_payment_status_line(_payment_states(config))}\n"
        f"Тарифов: <b>{len(config.plans)}</b>"
    )


def admin_payment_settings_text(config: Config) -> str:
    return (
        f"{tg_emoji('money', '🪙')} <b>Платежные методы</b>\n\n"
        f"{build_payment_status_line(_payment_states(config))}\n\n"
        "Переключатели применяются сразу. Если метод включен, но не настроен в `.env`, пользователи его не увидят."
    )


def admin_plans_text(config: Config) -> str:
    lines = []
    for plan in config.plans:
        badge = f" • {escape(plan.badge)}" if plan.badge else ""
        lines.append(
            f"• <b>{escape(plan.title)}</b> • key <code>{escape(plan.key)}</code> • "
            f"{plan.days} дн. • {plan.price_rub} ₽{badge}"
        )
    return (
        f"{tg_emoji('package', '📦')} <b>Тарифы</b>\n\n"
        + ("\n".join(lines) if lines else "Тарифы отсутствуют.")
    )


def admin_plan_text(plan: Plan) -> str:
    badge = escape(plan.badge) if plan.badge else "нет"
    return (
        f"{tg_emoji('package', '📦')} <b>Тариф</b>\n\n"
        f"Key: <code>{escape(plan.key)}</code>\n"
        f"Название: <b>{escape(plan.title)}</b>\n"
        f"Срок: <b>{plan.days} дней</b>\n"
        f"Цена: <b>{plan.price_rub} ₽</b>\n"
        f"Badge: <b>{badge}</b>"
    )


def admin_auto_broadcasts_text(campaigns: list[dict]) -> str:
    if not campaigns:
        return (
            f"{tg_emoji('calendar', '📅')} <b>Авторассылки</b>\n\n"
            "Сохраненные кампании отсутствуют."
        )

    lines = []
    for campaign in campaigns:
        status = "активна" if int(campaign.get("is_active") or 0) == 1 else "выключена"
        lines.append(
            f"• <code>#{campaign['id']}</code> • {escape(campaign['name'])} • "
            f"каждые {campaign['interval_hours']} ч. • {status}"
        )
    return f"{tg_emoji('calendar', '📅')} <b>Авторассылки</b>\n\n" + "\n".join(lines)


def admin_auto_broadcast_card_text(campaign: dict) -> str:
    status = "активна" if int(campaign.get("is_active") or 0) == 1 else "выключена"
    return (
        f"{tg_emoji('calendar', '📅')} <b>Авторассылка</b>\n\n"
        f"ID: <code>#{campaign['id']}</code>\n"
        f"Название: <b>{escape(campaign['name'])}</b>\n"
        f"Интервал: <b>{campaign['interval_hours']} ч.</b>\n"
        f"Статус: <b>{status}</b>\n"
        f"Следующий запуск: <b>{_format_short_date(campaign.get('next_run_at'))}</b>\n"
        f"Последний запуск: <b>{_format_short_date(campaign.get('last_sent_at'))}</b>\n"
        f"Последний результат: <b>{campaign.get('last_success_count', 0)}</b> успешно / "
        f"<b>{campaign.get('last_failed_count', 0)}</b> ошибок"
    )
