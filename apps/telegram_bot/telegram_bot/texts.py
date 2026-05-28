from __future__ import annotations

from html import escape
from typing import Any

USER_COMMANDS: list[tuple[str, str]] = [
    ("start", "Запустить онбординг и меню"),
    ("help", "Подсказка по командам и сценариям"),
    ("menu", "Открыть главное меню"),
    ("market", "Карта рынка по вашему профилю"),
    ("skillgap", "Аналитика навыков и график"),
    ("trends", "Тренды зарплат, спроса и карьерного графа"),
    ("profile", "Показать сохранённый профиль"),
    ("plan", "Карьерный план и действия"),
    ("plan_recommend", "Добавить рекомендации из skill gap в план"),
    ("settings", "Обновить профиль и навыки"),
    ("resume", "Загрузить резюме для автоматического извлечения навыков"),
    ("delete_me", "Удалить профиль"),
    ("subscribe", "Подписка на еженедельный дайджест"),
    ("subscription", "Показать текущую подписку"),
    ("pause_digest", "Поставить дайджест на паузу"),
    ("resume_digest", "Возобновить дайджест"),
    ("unsubscribe", "Отключить подписку"),
    ("digest", "Показать превью дайджеста"),
    ("api_key", "Ключ для доступа к Skillra Web"),
    ("search", "Поиск вакансий — /search Python Data Analyst"),
    ("pdf", "PDF-отчёт по вашему профилю"),
    ("csv", "CSV-экспорт skill-gap"),
    ("share", "Публичная ссылка на skill-gap"),
    ("analyze", "Разовый анализ роли без смены профиля"),
    ("account", "Профиль, дайджест и тариф"),
    ("digest_history", "История отправленных дайджестов"),
    ("status", "Статус API и данных"),
    ("privacy", "Кратко о приватности"),
]

ADMIN_COMMANDS: list[tuple[str, str]] = [
    ("admin_health", "Состояние /v1/health"),
    ("reload_data", "Перезагрузка данных"),
    ("broadcast_update", "Перезагрузка данных и уведомление admin"),
    ("admin_due", "Подписки, готовые к рассылке"),
]

WELCOME_MESSAGE = (
    "<b>Skillra Career Navigator</b> готов помочь вам понять рынок и сильные стороны.\n"
    "Нажмите «Начать», чтобы заполнить профиль и получить аналитику."
)

MENU_MESSAGE = (
    "Главное меню:\n"
    "Маршрут первого сеанса Skillra:\n"
    "1. Профиль и онбординг — цель, грейд, гео, формат и навыки.\n"
    "2. Рынок — карта сегмента, зарплаты, спрос и доверие данных.\n"
    "3. План — действия, приоритеты и статусы.\n"
    "4. Skill-gap — разрыв навыков и рекомендации в план.\n"
    "5. Вакансии — поиск, сохранение и статусы откликов.\n"
    "6. Дайджест — еженедельный возврат к рынку и плану.\n"
    "Дополнительно доступны Тренды, отчёты и ключ web-доступа."
)

PRIVACY_MESSAGE = (
    "Skillra хранит только ваш профиль (роль/грейд/город/формат/домен/навыки"
    " и optional username) для аналитики. Сообщения не сохраняем; удаление"
    " профиля — /delete_me, подписка — /unsubscribe. Полная политика:"
    " docs/privacy.md"
)

DIGEST_PROFILE_FALLBACK = "Профиль не найден. Пройдите онбординг командой /start, чтобы получить дайджест."

PROFILE_EXISTS_MESSAGE = "Профиль уже сохранён. Хотите обновить или оставить без изменений?"

RESUME_ONBOARDING_MESSAGE = "У вас уже начат онбординг. Продолжить с текущего шага или начать заново?"

SKILLS_PROMPT = "Перечислите ваши ключевые навыки через запятую (например: Python, SQL, Airflow)."

SETTINGS_SKILLS_PROMPT = "Перечислите новые навыки через запятую (например: Python, SQL, Airflow)."

RESUME_UPLOAD_OFFER = (
    "Хотите загрузить резюме в PDF? Я извлеку навыки и дополню профиль. "
    "Можно пропустить и сделать это позже командой /resume."
)

RESUME_UPLOAD_PROMPT = "Отправьте резюме в формате PDF до 10 МБ. " "Я автоматически извлеку навыки и дополню профиль."

RESUME_UPLOAD_STARTED = "Загружаю и анализирую резюме..."
RESUME_VALIDATION_ERROR = "Только PDF до 10 МБ."
RESUME_SKILLS_NOT_FOUND = "Резюме загружено, но навыки пока не найдены."

CANNOT_DETERMINE_USER = "Не удалось определить пользователя."
PROFILE_NOT_FOUND = "Профиль ещё не сохранён."
PROFILE_NOT_FOUND_ONBOARDING = "Профиль ещё не сохранён. Запустите онбординг командой /start."
PROFILE_DELETED_MESSAGE = "Профиль удалён. Вы можете начать онбординг заново командой /start."
SETTINGS_INTRO = "Настройки профиля. Что хотите изменить?"
PROFILE_SAVED_MESSAGE = "Профиль сохранён!"

ANALYTICS_PROFILE_FALLBACK = "Профиль не найден. Пройдите онбординг командой /start, чтобы получить аналитику."
ANALYTICS_PROFILE_INCOMPLETE = "Профиль неполный: укажите целевую роль через /start."

ACCESS_DENIED_MESSAGE = "нет доступа"

SUBSCRIPTION_NOT_FOUND_MESSAGE = "Активная подписка не найдена."
SUBSCRIPTION_DISABLED_MESSAGE = "Подписка отключена. Чтобы вернуть дайджест, используйте /subscribe."


def welcome_message() -> str:
    return WELCOME_MESSAGE


def help_message(is_admin: bool = False) -> str:
    commands_lines = ["<b>Команды</b>:"]
    commands_lines.extend(_format_command_lines(USER_COMMANDS))

    if is_admin:
        commands_lines.append("\n<b>Admin</b>:")
        commands_lines.extend(_format_command_lines(ADMIN_COMMANDS))

    navigator_lines = [
        "<b>Навигатор сценариев</b>:",
        "1) /start — заполнить профиль и получить меню.",
        "2) /market — увидеть карту рынка по профилю.",
        "3) /skillgap — получить рекомендации по навыкам и график.",
        "4) /trends — посмотреть динамику рынка и карьерный граф.",
        "5) /plan и /plan_recommend — открыть план и добавить рекомендации.",
        "6) /pdf, /csv и /share — выгрузить или поделиться skill-gap.",
        "7) /subscribe — оформить еженедельный дайджест.",
        "8) /digest и /digest_history — посмотреть превью и историю дайджеста.",
    ]

    return "\n".join(commands_lines + [""] + navigator_lines)


def menu_message() -> str:
    return MENU_MESSAGE


def privacy_message() -> str:
    return PRIVACY_MESSAGE


def digest_profile_fallback() -> str:
    return DIGEST_PROFILE_FALLBACK


def profile_exists_message() -> str:
    return PROFILE_EXISTS_MESSAGE


def resume_onboarding_message() -> str:
    return RESUME_ONBOARDING_MESSAGE


def skills_prompt() -> str:
    return SKILLS_PROMPT


def settings_skills_prompt() -> str:
    return SETTINGS_SKILLS_PROMPT


def resume_upload_offer() -> str:
    return RESUME_UPLOAD_OFFER


def resume_upload_prompt() -> str:
    return RESUME_UPLOAD_PROMPT


def resume_upload_started() -> str:
    return RESUME_UPLOAD_STARTED


def resume_validation_error() -> str:
    return RESUME_VALIDATION_ERROR


def resume_skills_not_found() -> str:
    return RESUME_SKILLS_NOT_FOUND


def cannot_determine_user() -> str:
    return CANNOT_DETERMINE_USER


def profile_not_found() -> str:
    return PROFILE_NOT_FOUND


def profile_not_found_onboarding() -> str:
    return PROFILE_NOT_FOUND_ONBOARDING


def profile_deleted_message() -> str:
    return PROFILE_DELETED_MESSAGE


def settings_intro_message() -> str:
    return SETTINGS_INTRO


def profile_saved_message() -> str:
    return PROFILE_SAVED_MESSAGE


def analytics_profile_fallback() -> str:
    return ANALYTICS_PROFILE_FALLBACK


def analytics_profile_incomplete() -> str:
    return ANALYTICS_PROFILE_INCOMPLETE


def access_denied_message() -> str:
    return ACCESS_DENIED_MESSAGE


def subscription_not_found_message() -> str:
    return SUBSCRIPTION_NOT_FOUND_MESSAGE


def subscription_disabled_message() -> str:
    return SUBSCRIPTION_DISABLED_MESSAGE


def subscription_timezone_prompt(default_timezone: str) -> str:
    return (
        "Выберите таймзону для еженедельного дайджеста. "
        "Можно ввести вручную (например, Europe/Moscow). "
        f"По умолчанию: {escape(default_timezone)}"
    )


def subscription_weekday_prompt() -> str:
    return "Выберите день недели для еженедельного дайджеста."


def subscription_time_prompt(default_time: str, timezone: str) -> str:
    return (
        "Во сколько присылать дайджест? "
        "Можно выбрать кнопку или ввести время вручную в формате HH:MM. "
        f"Текущая таймзона: {escape(timezone or '—')}"
    )


def onboarding_step_prompt(step: str) -> str:
    mapping = {
        "role": "Выберите целевую роль:",
        "grade": "Какой грейд рассматриваете?",
        "city_tier": "Выберите уровень города:",
        "work_mode": "Какой формат работы предпочтителен?",
        "domain": "Выберите домен (можно пропустить):",
    }
    return mapping.get(step, "Выберите значение из списка:")


def format_status_message(
    service_health: dict[str, Any] | None,
    data_health: dict[str, Any] | None,
    data_health_error: str | None = None,
    due_subscriptions_count: int | None = None,
) -> str:
    lines = ["<b>Статус платформы</b>"]

    version = (service_health or {}).get("version") or "неизвестна"
    api_status = (service_health or {}).get("status") or "неизвестен"
    lines.append(f"API: <b>{escape(str(api_status))}</b> (версия: <b>{escape(str(version))}</b>)")

    db_status = _extract_db_status(service_health)
    if db_status:
        lines.append(f"База данных: <b>{escape(str(db_status))}</b>")
    else:
        lines.append("База данных: состояние неизвестно")

    datastore_status = _extract_datastore_status(data_health)
    if datastore_status is None:
        lines.append("Данные: состояние неизвестно")
    else:
        ready = datastore_status.get("ready")
        if ready is True:
            lines.append("Данные: ✅ готовы")
        elif ready is False:
            lines.append("Данные: ❌ недоступны")
        else:
            lines.append("Данные: состояние неизвестно")

        generated_at = _extract_generated_at(datastore_status)
        if generated_at:
            lines.append(f"Сгенерировано: <b>{escape(generated_at)}</b>")

    if due_subscriptions_count is not None:
        lines.append(f"Due подписки: <b>{due_subscriptions_count}</b>")

    if data_health_error:
        lines.append(f"Примечание: {escape(data_health_error)}")

    return "\n".join(lines)


def _format_command_lines(commands: list[tuple[str, str]]) -> list[str]:
    return [f"/{name} — {description}" for name, description in commands]


def _extract_datastore_status(data_health: dict[str, Any] | None) -> dict[str, Any] | None:
    if not data_health:
        return None

    datastore = data_health.get("datastore")
    if isinstance(datastore, dict):
        return datastore

    details = data_health.get("details")
    if isinstance(details, dict):
        datastore = details.get("datastore")
        if isinstance(datastore, dict):
            return datastore

    return None


def _extract_generated_at(datastore_status: dict[str, Any]) -> str | None:
    dataset_meta = datastore_status.get("dataset_meta")
    if isinstance(dataset_meta, dict):
        timestamp = dataset_meta.get("generated_at_utc") or dataset_meta.get("generated_at")
        if timestamp:
            return str(timestamp)
    return None


def _extract_db_status(service_health: dict[str, Any] | None) -> str | None:
    if not service_health:
        return None

    db_payload = service_health.get("db") or service_health.get("database")
    if isinstance(db_payload, dict):
        status = db_payload.get("status") or db_payload.get("state")
        if status:
            return str(status)
    elif isinstance(db_payload, str):
        return db_payload

    details = service_health.get("details")
    if isinstance(details, dict):
        for key in ("db", "database", "postgres"):
            value = details.get(key)
            if isinstance(value, dict):
                status = value.get("status") or value.get("state")
                if status:
                    return str(status)
            elif isinstance(value, str):
                return value

    return None
