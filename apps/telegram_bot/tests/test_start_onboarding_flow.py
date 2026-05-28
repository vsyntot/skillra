import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from telegram_bot.handlers import onboarding


def test_start_onboarding_prompts_resume_when_state_active():
    message = SimpleNamespace(
        from_user=SimpleNamespace(id=1),
        answer=AsyncMock(),
    )
    state = SimpleNamespace(get_state=AsyncMock(return_value=onboarding.ProfileOnboarding.role.state))
    api_client = SimpleNamespace(get_profile=AsyncMock())
    meta_cache = SimpleNamespace()

    asyncio.run(onboarding.start_onboarding(message, state, api_client, meta_cache))

    assert message.answer.await_args_list
    args, kwargs = message.answer.await_args_list[0]
    assert args[0] == onboarding.RESUME_ONBOARDING_MESSAGE
    markup = kwargs["reply_markup"]
    callbacks = [button.callback_data for row in markup.inline_keyboard for button in row]
    assert onboarding.START_RESUME_CALLBACK in callbacks
    assert onboarding.START_RESTART_CALLBACK in callbacks


def test_start_onboarding_prompts_for_existing_profile():
    message = SimpleNamespace(
        from_user=SimpleNamespace(id=1),
        answer=AsyncMock(),
    )
    state = SimpleNamespace(get_state=AsyncMock(return_value=None))
    api_client = SimpleNamespace(get_profile=AsyncMock(return_value={"target_role": "analyst"}))
    meta_cache = SimpleNamespace()

    asyncio.run(onboarding.start_onboarding(message, state, api_client, meta_cache))

    args, kwargs = message.answer.await_args_list[0]
    assert args[0] == onboarding.PROFILE_EXISTS_MESSAGE
    markup = kwargs["reply_markup"]
    callbacks = [button.callback_data for row in markup.inline_keyboard for button in row]
    assert onboarding.START_UPDATE_PROFILE_CALLBACK in callbacks
    assert onboarding.START_KEEP_PROFILE_CALLBACK in callbacks


def test_start_onboarding_shows_next_action_for_existing_profile():
    message = SimpleNamespace(
        from_user=SimpleNamespace(id=1),
        answer=AsyncMock(),
    )
    state = SimpleNamespace(get_state=AsyncMock(return_value=None))
    api_client = SimpleNamespace(
        get_profile=AsyncMock(return_value={"target_role": "analyst"}),
        get_next_best_action=AsyncMock(
            return_value={
                "state": "create_plan",
                "title": "Собрать карьерный план",
                "reason": "Профиль готов.",
                "cta": "Собрать план",
                "command": "/plan",
                "route": "/career-plan",
                "profile_quality": {"score": 100, "missing_fields": []},
            }
        ),
    )
    meta_cache = SimpleNamespace()

    asyncio.run(onboarding.start_onboarding(message, state, api_client, meta_cache))

    args, kwargs = message.answer.await_args_list[0]
    assert onboarding.PROFILE_EXISTS_MESSAGE in args[0]
    assert "Собрать карьерный план" in args[0]
    assert kwargs["parse_mode"] == "HTML"
    api_client.get_next_best_action.assert_awaited_once_with(1, source="bot")


def test_resume_onboarding_returns_to_current_step(monkeypatch):
    message = SimpleNamespace(answer=AsyncMock())
    state = SimpleNamespace(
        get_state=AsyncMock(return_value=onboarding.ProfileOnboarding.grade.state),
        set_state=AsyncMock(),
        update_data=AsyncMock(),
        clear=AsyncMock(),
    )
    api_client = SimpleNamespace()
    meta_cache = SimpleNamespace()
    ask_grade = AsyncMock()
    monkeypatch.setattr(onboarding, "_ask_grade", ask_grade)

    asyncio.run(onboarding._resume_onboarding(message, state, api_client, meta_cache))

    ask_grade.assert_awaited_once_with(message, state, api_client, meta_cache)
    assert message.answer.await_args_list
