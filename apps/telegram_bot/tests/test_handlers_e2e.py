from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock

from aiogram import Bot, Dispatcher
from aiogram.client.session.base import BaseSession
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.methods import AnswerCallbackQuery, EditMessageReplyMarkup, SendMessage
from aiogram.types import Message, Update
from telegram_bot.config import DigestSettings
from telegram_bot.handlers import onboarding, subscriptions
from telegram_bot.keyboards.onboarding import SelectionCallbackFactory
from telegram_bot.services.errors import SkillraApiError


class DummySession(BaseSession):
    def __init__(self) -> None:
        super().__init__()
        self.requests: list[Any] = []

    async def close(self) -> None:  # pragma: no cover - part of session API
        return None

    async def stream_content(self, *args: Any, **kwargs: Any) -> bytes:  # pragma: no cover - not used in tests
        return b""

    async def make_request(self, bot: Bot, method: Any, timeout: int | None = None) -> Any:
        self.requests.append(method)
        if isinstance(method, SendMessage):
            payload = {
                "message_id": len(self.requests),
                "date": 0,
                "chat": {"id": method.chat_id, "type": "private"},
                "from": {"id": bot.id, "is_bot": True, "first_name": "Bot"},
                "text": method.text,
            }
            return Message.model_validate(payload, context={"bot": bot})

        if isinstance(method, EditMessageReplyMarkup):
            return True

        if isinstance(method, AnswerCallbackQuery):
            return True

        return True

    @property
    def sent_texts(self) -> list[str | None]:
        return [req.text for req in self.requests if isinstance(req, SendMessage)]


def _storage_state(dp: Dispatcher, bot: Bot, chat_id: int, user_id: int) -> FSMContext:
    return FSMContext(storage=dp.storage, key=StorageKey(bot_id=bot.id, chat_id=chat_id, user_id=user_id))


def _update_from_message(bot: Bot, *, text: str, chat_id: int, user_id: int, update_id: int) -> Update:
    payload = {
        "update_id": update_id,
        "message": {
            "message_id": update_id,
            "date": 0,
            "chat": {"id": chat_id, "type": "private"},
            "from": {"id": user_id, "is_bot": False, "first_name": "Test"},
            "text": text,
        },
    }
    return Update.model_validate(payload, context={"bot": bot})


def _update_from_callback(
    bot: Bot, *, data: str, chat_id: int, user_id: int, update_id: int, message_id: int = 1
) -> Update:
    payload = {
        "update_id": update_id,
        "callback_query": {
            "id": str(update_id),
            "from": {"id": user_id, "is_bot": False, "first_name": "Test"},
            "chat_instance": "test-instance",
            "message": {
                "message_id": message_id,
                "date": 0,
                "chat": {"id": chat_id, "type": "private"},
                "from": {"id": user_id, "is_bot": False, "first_name": "Test"},
                "text": "callback-message",
            },
            "data": data,
        },
    }
    return Update.model_validate(payload, context={"bot": bot})


async def _dispatch(dp: Dispatcher, bot: Bot, update: Update) -> None:
    await dp.feed_update(bot, update, data=dp.workflow_data)


def test_onboarding_happy_path_through_dispatcher() -> None:
    async def _run() -> None:
        session = DummySession()
        bot = Bot(token="123:TEST", session=session)
        storage = MemoryStorage()
        dp = Dispatcher(storage=storage)
        dp.include_router(onboarding.router)

        api_client = type(
            "ApiMock",
            (),
            {
                "get_profile": AsyncMock(
                    side_effect=[
                        SkillraApiError(
                            error_code="PROFILE_NOT_FOUND",
                            error_message=None,
                            status_code=404,
                            request_id="req-1",
                            payload={},
                        )
                    ]
                ),
                "upsert_profile": AsyncMock(
                    return_value={
                        "target_role": "Data Analyst",
                        "target_grade": "Junior",
                        "target_city_tier": "Tier-1",
                        "target_work_mode": "Remote",
                        "target_domain": "Fintech",
                        "current_skills": ["python", "sql"],
                    }
                ),
            },
        )()

        meta_cache = type(
            "MetaMock",
            (),
            {
                "get_roles": AsyncMock(return_value=["Data Analyst"]),
                "get_grades": AsyncMock(return_value=["Junior"]),
                "get_city_tiers": AsyncMock(return_value=["Tier-1"]),
                "get_work_modes": AsyncMock(return_value=["Remote"]),
                "get_domains": AsyncMock(return_value=["Fintech"]),
                "get_skills": AsyncMock(return_value=["python", "sql"]),
            },
        )()

        dp.workflow_data.update({"api_client": api_client, "meta_cache": meta_cache})

        chat_id = 100
        user_id = 200

        start_update = _update_from_message(bot, text="/start", chat_id=chat_id, user_id=user_id, update_id=1)
        await _dispatch(dp, bot, start_update)

        state = _storage_state(dp, bot, chat_id, user_id)
        assert await state.get_state() == onboarding.ProfileOnboarding.role.state

        selections = [
            ("role", "Data Analyst"),
            ("grade", "Junior"),
            ("city_tier", "Tier-1"),
            ("work_mode", "Remote"),
            ("domain", "Fintech"),
        ]

        for idx, (step, value) in enumerate(selections, start=2):
            callback_update = _update_from_callback(
                bot,
                data=SelectionCallbackFactory.pack(step, value),
                chat_id=chat_id,
                user_id=user_id,
                update_id=idx,
                message_id=idx,
            )
            await _dispatch(dp, bot, callback_update)

        skills_update = _update_from_message(bot, text="python, sql", chat_id=chat_id, user_id=user_id, update_id=8)
        await _dispatch(dp, bot, skills_update)

        confirm_update = _update_from_callback(
            bot,
            data=onboarding.CONFIRM_CALLBACK,
            chat_id=chat_id,
            user_id=user_id,
            update_id=9,
            message_id=8,
        )
        await _dispatch(dp, bot, confirm_update)

        assert api_client.upsert_profile.await_count == 1
        call = api_client.upsert_profile.await_args
        assert call.args[0] == user_id
        payload = call.args[1]
        assert payload["target_role"] == "Data Analyst"
        assert payload["target_grade"] == "Junior"
        assert payload["target_city_tier"] == "Tier-1"
        assert payload["target_work_mode"] == "Remote"
        assert payload["target_domain"] == "Fintech"
        assert payload["current_skills"] == ["python", "sql"]

        assert await state.get_state() == onboarding.ProfileOnboarding.upload_resume.state
        assert session.sent_texts
        assert any("/resume" in (text or "") for text in session.sent_texts)
        resume_offer = [req for req in session.requests if isinstance(req, SendMessage)][-1]
        callbacks = [button.callback_data for row in resume_offer.reply_markup.inline_keyboard for button in row]
        assert onboarding.RESUME_UPLOAD_CALLBACK in callbacks
        assert onboarding.RESUME_SKIP_CALLBACK in callbacks
        await bot.session.close()

    asyncio.run(_run())


def test_subscription_flow_through_dispatcher() -> None:
    async def _run() -> None:
        session = DummySession()
        bot = Bot(token="123:TEST", session=session)
        storage = MemoryStorage()
        dp = Dispatcher(storage=storage)
        dp.include_router(subscriptions.router)

        api_client = type(
            "ApiMock",
            (),
            {
                "upsert_weekly_subscription": AsyncMock(
                    return_value={"weekday": 1, "time_local": "18:00", "timezone": "Europe/Moscow"}
                )
            },
        )()

        digest_settings = DigestSettings(
            default_weekday=0,
            default_time_local="09:00",
            default_timezone="Europe/Moscow",
        )
        dp.workflow_data.update({"api_client": api_client, "digest_settings": digest_settings})

        chat_id = 300
        user_id = 400

        start_update = _update_from_message(bot, text="/subscribe", chat_id=chat_id, user_id=user_id, update_id=1)
        await _dispatch(dp, bot, start_update)

        tz_update = _update_from_callback(
            bot,
            data=f"{subscriptions.TIMEZONE_PREFIX}Europe/Moscow",
            chat_id=chat_id,
            user_id=user_id,
            update_id=2,
        )
        await _dispatch(dp, bot, tz_update)

        weekday_update = _update_from_callback(
            bot,
            data=f"{subscriptions.WEEKDAY_PREFIX}1",
            chat_id=chat_id,
            user_id=user_id,
            update_id=3,
        )
        await _dispatch(dp, bot, weekday_update)

        time_update = _update_from_callback(
            bot,
            data=f"{subscriptions.TIME_PREFIX}18:00",
            chat_id=chat_id,
            user_id=user_id,
            update_id=4,
        )
        await _dispatch(dp, bot, time_update)

        assert api_client.upsert_weekly_subscription.await_count == 1
        call = api_client.upsert_weekly_subscription.await_args
        assert call.args[0] == user_id
        payload = call.args[1]
        assert payload == {"active": True, "weekday": 1, "time_local": "18:00", "timezone": "Europe/Moscow"}

        state = _storage_state(dp, bot, chat_id, user_id)
        assert await state.get_state() is None
        assert session.sent_texts
        await bot.session.close()

    asyncio.run(_run())
