# Remnawave Telegram Bot

Telegram-бот для продажи VPN-подписок: от первого `/start` до автоматической выдачи subscription URL после оплаты.

Пользователь проходит обязательную подписку на канал, выбирает тариф, оплачивает удобным способом, а бот проверяет статус счета и активирует подписку в Remnawave.

## Что под капотом

- Python + Aiogram 3
- PostgreSQL для хранения пользователей, заказов, промокодов, настроек и рассылок
- Интеграция с Remnawave для выдачи и продления подписок
- Оплата через Crypto Bot, YooMoney и FreeKassa
- Проверка статуса платежа по кнопке, без вебхуков
- FSM-логика, админские сценарии и многоуровневая обработка ошибок

## Функционал

- Продажа тарифов: выбор плана, расчет стоимости, применение скидок и бонусных дней.
- Профиль пользователя: остаток дней, дата окончания, реферальный код, статистика по приглашениям, subscription URL.
- Бонусная система: промокоды с бонусными днями и скидкой на следующую оплату.
- Реферальная программа: ссылка для приглашений, начисление бонуса за первого оплаченного реферала.
- Поддержка и инструкции: отдельный раздел с подсказками для iOS, Android, Windows и macOS.
- Админка: сводка по пользователям, заказам, активным подпискам, выручке и промокодам.
- Поиск и управление: поиск пользователя по Telegram ID, username, внутреннему ID или реферальному коду.
- Работа с заказами: карточка заказа, ручная перепроверка платежа, просмотр статусов и истории.
- Управление промокодами: создание, отключение, просмотр статистики использований.
- Рассылки: отправка по базе с сохранением форматирования, медиа и URL-кнопок.
- Авторассылки: кампании с интервалами, автозапуском и статистикой успешных отправок.
- Настройки на лету: переключение платежек, изменение названия бренда, канала и параметров реферальной системы.

Бот синхронизирует локальные данные с Remnawave, обрабатывает продление подписки, повторные оплаты и неактивные счета. Это готовая основа под запуск и масштабирование VPN-сервиса.

## Структура

- `main.py` - точка входа
- `dozhrvpn_bot/` - основной код бота
- `.env.example` - пример конфигурации
- `Dockerfile` - образ приложения
- `docker-compose.yml` - быстрый запуск бота и PostgreSQL
- `requirements.txt` - зависимости

## Быстрый старт

### Docker Compose

```bash
copy .env.example .env
docker compose up -d --build
docker compose logs -f bot
```

Перед запуском заполните в `.env` как минимум `BOT_TOKEN`, `ADMIN_IDS`, `REQUIRED_CHANNEL_ID`, `REQUIRED_CHANNEL_URL`, `REMNAWAVE_BASE_URL` и данные для авторизации в Remnawave.

`docker-compose.yml` поднимает PostgreSQL и сам передает боту `DATABASE_URL`. Если нужен внешний PostgreSQL, укажите свой `DATABASE_URL` в `.env`.

### Локально

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
python main.py
```

## Обязательные переменные

- `BOT_TOKEN`
- `ADMIN_IDS`
- `DATABASE_URL`
- `REQUIRED_CHANNEL_ID`
- `REQUIRED_CHANNEL_URL`
- `REMNAWAVE_BASE_URL`
- `REMNAWAVE_API_TOKEN` или `REMNAWAVE_LOGIN` + `REMNAWAVE_PASSWORD`

Минимум один платежный метод:

- `CRYPTO_PAY_TOKEN`
- или `YOOMONEY_WALLET` + `YOOMONEY_TOKEN`
- или `FREEKASSA_SHOP_ID` + `FREEKASSA_API_KEY` + `FREEKASSA_PAYMENT_SYSTEM_ID` + `FREEKASSA_PAYER_EMAIL`

Пример DSN:

```env
DATABASE_URL=postgresql://<user>:<password>@127.0.0.1:5432/remnawave_tg_bot
```

Бот сам создает таблицы при старте.

## Контакты

Портфолио: [https://t.me/dozhr_portfolio](https://t.me/dozhr_portfolio)

Заказать разработку - [https://t.me/dozhr](https://t.me/dozhr)
