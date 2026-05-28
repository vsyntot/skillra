from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from telegram_bot.handlers import search
from telegram_bot.services.callback_context import CallbackContextStore


class FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    async def set(self, name: str, value: str, ex: int | None = None) -> bool:  # noqa: ARG002
        self.values[name] = value
        return True

    async def get(self, name: str) -> str | None:
        return self.values.get(name)

    async def delete(self, name: str) -> int:
        return 1 if self.values.pop(name, None) is not None else 0


def _callback_context() -> CallbackContextStore:
    return CallbackContextStore(signing_secret="secret", redis_client=FakeRedis())


def test_format_search_results_renders_links_and_limits() -> None:
    vacancies = [
        {
            "title": f"Python Developer {index}",
            "employer": "Skillra",
            "city": "Moscow",
            "salary_from": 100000,
            "salary_to": 150000,
            "hh_url": f"https://hh.ru/vacancy/{index}",
        }
        for index in range(6)
    ]

    text = search.format_search_results(
        "Python",
        vacancies,
        {
            "confidence": "medium",
            "index_status": "success",
            "dataset_run_id": "run-1",
        },
    )

    assert "Результаты" in text
    assert "Надёжность поиска" in text
    assert "среднее" in text
    assert "Python Developer 0" in text
    assert "100 000-150 000 ₽" in text
    assert "https://hh.ru/vacancy/0" in text
    assert "Python Developer 5" not in text


def test_handle_search_calls_api_client() -> None:
    async def _run() -> None:
        message = AsyncMock()
        message.text = "/search Python Data Analyst"
        message.from_user = SimpleNamespace(id=42)
        api_client = AsyncMock()
        api_client.get_profile.return_value = {
            "target_role": "analyst",
            "target_grade": "middle",
            "target_country": "Россия",
            "target_region": "Москва",
            "target_city": "Москва",
            "target_geo_scope": "local",
        }
        api_client.search_vacancies_payload.return_value = {
            "results": [
                {
                    "hh_vacancy_id": "1",
                    "title": "Data Analyst",
                    "employer": "Acme",
                    "hh_url": "https://hh.ru/vacancy/1",
                }
            ]
        }

        await search.handle_search(message, api_client)

        api_client.search_vacancies_payload.assert_awaited_once_with(
            q="Python Data Analyst",
            limit=search.RESULTS_PER_PAGE,
            role="analyst",
            grade="middle",
            country="Россия",
            region="Москва",
            city="Москва",
            geo_scope="local",
            telegram_user_id=42,
            source="bot",
        )
        answer_text = message.answer.await_args.args[0]
        assert "Data Analyst" in answer_text
        assert "Открыть на hh.ru" in answer_text
        assert message.answer.await_args.kwargs["reply_markup"] is not None
        assert message.answer.await_args.kwargs["disable_web_page_preview"] is True

    asyncio.run(_run())


def test_handle_search_uses_durable_save_callbacks_when_context_available() -> None:
    async def _run() -> None:
        message = AsyncMock()
        message.text = "/search Python Data Analyst"
        message.from_user = SimpleNamespace(id=42)
        api_client = AsyncMock()
        api_client.get_profile.return_value = {}
        api_client.search_vacancies_payload.return_value = {
            "results": [
                {
                    "hh_vacancy_id": "1",
                    "title": "Data Analyst",
                    "employer": "Acme",
                    "hh_url": "https://hh.ru/vacancy/1",
                }
            ]
        }

        await search.handle_search(message, api_client, callback_context=_callback_context())

        keyboard = message.answer.await_args.kwargs["reply_markup"]
        callbacks = [button.callback_data for row in keyboard.inline_keyboard for button in row]
        assert callbacks[0].startswith("srch:save:")

    asyncio.run(_run())


def test_handle_search_shows_usage_without_query() -> None:
    async def _run() -> None:
        message = AsyncMock()
        message.text = "/search"
        api_client = AsyncMock()

        await search.handle_search(message, api_client)

        api_client.search_vacancies_payload.assert_not_called()
        assert "/search Python Data Analyst" in message.answer.await_args.args[0]

    asyncio.run(_run())


def test_build_search_results_keyboard_adds_save_buttons() -> None:
    keyboard = search.build_search_results_keyboard(
        [
            {"hh_vacancy_id": "101", "title": "A"},
            {"hh_vacancy_id": "102", "title": "B"},
        ]
    )

    assert keyboard is not None
    buttons = [button for row in keyboard.inline_keyboard for button in row]
    assert [button.text for button in buttons] == ["Сохранить 1", "Сохранить 2"]
    assert [button.callback_data for button in buttons] == ["vac:save:101", "vac:save:102"]


def test_save_search_vacancy_creates_plan_when_missing() -> None:
    async def _run() -> None:
        callback = AsyncMock()
        callback.data = "vac:save:101"
        callback.from_user = SimpleNamespace(id=42)
        callback.message = AsyncMock()
        api_client = AsyncMock()
        api_client.save_career_plan_vacancy.side_effect = [
            search.SkillraApiError(
                error_code="CAREER_PLAN_NOT_FOUND",
                error_message=None,
                status_code=404,
                request_id=None,
                payload={},
            ),
            {
                "id": 7,
                "vacancy_title": "Data Analyst",
                "application_status": "saved",
            },
        ]
        search._SEARCH_RESULT_CACHE.clear()
        search._cache_search_results(
            42,
            [
                {
                    "hh_vacancy_id": "101",
                    "title": "Data Analyst",
                    "hh_url": "https://hh.ru/vacancy/101",
                }
            ],
        )

        await search.save_search_vacancy(callback, api_client)

        api_client.upsert_career_plan.assert_awaited_once_with(42, {"notes": "Создано из Telegram /search"})
        assert api_client.save_career_plan_vacancy.await_count == 2
        payload = api_client.save_career_plan_vacancy.await_args_list[-1].args[1]
        assert payload == {
            "hh_vacancy_id": "101",
            "title": "Data Analyst",
            "url": "https://hh.ru/vacancy/101",
        }
        assert "Вакансия сохранена" in callback.message.answer.await_args.args[0]
        assert callback.message.answer.await_args.kwargs["reply_markup"] is not None

    asyncio.run(_run())


def test_save_search_vacancy_uses_durable_context_after_memory_clear() -> None:
    async def _run() -> None:
        store = _callback_context()
        callback_data = await store.create_callback_data(
            namespace=search.SEARCH_CALLBACK_NAMESPACE,
            action=search.SEARCH_SAVE_ACTION,
            user_id=42,
            entity_type="vacancy",
            entity_id="101",
            payload={
                "hh_vacancy_id": "101",
                "title": "Data Analyst",
                "url": "https://hh.ru/vacancy/101",
            },
            ttl_seconds=search.SEARCH_RESULT_CACHE_TTL_SECONDS,
        )
        callback = AsyncMock()
        callback.data = callback_data
        callback.from_user = SimpleNamespace(id=42)
        callback.message = AsyncMock()
        api_client = AsyncMock()
        api_client.save_career_plan_vacancy.return_value = {
            "id": 7,
            "vacancy_title": "Data Analyst",
            "application_status": "saved",
        }
        search._SEARCH_RESULT_CACHE.clear()

        await search.save_search_vacancy(callback, api_client, callback_context=store)

        api_client.save_career_plan_vacancy.assert_awaited_once_with(
            42,
            {
                "hh_vacancy_id": "101",
                "title": "Data Analyst",
                "url": "https://hh.ru/vacancy/101",
            },
        )
        keyboard = callback.message.answer.await_args.kwargs["reply_markup"]
        callbacks = [button.callback_data for row in keyboard.inline_keyboard for button in row]
        assert callbacks[0].startswith("srch:outcome:")

    asyncio.run(_run())


def test_save_search_vacancy_reports_missing_durable_context() -> None:
    async def _run() -> None:
        callback = AsyncMock()
        callback.data = "srch:save:missing"
        callback.from_user = SimpleNamespace(id=42)
        callback.message = AsyncMock()
        api_client = AsyncMock()

        await search.save_search_vacancy(callback, api_client, callback_context=_callback_context())

        api_client.save_career_plan_vacancy.assert_not_called()
        assert "Повторите /search" in callback.message.answer.await_args.args[0]

    asyncio.run(_run())


def test_save_search_vacancy_reports_expired_callback(monkeypatch) -> None:
    async def _run() -> None:
        callback = AsyncMock()
        callback.data = "vac:save:101"
        callback.from_user = SimpleNamespace(id=42)
        callback.message = AsyncMock()
        api_client = AsyncMock()

        search._SEARCH_RESULT_CACHE.clear()
        monkeypatch.setattr(search.time, "time", lambda: 1000.0)
        search._cache_search_results(
            42,
            [
                {
                    "hh_vacancy_id": "101",
                    "title": "Data Analyst",
                    "hh_url": "https://hh.ru/vacancy/101",
                }
            ],
        )
        monkeypatch.setattr(search.time, "time", lambda: 1000.0 + search.SEARCH_RESULT_CACHE_TTL_SECONDS + 1)

        await search.save_search_vacancy(callback, api_client)

        api_client.save_career_plan_vacancy.assert_not_awaited()
        assert "Срок действия кнопки истёк" in callback.message.answer.await_args.args[0]

    asyncio.run(_run())


def test_update_search_vacancy_outcome_calls_api() -> None:
    async def _run() -> None:
        callback = AsyncMock()
        callback.data = "vac:out:7:interview"
        callback.from_user = SimpleNamespace(id=42)
        callback.message = AsyncMock()
        api_client = AsyncMock()
        api_client.update_application_outcome.return_value = {
            "id": 7,
            "vacancy_title": "Data Analyst",
            "application_status": "interview",
        }

        await search.update_search_vacancy_outcome(callback, api_client)

        api_client.update_application_outcome.assert_awaited_once_with(42, 7, "interview", source="bot")
        assert "Интервью" in callback.message.answer.await_args.args[0]
        assert "Data Analyst" in callback.message.answer.await_args.args[0]

    asyncio.run(_run())


def test_update_search_vacancy_outcome_uses_durable_context() -> None:
    async def _run() -> None:
        store = _callback_context()
        callback_data = await store.create_callback_data(
            namespace=search.SEARCH_CALLBACK_NAMESPACE,
            action=search.SEARCH_OUTCOME_ACTION,
            user_id=42,
            entity_type="career_action",
            entity_id="7",
            payload={"action_id": 7, "status": "interview"},
            ttl_seconds=search.SEARCH_RESULT_CACHE_TTL_SECONDS,
        )
        callback = AsyncMock()
        callback.data = callback_data
        callback.from_user = SimpleNamespace(id=42)
        callback.message = AsyncMock()
        api_client = AsyncMock()
        api_client.update_application_outcome.return_value = {
            "id": 7,
            "vacancy_title": "Data Analyst",
            "application_status": "interview",
        }

        await search.update_search_vacancy_outcome(callback, api_client, callback_context=store)

        api_client.update_application_outcome.assert_awaited_once_with(42, 7, "interview", source="bot")
        assert "Интервью" in callback.message.answer.await_args.args[0]

    asyncio.run(_run())
