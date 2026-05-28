from __future__ import annotations

import asyncio
import inspect
from types import SimpleNamespace
from typing import Any, Awaitable, Callable
from unittest.mock import AsyncMock

from telegram_bot.handlers import onboarding
from telegram_bot.keyboards import onboarding as kb_onboarding
from telegram_bot.services.api_client import SkillraApiClient


def test_parse_skills_strips_and_deduplicates() -> None:
    skills = onboarding.parse_skills("Python, sql,  python ,Airflow,,")
    assert skills == ["python", "sql", "airflow"]


def test_find_unknown_skills_returns_suggestions() -> None:
    unknown, suggestions = onboarding.find_unknown_skills(["python", "sqll", "excel"], ["python", "sql", "airflow"])

    assert unknown == ["sqll", "excel"]
    assert suggestions.get("sqll")
    assert suggestions.get("excel") == []


def test_build_profile_payload_collects_state() -> None:
    user = SimpleNamespace(username="alice")
    payload = onboarding.build_profile_payload(
        user,
        {
            "target_role": "analyst",
            "target_grade": "Middle",
            "target_city_tier": "Moscow",
            "target_country": "Россия",
            "target_region": "Москва",
            "target_city": "Москва",
            "target_geo_scope": "local",
            "target_work_mode": "Hybrid",
            "target_domain": "Fintech",
            "current_skills": ["Python"],
        },
    )

    assert payload["username"] == "alice"
    assert payload["target_role"] == "analyst"
    assert payload["target_country"] == "Россия"
    assert payload["target_region"] == "Москва"
    assert payload["target_city"] == "Москва"
    assert payload["target_geo_scope"] == "local"
    assert payload["target_domain"] == "Fintech"
    assert payload["current_skills"] == ["Python"]


def test_onboarding_progress_line() -> None:
    assert onboarding._progress_line("role") == "Шаг 1/7: ●○○○○○○"
    assert onboarding._progress_line("confirm_skills") == "Шаг 7/7: ●●●●●●●"


def test_format_profile_renders_warnings() -> None:
    text = onboarding.format_profile(
        {
            "target_role": "ml",
            "target_grade": None,
            "target_city_tier": None,
            "target_country": "Россия",
            "target_region": "Москва",
            "target_city": "Москва",
            "target_geo_scope": "local",
            "target_work_mode": "Remote",
            "target_domain": "Fintech",
            "current_skills": ["Python", "Airflow"],
            "warnings": ["Data is stale"],
        }
    )

    assert "Ваш профиль" in text
    assert "ml" in text
    assert "Россия · Москва · Москва · local" in text
    assert "Fintech" in text
    assert "⚠️" in text
    assert "Data is stale" in text


def test_format_profile_handles_missing_and_escaped_fields() -> None:
    text = onboarding.format_profile(
        {
            "target_role": None,
            "target_grade": "",
            "target_city_tier": None,
            "target_work_mode": None,
            "target_domain": "<script>alert(1)</script>",
            "current_skills": ["Python", "<b>hack</b>"],
        }
    )

    assert "Ваш профиль" in text
    assert "—" in text  # placeholder for missing fields
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in text
    assert "Python, &lt;b&gt;hack&lt;/b&gt;" in text


def test_role_keyboard_contains_pagination_controls() -> None:
    markup = kb_onboarding.build_role_keyboard(["A", "B", "C", "D", "E"], page=1, page_size=2)
    callbacks = [button.callback_data for row in markup.inline_keyboard for button in row]

    assert kb_onboarding.SelectionCallbackFactory.pack("role", "A") in callbacks
    assert kb_onboarding.PaginationCallbackFactory.pack("role", 2) in callbacks


def test_domain_keyboard_has_skip_button() -> None:
    markup = kb_onboarding.build_domain_keyboard(["Fintech", "E-commerce"], page=1, page_size=5)
    callbacks = [button.callback_data for row in markup.inline_keyboard for button in row]

    assert kb_onboarding.SelectionCallbackFactory.pack("domain", kb_onboarding.SKIP_DOMAIN_VALUE) in callbacks


def _run_selection_handler(
    monkeypatch: Any,
    handler: Callable[..., Awaitable[None]],
    step: str,
) -> None:
    callback = SimpleNamespace(
        data=kb_onboarding.SelectionCallbackFactory.pack(step, "value"),
        message=AsyncMock(),
        answer=AsyncMock(),
        from_user=SimpleNamespace(id=1, username="alice"),
    )
    state = AsyncMock()
    api_client = SimpleNamespace()
    meta_cache = SimpleNamespace()

    process_mock = AsyncMock()
    monkeypatch.setattr(onboarding, "_process_selection", process_mock)

    kwargs = {
        "callback": callback,
        "state": state,
        "api_client": api_client,
        "meta_cache": meta_cache,
    }
    accepted_kwargs = {name: kwargs[name] for name in inspect.signature(handler).parameters if name in kwargs}

    asyncio.run(handler(**accepted_kwargs))

    process_mock.assert_awaited_once()
    assert process_mock.await_args.kwargs["step"] == step
    assert process_mock.await_args.kwargs["value"] == "value"
    assert process_mock.await_args.kwargs["user"] == callback.from_user
    assert process_mock.await_args.args[3] is meta_cache


def test_select_role_calls_process_selection(monkeypatch: Any) -> None:
    _run_selection_handler(monkeypatch, onboarding.select_role, "role")


def test_select_grade_calls_process_selection(monkeypatch: Any) -> None:
    _run_selection_handler(monkeypatch, onboarding.select_grade, "grade")


def test_select_city_tier_calls_process_selection(monkeypatch: Any) -> None:
    _run_selection_handler(monkeypatch, onboarding.select_city_tier, "city_tier")


def test_select_work_mode_calls_process_selection(monkeypatch: Any) -> None:
    _run_selection_handler(monkeypatch, onboarding.select_work_mode, "work_mode")


def test_select_domain_calls_process_selection(monkeypatch: Any) -> None:
    _run_selection_handler(monkeypatch, onboarding.select_domain, "domain")


def test_paginate_callback_updates_markup() -> None:
    state = AsyncMock()
    state.get_data = AsyncMock(return_value={"role_options": ["A", "B", "C", "D"]})
    state.update_data = AsyncMock()
    callback_message = AsyncMock()
    callback_message.edit_reply_markup = AsyncMock()
    callback = SimpleNamespace(
        data=kb_onboarding.PaginationCallbackFactory.pack("role", 2),
        message=callback_message,
        answer=AsyncMock(),
        from_user=None,
    )
    api_client = SimpleNamespace()
    meta_cache = SimpleNamespace(get_roles=AsyncMock(return_value=[]))

    asyncio.run(onboarding.paginate_onboarding_options(callback, state, api_client, meta_cache))

    callback_message.edit_reply_markup.assert_awaited_once()
    state.update_data.assert_awaited_with({"role_page": 2})


def test_skills_confirmation_keyboard_has_two_actions() -> None:
    markup = onboarding.skills_confirmation_keyboard()
    buttons = [button.callback_data for button in markup.inline_keyboard[0]]
    assert onboarding.CONFIRM_CALLBACK in buttons
    assert onboarding.EDIT_CALLBACK in buttons


def test_settings_keyboard_contains_all_fields() -> None:
    markup = onboarding.settings_keyboard()
    callbacks = [button.callback_data for row in markup.inline_keyboard for button in row]
    assert f"{onboarding.SETTINGS_FIELD_PREFIX}:target_role" in callbacks
    assert f"{onboarding.SETTINGS_FIELD_PREFIX}:current_skills" in callbacks


def test_merge_profile_keeps_existing_values() -> None:
    profile = {
        "target_role": "analyst",
        "target_grade": "Junior",
        "target_city_tier": "Moscow",
        "target_country": "Россия",
        "target_region": "Москва",
        "target_city": "Москва",
        "target_geo_scope": "local",
        "target_work_mode": "Office",
        "target_domain": None,
        "current_skills": ["python"],
    }

    merged = onboarding._merge_profile(profile, {"target_grade": "Middle"})

    assert merged["target_role"] == "analyst"
    assert merged["target_grade"] == "Middle"
    assert merged["target_country"] == "Россия"
    assert merged["target_region"] == "Москва"
    assert merged["target_city"] == "Москва"
    assert merged["target_geo_scope"] == "local"
    assert merged["current_skills"] == ["python"]


def test_api_client_headers_include_service_token() -> None:
    headers = SkillraApiClient._default_headers("token123")
    # Authorization: Bearer was removed (GAP-07): only X-Skillra-Token is used.
    assert "Authorization" not in headers
    assert headers["X-Skillra-Token"] == "token123"
