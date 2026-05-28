import asyncio
from types import SimpleNamespace

from aiogram.enums import ParseMode
from telegram_bot.handlers import commands
from telegram_bot.services.errors import SkillraApiError


class DummyMessage:
    def __init__(self) -> None:
        self.answers: list[tuple[str, dict[str, object]]] = []
        self.from_user = SimpleNamespace(id=42)

    async def answer(self, text: str, **kwargs: object) -> None:  # noqa: D401
        self.answers.append((text, kwargs))


class DummyCallback:
    def __init__(self, data: str) -> None:
        self.data = data
        self.from_user = SimpleNamespace(id=42)
        self.message = DummyMessage()
        self.answered = False

    async def answer(self) -> None:
        self.answered = True


def _career_plan() -> dict[str, object]:
    return {
        "telegram_user_id": 42,
        "target_role": "Data Analyst",
        "target_grade": "Middle",
        "target_city_tier": "Moscow",
        "target_work_mode": "remote",
        "target_domain": "fintech",
        "status": "active",
        "notes": "focus",
        "actions": [
            {
                "id": 7,
                "title": "Learn Airflow",
                "action_type": "learning",
                "status": "planned",
                "priority": 10,
                "skill_name": "Airflow",
            }
        ],
    }


def test_format_career_plan_message_lists_actions() -> None:
    text = commands.format_career_plan_message(_career_plan())

    assert "Карьерный план" in text
    assert "Data Analyst" in text
    assert "Learn Airflow" in text
    assert "0/1 завершено" in text


def test_build_plan_actions_keyboard_adds_status_buttons() -> None:
    keyboard = commands.build_plan_actions_keyboard(_career_plan())

    assert keyboard is not None
    buttons = [button for row in keyboard.inline_keyboard for button in row]
    assert [button.text for button in buttons] == ["1 · В работе", "1 · Готово", "1 · Отложить"]
    assert [button.callback_data for button in buttons] == [
        "plan:act:7:in_progress",
        "plan:act:7:done",
        "plan:act:7:skipped",
    ]


def test_update_plan_action_status_callback() -> None:
    async def _run() -> None:
        callback = DummyCallback("plan:act:7:done")

        class DummyClient:
            async def patch_career_action(
                self,
                user_id: int,
                action_id: int,
                payload: dict[str, object],
            ) -> dict[str, object]:  # noqa: D401
                assert user_id == 42
                assert action_id == 7
                assert payload == {"status": "done"}
                return {"id": 7, "title": "Learn Airflow", "status": "done"}

        await commands.update_plan_action_status(callback, DummyClient())

        assert callback.answered is True
        assert callback.message.answers
        text, kwargs = callback.message.answers[-1]
        assert "Статус обновлён" in text
        assert "Learn Airflow" in text
        assert kwargs.get("parse_mode") == ParseMode.HTML

    asyncio.run(_run())


def test_handle_plan_creates_missing_plan() -> None:
    async def _run() -> None:
        message = DummyMessage()

        class DummyClient:
            async def get_career_plan(self, user_id: int) -> dict[str, object]:  # noqa: D401
                assert user_id == 42
                raise SkillraApiError(
                    error_code="CAREER_PLAN_NOT_FOUND",
                    error_message=None,
                    status_code=404,
                    request_id="req-plan",
                    payload={"error_code": "CAREER_PLAN_NOT_FOUND"},
                )

            async def upsert_career_plan(
                self,
                user_id: int,
                payload: dict[str, object],
            ) -> dict[str, object]:  # noqa: D401
                assert user_id == 42
                assert payload["notes"] == "Создано из Telegram /plan"
                return _career_plan()

        await commands.handle_plan(message, DummyClient())

        assert message.answers
        text, kwargs = message.answers[-1]
        assert "Learn Airflow" in text
        assert kwargs.get("parse_mode") == ParseMode.HTML

    asyncio.run(_run())


def test_handle_plan_recommend_generates_actions() -> None:
    async def _run() -> None:
        message = DummyMessage()

        class DummyClient:
            async def get_career_plan(self, user_id: int) -> dict[str, object]:  # noqa: D401
                assert user_id == 42
                return _career_plan()

            async def generate_career_plan_actions(
                self,
                user_id: int,
                *,
                limit: int,
                replace_generated: bool,
            ) -> dict[str, object]:  # noqa: D401
                assert user_id == 42
                assert limit == 5
                assert replace_generated is False
                plan = _career_plan()
                plan["actions"] = [
                    {
                        "id": 9,
                        "title": "Close SQL skill gap",
                        "action_type": "learning",
                        "status": "planned",
                        "priority": 10,
                        "skill_name": "SQL",
                    }
                ]
                return plan

        await commands.handle_plan_recommend(message, DummyClient())

        assert message.answers
        text, kwargs = message.answers[-1]
        assert "Рекомендации из skill gap добавлены" in text
        assert "Close SQL skill gap" in text
        assert kwargs.get("parse_mode") == ParseMode.HTML

    asyncio.run(_run())
