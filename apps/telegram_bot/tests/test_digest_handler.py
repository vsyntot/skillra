import asyncio
from types import SimpleNamespace

from aiogram.types import ReplyKeyboardMarkup
from telegram_bot.handlers import commands
from telegram_bot.services.errors import SkillraApiError


class DummyMessage:
    def __init__(self) -> None:
        self.answers: list[tuple[str, dict[str, object]]] = []
        self.photos: list[tuple[object, dict[str, object]]] = []
        self.from_user = SimpleNamespace(id=42)

    async def answer(self, text: str, **kwargs: object) -> None:  # noqa: D401
        self.answers.append((text, kwargs))

    async def answer_photo(self, photo: object, **kwargs: object) -> None:  # noqa: D401
        self.photos.append((photo, kwargs))


def test_handle_digest_sends_preview_and_chart() -> None:
    async def _run() -> None:
        message = DummyMessage()

        class DummyClient:
            async def get_digest_preview(self, user_id: int, *, source: str | None = None) -> dict[str, object]:
                assert user_id == 42
                assert source == "bot"
                return {"text": "Digest content"}

            async def get_digest_chart(self, user_id: int) -> bytes:  # noqa: D401
                assert user_id == 42
                return b"chart-bytes"

        await commands.handle_digest(message, DummyClient())

        assert message.answers == [("Digest content", {"parse_mode": None})]
        assert len(message.photos) == 1
        _, photo_kwargs = message.photos[0]
        assert photo_kwargs.get("caption") == "Digest график"

    asyncio.run(_run())


def test_handle_digest_prompts_onboarding_for_missing_profile() -> None:
    async def _run() -> None:
        message = DummyMessage()

        class DummyClient:
            async def get_digest_preview(self, user_id: int, *, source: str | None = None) -> dict[str, object]:
                assert user_id == 42
                assert source == "bot"
                raise SkillraApiError(
                    error_code="PROFILE_NOT_FOUND",
                    error_message=None,
                    status_code=404,
                    request_id="req-digest",
                    payload={"error_code": "PROFILE_NOT_FOUND"},
                )

        await commands.handle_digest(message, DummyClient())

        assert message.answers
        text, kwargs = message.answers[-1]
        assert commands.DIGEST_PROFILE_FALLBACK in text
        assert isinstance(kwargs.get("reply_markup"), ReplyKeyboardMarkup)
        assert not message.photos

    asyncio.run(_run())


def test_handle_digest_history_sends_recent_items() -> None:
    async def _run() -> None:
        message = DummyMessage()

        class DummyClient:
            async def get_digest_history(self, user_id: int, *, limit: int, offset: int) -> dict[str, object]:  # noqa: D401
                assert user_id == 42
                assert limit == 5
                assert offset == 0
                return {
                    "total": 1,
                    "items": [
                        {
                            "id": 1,
                            "sent_at": "2026-05-20T09:00:00Z",
                            "format": "html",
                            "text_preview": "Digest preview",
                        }
                    ],
                }

        await commands.handle_digest_history(message, DummyClient())

        assert message.answers
        text, kwargs = message.answers[-1]
        assert "История дайджестов" in text
        assert "Digest preview" in text
        assert kwargs["parse_mode"].value == "HTML"

    asyncio.run(_run())
