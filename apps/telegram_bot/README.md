# Skillra Telegram Bot

aiogram-бот, который выступает Telegram-фронтом к Skillra API. Внутри есть
конфиг из окружения, HTTP-клиент к API, FSM-онбординг, пользовательские и
админские команды, логирование без PII, rate limit и обработчик ошибок.
Подписка (`/subscribe`, `/unsubscribe`) хранится в Skillra API, а рассылку
выполняет отдельный `digest-worker` сервис.

## Структура
- `telegram_bot/main.py` — точка входа бота с polling-режимом.
- `telegram_bot/config.py` — парсинг переменных окружения с валидацией.
- `telegram_bot/services/api_client.py` — httpx-клиент к Skillra API с retry.
- `telegram_bot/handlers/commands.py` — команды `/start`, `/help`, `/menu`, `/privacy`.
- `telegram_bot/handlers/subscriptions.py` — подписка на дайджест и отмена.
- `telegram_bot/middlewares/` — логирование, rate limit, обработка ошибок.
- `apps/digest_worker/digest_worker/worker.py` — отдельный worker рассылки дайджестов.
- `requirements.txt` — зависимости уровня бота.

## Быстрый старт
1. Установить зависимости: `pip install -r apps/telegram_bot/requirements.txt`.
2. Подготовить `.env` на основе `.env.example` и заполнить токены. Для локальной
   разработки используйте отдельного BotFather test bot, не production
   `@skillra_bot`.
3. Выбрать режим запуска:
   - **Polling (по умолчанию)** — оставить `BOT_MODE` пустым/`polling` и запустить `make bot` или `python -m apps.telegram_bot.telegram_bot.main`.
   - **Webhook** — выставить `BOT_MODE=webhook`, указать `TELEGRAM_WEBHOOK_URL` и `TELEGRAM_WEBHOOK_SECRET_TOKEN`, затем запустить `python -m apps.telegram_bot.telegram_bot.main` (бот поднимет веб-сервер и зарегистрирует вебхук).
     Сервер в webhook-режиме также отдаёт `GET /health` без авторизации, что удобно для readiness-проб и балансировщиков.
4. Для production-рассылки запустить `digest-worker` из compose profile `worker`.

### Docker Compose (локальная разработка)
1. Создать `.env` из `.env.example` (файл не коммитится) и указать `TELEGRAM_BOT_TOKEN`, `SKILLRA_API_TOKEN` и другие параметры.
2. Убедиться, что API сможет читать `data/processed/latest/` (при необходимости выполнить `make pipeline`).
3. Запустить инфраструктуру вместе с API и БД: `make compose-up`.
4. Смотреть логи бота: `docker compose --env-file .env -f infra/docker-compose.dev.yml logs -f skillra-bot` или `make compose-logs` (стрим всех сервисов).
5. Остановить compose: `make compose-down`.

## Команды
Пользовательские:
- `/start` — онбординг с сохранением профиля в Skillra API и кнопки «Начать/Меню».
- `/help` — список команд и навигатор сценариев.
- `/menu` — открыть главное меню (кнопки «Карта рынка»/«Skill-gap»/«Подписка»/`/profile`).
- `/market` — карта рынка по сохранённому профилю (вакансии, зарплаты, топ навыков).
- `/skillgap` — рекомендации по навыкам и график skill-gap.
- `/trends` — тренды зарплат, вакансий, спроса на навыки и карьерный граф.
- `/profile` — показать сохранённый профиль.
- `/settings` — запустить флоу изменения профиля/навыков.
- `/delete_me` — удалить профиль из API.
- `/subscribe` и `/unsubscribe` — управление еженедельным дайджестом.
- `/digest` — превью дайджеста и график по сохранённому профилю.
- `/api_key` — ключ для входа в Skillra Web.
- `/search <query>` — поиск вакансий по профилю, сохранение вакансии в карьерный план
  и обновление статуса отклика.
- `/plan` — карьерный план и ближайшие действия.
- `/plan_recommend` — добавить в план рекомендации из skill gap.
- `/resume` — загрузка PDF-резюме и дополнение навыков в профиле.
- `/pdf` — PDF-отчёт по сохранённому профилю.
- `/csv` — CSV-экспорт skill-gap по сохранённому профилю.
- `/share` — публичная ссылка на read-only skill-gap анализ.
- `/analyze` — разовый анализ роли/грейда без изменения профиля.
- `/account` — профиль и подписка одним сообщением.
- `/digest_history` — последние отправленные дайджесты пользователя.
- `/status` — состояние API, данных и очереди рассылки.
- `/privacy` — кратко о политике приватности.

Админские (по `TELEGRAM_ADMIN_IDS`):
- `/admin_health` — состояние `/v1/health` и готовность датасета.
- `/reload_data` (`/admin_reload_data`) — инициировать перезагрузку данных в API.
- `/admin_due` — количество подписок, готовых к рассылке.

## Сценарии
- **Онбординг (/start).** FSM спрашивает роль/грейд/город/формат/домен и навыки, сохраняет
  профиль через Skillra API и предлагает меню.
- **Аналитика рынка.** `/market` использует сохранённый профиль, строит фильтры и выводит
  карточку сегмента (вакансии, медианные зарплаты, топ навыков, предупреждения).
- **Skill-gap.** `/skillgap` собирает персону из профиля, запрашивает аналитику в API,
  отправляет текстовый отчёт и PNG-график разрыва.
- **Тренды.** `/trends` использует сохранённые роль/грейд, показывает динамику зарплат,
  вакансий, спроса на топ-навыки и карьерные переходы.
- **Карьерный план.** `/plan` открывает или создаёт план, `/plan_recommend` добавляет
  evidence-backed действия из skill-gap, `/search` сохраняет вакансии в план и ведёт
  статусы отклика.
- **Подписка и дайджест.** `/subscribe` включает еженедельную рассылку (таймзона/день/время
  с дефолтами из окружения), `/unsubscribe` её отключает. `/digest` даёт превью и график,
  `/digest_history` показывает последние отправки, `digest-worker` периодически
  claim-ит готовые подписки и рассылает их.
- **Профиль и настройки.** `/profile` показывает текущие данные, `/settings` позволяет
  переоткрыть флоу редактирования навыков, `/delete_me` удаляет профиль из API.
- **Операционка.** `/status` проверяет `/health`, `/data_health` и количество due подписок;
  админ-команды используют сервисный и админ токены API.

## Переменные окружения
Ключевые (обязательные):
- `TELEGRAM_BOT_TOKEN` — токен бота.
- `TELEGRAM_BOT_USERNAME` — username текущего бота без `@`.
- `SKILLRA_RUNTIME_ENV` — `local` или `prod`; официальный `skillra_bot`
  разрешён только при `prod`.
- `SKILLRA_API_BASE_URL` — базовый URL Skillra API (для prod compose: `http://prod-skillra-api:8000`, для isolated dev compose: `http://skillra-api:8000`).
- `SKILLRA_API_TOKEN` — сервисный токен для пользовательских запросов.
- `SKILLRA_ADMIN_TOKEN` — админ-токен для health/reload/due.
- `REDIS_URL` — хранилище FSM и состояния расписаний (например, `redis://localhost:6379/0`).

Режим работы и формат:
- `BOT_MODE` — `polling` (по умолчанию) или `webhook`.
- `TELEGRAM_PARSE_MODE` — `HTML` по умолчанию.
- `TELEGRAM_RATE_LIMIT_PER_SECOND` — rate limit middleware, положительное число.
- `LOG_LEVEL` — уровень логирования (по умолчанию `INFO`).

Дайджест и worker:
- `DIGEST_POLL_INTERVAL` — как часто worker проверяет due подписки (секунды).
- `TELEGRAM_DIGEST_WEEKDAY` / `TELEGRAM_DIGEST_TIME_LOCAL` / `TELEGRAM_DIGEST_TIMEZONE` —
  дефолты для расписания подписки (день недели 0–6, `HH:MM`, таймзона tzdb).
- `TELEGRAM_ADMIN_IDS` — запятая через запятую список Telegram ID админов.

API-клиент:
- `SKILLRA_API_CONNECT_TIMEOUT` / `SKILLRA_API_READ_TIMEOUT` — таймауты httpx.
- `SKILLRA_API_MAX_RETRIES` / `SKILLRA_API_RETRY_BACKOFF_SECONDS` — retry логика клиента.

Webhook-режим дополнительно требует:
- `TELEGRAM_WEBHOOK_URL` — абсолютный публичный URL вебхука.
- `TELEGRAM_WEBHOOK_SECRET_TOKEN` — проверяется по заголовку `X-Telegram-Bot-Api-Secret-Token`.
- `TELEGRAM_WEBHOOK_HOST` / `TELEGRAM_WEBHOOK_PORT` / `TELEGRAM_WEBHOOK_PATH` — параметры
  локального HTTP-сервера (path заполняется из URL, если не задан).

Полный список значений с примерами — в корневом `.env.example` (секция Telegram Bot). Все
токены и секреты должны оставаться вне репозитория.

Production contract: `@skillra_bot` обслуживается только production runtime.
Внутри prod compose бот ходит к API по `http://prod-skillra-api:8000`; публичный
master stand для пользователей и web app — `https://skillra.ru`, webhook endpoint
при webhook-режиме — `https://tg.skillra.ru/webhook`.
