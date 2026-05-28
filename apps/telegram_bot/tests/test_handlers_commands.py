import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from telegram_bot.handlers import commands
from telegram_bot.services.errors import SkillraApiError


def test_welcome_message_contains_branding() -> None:
    text = commands.format_welcome_message()
    assert "Skillra" in text
    assert "Начать" in text


def test_help_lists_commands() -> None:
    text = commands.format_help_message()
    assert "/start" in text
    assert "/help" in text
    assert "/menu" in text
    assert "/market" in text
    assert "/skillgap" in text
    assert "/trends" in text
    assert "/profile" in text
    assert "/plan" in text
    assert "/plan_recommend" in text
    assert "/delete_me" in text
    assert "/resume" in text
    assert "/subscribe" in text
    assert "/subscription" in text
    assert "/pause_digest" in text
    assert "/resume_digest" in text
    assert "/unsubscribe" in text
    assert "/digest" in text
    assert "/api_key" in text
    assert "/search" in text
    assert "/pdf" in text
    assert "/csv" in text
    assert "/share" in text
    assert "/analyze" in text
    assert "/account" in text
    assert "/digest_history" in text
    assert "/status" in text
    assert "/privacy" in text
    assert "Навигатор" in text
    assert "/admin_health" not in text


def test_help_lists_admin_commands_for_admins() -> None:
    text = commands.format_help_message(is_admin=True)

    assert "/admin_health" in text
    assert "/reload_data" in text
    assert "/broadcast_update" in text
    assert "/admin_due" in text


def test_menu_message_describes_sections() -> None:
    text = commands.format_menu_message()
    assert "Главное меню" in text
    assert "онбординг".lower() in text.lower()
    assert "Skill-gap" in text
    assert "Тренды" in text


def test_next_best_action_message_covers_core_states() -> None:
    states = [
        ("create_profile", "Создать профиль", "/profile"),
        ("create_plan", "Собрать план", "/plan"),
        ("find_vacancy", "Найти вакансию", "/search"),
    ]

    for state, title, command in states:
        text = commands.format_next_best_action_message(
            {
                "state": state,
                "title": title,
                "reason": "Следующий шаг выбран по состоянию профиля.",
                "cta": "Продолжить",
                "command": command,
                "route": "/profile",
                "profile_quality": {"score": 80, "missing_fields": ["target_domain"]},
            }
        )

        assert title in text
        assert command in text
        assert "80%" in text
        assert "target_domain" in text
        assert "Первый сеанс" in text
        assert "сейчас" in text


def test_next_best_action_message_escapes_html() -> None:
    text = commands.format_next_best_action_message(
        {
            "title": "<script>",
            "reason": "x < y",
            "cta": "Открыть",
            "command": "/profile",
            "route": "/profile",
            "profile_quality": {"score": 100, "missing_fields": []},
        }
    )

    assert "&lt;script&gt;" in text
    assert "x &lt; y" in text


def test_handle_menu_shows_personal_next_action() -> None:
    message = SimpleNamespace(from_user=SimpleNamespace(id=42), answer=AsyncMock())
    api_client = SimpleNamespace(
        get_next_best_action=AsyncMock(
            return_value={
                "state": "find_vacancy",
                "title": "Найти подходящую вакансию",
                "reason": "План уже есть.",
                "cta": "Искать вакансии",
                "command": "/search",
                "route": "/search",
                "profile_quality": {"score": 100, "missing_fields": []},
            }
        )
    )

    asyncio.run(commands.handle_menu(message, api_client))

    api_client.get_next_best_action.assert_awaited_once_with(42, source="bot")
    text = message.answer.await_args.args[0]
    assert "Главное меню" in text
    assert "Найти подходящую вакансию" in text
    assert message.answer.await_args.kwargs["parse_mode"] == commands.ParseMode.HTML


def test_handle_menu_falls_back_when_next_action_unavailable() -> None:
    message = SimpleNamespace(from_user=SimpleNamespace(id=42), answer=AsyncMock())
    api_client = SimpleNamespace(
        get_next_best_action=AsyncMock(
            side_effect=SkillraApiError(
                error_code=None,
                error_message=None,
                status_code=503,
                request_id="req",
                payload={},
            )
        )
    )

    asyncio.run(commands.handle_menu(message, api_client))

    text = message.answer.await_args.args[0]
    assert "Главное меню" in text
    assert "Личный следующий шаг" not in text


def test_privacy_message_is_present() -> None:
    text = commands.format_privacy_message()
    assert "хранит только ваш профиль" in text
    assert "/delete_me" in text
    assert "/unsubscribe" in text


def test_format_commercial_state_message_lists_locked_features() -> None:
    lines = commands.format_commercial_state_message(
        {
            "plan": "free",
            "subscription_state": "none",
            "locked_features": ["career_plan.generate_actions", "skill_gap.export"],
        }
    )
    text = "\n".join(lines)

    assert "Тариф" in text
    assert "Free" in text
    assert "рекомендации из skill gap" in text
    assert "https://skillra.ru/account" in text
    assert "/api_key" in text


def test_format_commercial_state_message_adds_payment_recovery_guidance() -> None:
    lines = commands.format_commercial_state_message(
        {
            "plan": "pro",
            "subscription_state": "payment_failed",
            "locked_features": ["career_plan.generate_actions"],
        }
    )
    text = "\n".join(lines)

    assert "платёж не прошёл" in text
    assert "поддержку" in text
    assert "Данные провайдера" in text


def test_show_account_includes_commercial_state() -> None:
    message = SimpleNamespace(from_user=SimpleNamespace(id=42), answer=AsyncMock())
    api_client = SimpleNamespace(
        get_next_best_action=AsyncMock(return_value=None),
        get_commercial_state=AsyncMock(
            return_value={
                "plan": "pro",
                "subscription_state": "active",
                "locked_features": [],
                "entitlements": ["*"],
            }
        ),
        get_profile=AsyncMock(return_value={"target_role": "analyst", "target_grade": "junior", "current_skills": []}),
        get_weekly_subscription=AsyncMock(
            return_value={
                "active": True,
                "weekday": 0,
                "time_local": "10:00",
                "timezone": "UTC",
                "last_sent_at": None,
            }
        ),
    )

    asyncio.run(commands.show_account(message, api_client))

    api_client.get_commercial_state.assert_awaited_once_with(42)
    text = message.answer.await_args.args[0]
    assert "Тариф" in text
    assert "Pro" in text
    assert "Pro-возможности доступны" in text
    assert message.answer.await_args.kwargs["parse_mode"] == commands.ParseMode.HTML


def test_menu_keyboard_contains_buttons() -> None:
    markup = commands.build_menu_keyboard()
    buttons = [button.text for row in markup.keyboard for button in row]

    assert "Карта рынка" in buttons
    assert "Skill-gap" in buttons
    assert "Подписка" in buttons
    assert "/plan" in buttons
    assert "/trends" in buttons
    assert "/search" in buttons
    assert "/digest" in buttons
    assert "/account" in buttons
    assert "/api_key" in buttons


def test_router_import() -> None:
    assert commands.router is not None


def test_format_status_message_ready() -> None:
    service = {"version": "1.2.3"}
    data_health = {
        "datastore": {
            "ready": True,
            "dataset_meta": {"generated_at_utc": "2024-05-01T12:00:00Z"},
        }
    }

    message = commands.format_status_message(service, data_health, due_subscriptions_count=5)

    assert "1.2.3" in message
    assert "готовы" in message
    assert "2024-05-01T12:00:00Z" in message
    assert "5" in message


def test_format_status_message_handles_error_payload() -> None:
    service = {}
    data_health = {
        "details": {
            "datastore": {
                "ready": False,
                "dataset_meta": {"generated_at": "2024-04-30T10:00:00Z"},
            }
        }
    }

    message = commands.format_status_message(
        service,
        data_health,
        data_health_error="/v1/health вернул 503",
        due_subscriptions_count=0,
    )

    assert "неизвестна" in message
    assert "недоступны" in message
    assert "2024-04-30T10:00:00Z" in message
    assert "503" in message
