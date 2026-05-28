from __future__ import annotations

from typing import Any


class SkillraApiError(Exception):
    def __init__(
        self,
        *,
        error_code: str | None,
        error_message: str | None,
        status_code: int | None,
        request_id: str | None,
        payload: Any,
    ) -> None:
        super().__init__(error_message or error_code or "Skillra API error")
        self.error_code = error_code
        self.error_message = error_message
        self.status_code = status_code
        self.request_id = request_id
        self.payload = payload


def user_message_from_error(error: SkillraApiError, default_message: str) -> str:
    fallback_messages = {
        "SERVICE_TOKEN_NOT_CONFIGURED": "Сервис временно недоступен (конфигурация). Обратитесь к администратору.",
        "ADMIN_TOKEN_NOT_CONFIGURED": "Сервис временно недоступен (конфигурация). Обратитесь к администратору.",
        "INVALID_SERVICE_TOKEN": "Сервис недоступен: требуется актуальный токен.",
        "DATA_UNAVAILABLE": "Данные ещё не загружены. Попробуйте позже.",
        "VALIDATION_ERROR": "Неверные параметры. Проверьте введённые данные.",
        "PROFILE_NOT_FOUND": "Профиль не найден. Пройдите /start.",
        "ENTITLEMENT_REQUIRED": (
            "Эта возможность доступна в Trial или Pro. Откройте Аккаунт: https://skillra.ru/account. "
            "Для входа в web используйте /api_key."
        ),
    }

    if error.error_message:
        return error.error_message

    if error.error_code and error.error_code in fallback_messages:
        return fallback_messages[error.error_code]

    return default_message
