from __future__ import annotations

import pytest

from scripts.smoke_telegram_bot import (
    TelegramSmokeFailure,
    normalize_username,
    validate_contour,
    validate_get_me,
    validate_webhook_info,
)


def test_normalize_username_strips_at_and_case() -> None:
    assert normalize_username("@Skillra_Staging_Bot") == "skillra_staging_bot"
    assert normalize_username(" skillra_bot ") == "skillra_bot"
    assert normalize_username(" ") is None


def test_validate_get_me_accepts_expected_staging_bot() -> None:
    result = validate_get_me(
        {"ok": True, "result": {"id": 10, "is_bot": True, "username": "Skillra_Staging_Bot"}},
        expected_username="skillra_staging_bot",
        forbidden_username="skillra_bot",
    )

    assert result["username"] == "Skillra_Staging_Bot"


def test_validate_get_me_rejects_prod_bot_in_staging() -> None:
    with pytest.raises(TelegramSmokeFailure, match="forbidden"):
        validate_get_me(
            {"ok": True, "result": {"id": 10, "is_bot": True, "username": "skillra_bot"}},
            expected_username=None,
            forbidden_username="skillra_bot",
        )


def test_validate_get_me_rejects_username_mismatch() -> None:
    with pytest.raises(TelegramSmokeFailure, match="username mismatch"):
        validate_get_me(
            {"ok": True, "result": {"id": 10, "is_bot": True, "username": "wrong_bot"}},
            expected_username="skillra_staging_bot",
            forbidden_username="skillra_bot",
        )


def test_validate_webhook_info_accepts_expected_url() -> None:
    result = validate_webhook_info(
        {"ok": True, "result": {"url": "https://tg.staging.skillra.ru/webhook"}},
        expected_url="https://tg.staging.skillra.ru/webhook",
    )

    assert result["url"] == "https://tg.staging.skillra.ru/webhook"


def test_validate_webhook_info_rejects_prod_url() -> None:
    with pytest.raises(TelegramSmokeFailure, match="webhook URL mismatch"):
        validate_webhook_info(
            {"ok": True, "result": {"url": "https://tg.skillra.ru/webhook"}},
            expected_url="https://tg.staging.skillra.ru/webhook",
        )


def test_validate_contour_accepts_polling_staging_without_webhook_url() -> None:
    validate_contour(
        expected_contour="staging",
        bot_username="skillra_staging_bot",
        webhook_url="",
        public_health_url="https://tg.staging.skillra.ru/health",
    )


def test_validate_contour_rejects_prod_bot_for_staging_even_without_forbid_override() -> None:
    with pytest.raises(TelegramSmokeFailure, match="forbidden"):
        validate_contour(
            expected_contour="staging",
            bot_username="skillra_bot",
            webhook_url="",
            public_health_url=None,
        )


def test_validate_contour_rejects_prod_webhook_host_for_staging() -> None:
    with pytest.raises(TelegramSmokeFailure, match="staging webhook host"):
        validate_contour(
            expected_contour="staging",
            bot_username="skillra_staging_bot",
            webhook_url="https://tg.skillra.ru/webhook",
            public_health_url=None,
        )
