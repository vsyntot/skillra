from __future__ import annotations

import asyncio
from types import SimpleNamespace

from telegram_bot.handlers import analytics, onboarding
from telegram_bot.services.errors import SkillraApiError


class DummyMetaCache:
    def __init__(self, skills: list[str] | None = None) -> None:
        self._skills = skills or ["golang", "luau", "rust", "scala"]

    async def get_skills(self, *_: object) -> list[str]:  # noqa: D401
        return self._skills


def _api_error(payload: dict[str, object]) -> SkillraApiError:
    return SkillraApiError(
        error_code=payload.get("error_code") if isinstance(payload, dict) else None,
        error_message=payload.get("message") if isinstance(payload, dict) else None,
        status_code=400,
        request_id="req-test",
        payload=payload,
    )


class DummyMessage:
    def __init__(self) -> None:
        self.answers: list[str] = []
        self.from_user = SimpleNamespace(id=1, username="alice")

    async def answer(self, text: str, **_: object) -> None:  # noqa: D401
        self.answers.append(text)


class DummyState:
    def __init__(self, data: dict[str, object] | None = None) -> None:
        self._data = data or {}

    async def get_data(self) -> dict[str, object]:
        return self._data

    async def clear(self) -> None:  # pragma: no cover - not used in these tests
        self._data = {}


class DummyCallback:
    def __init__(self) -> None:
        self.data = onboarding.CONFIRM_CALLBACK
        self.from_user = SimpleNamespace(id=1, username="alice")
        self.message = DummyMessage()
        self.answered = False

    async def answer(self, *_: object, **__: object) -> None:
        self.answered = True


def test_handle_market_map_formats_unknown_skills_error() -> None:
    async def _run() -> None:
        exc = _api_error(
            {
                "error_code": "UNKNOWN_SKILLS",
                "details": {"unknown_skills": ["Lua", "Go"]},
            }
        )

        class DummyClient:
            async def get_profile(self, _: int) -> dict[str, object]:
                return {
                    "target_role": "analyst",
                    "target_grade": "Junior",
                    "target_city_tier": "Moscow",
                    "target_work_mode": "Office",
                }

            async def market_segment_summary(self, _: dict[str, object]) -> dict[str, object]:
                raise exc

        message = DummyMessage()
        meta_cache = DummyMetaCache()

        await analytics.handle_market_map(message, DummyClient(), meta_cache)

        assert message.answers[-1] == (
            "Некоторые навыки неизвестны:\n"
            "• lua. Возможно вы имели в виду: luau, golang\n"
            "• go. Возможно вы имели в виду: golang\n"
            "Откройте /settings и исправьте."
        )

    asyncio.run(_run())


def test_handle_skill_gap_formats_data_unavailable_error() -> None:
    async def _run() -> None:
        exc = _api_error({"error_code": "DATA_UNAVAILABLE"})

        class DummyClient:
            async def get_profile(self, _: int) -> dict[str, object]:
                return {
                    "target_role": "analyst",
                    "target_grade": "Junior",
                    "target_city_tier": "Moscow",
                    "target_work_mode": "Remote",
                }

            async def persona_analyze(self, _: dict[str, object]) -> dict[str, object]:
                raise exc

        message = DummyMessage()

        meta_cache = DummyMetaCache()

        await analytics.handle_skill_gap(message, DummyClient(), meta_cache)

        assert message.answers[-1] == "Данные ещё не загружены. Попробуйте позже."

    asyncio.run(_run())


def test_confirm_skills_formats_unknown_skills_error() -> None:
    async def _run() -> None:
        exc = _api_error(
            {
                "error_code": "UNKNOWN_SKILLS",
                "details": {"unknown_skills": ["Scala", "R"]},
            }
        )

        class DummyClient:
            async def upsert_profile(self, *_: object, **__: object) -> dict[str, object]:
                raise exc

        callback = DummyCallback()
        state = DummyState(data={"current_skills": ["Scala", "R"]})

        meta_cache = DummyMetaCache(skills=["scala", "scipy", "rust"])

        await onboarding.confirm_skills(callback, state, DummyClient(), meta_cache)

        assert callback.message.answers[-1] == (
            "Некоторые навыки неизвестны:\n"
            "• scala. Возможно вы имели в виду: scala, scipy\n"
            "• r. Возможно вы имели в виду: rust\n"
            "Исправьте список и попробуйте снова."
        )

    asyncio.run(_run())
