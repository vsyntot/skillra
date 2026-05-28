from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from telegram_bot.handlers import pdf_report
from telegram_bot.services.errors import SkillraApiError


def test_handle_pdf_report_exports_profile_pdf() -> None:
    async def _run() -> None:
        message = AsyncMock()
        message.from_user = SimpleNamespace(id=42, username="alice")
        api_client = AsyncMock()
        api_client.get_profile.return_value = {
            "target_role": "Data Analyst",
            "target_grade": "Middle",
            "target_city_tier": "Tier-1",
            "target_work_mode": "Remote",
            "current_skills": ["Python", "SQL"],
        }
        api_client.export_persona_pdf.return_value = b"%PDF"

        await pdf_report.handle_pdf_report(message, api_client)

        api_client.get_profile.assert_awaited_once_with(42)
        api_client.export_persona_pdf.assert_awaited_once()
        payload = api_client.export_persona_pdf.await_args.args[0]
        assert payload["target_role"] == "Data Analyst"
        assert payload["current_skills"] == ["Python", "SQL"]
        assert message.answer.await_args_list[0].args[0].startswith("Генерирую PDF")
        document_call = message.answer_document.await_args
        assert document_call.kwargs["caption"] == "Ваш персональный отчёт Skillra"
        assert document_call.args[0].filename == "skillra_report_42.pdf"

    asyncio.run(_run())


def test_handle_pdf_report_prompts_for_missing_profile() -> None:
    async def _run() -> None:
        message = AsyncMock()
        message.from_user = SimpleNamespace(id=42, username=None)
        api_client = AsyncMock()
        api_client.get_profile.side_effect = SkillraApiError(
            error_code="PROFILE_NOT_FOUND",
            error_message=None,
            status_code=404,
            request_id="req",
            payload={},
        )

        await pdf_report.handle_pdf_report(message, api_client)

        api_client.export_persona_pdf.assert_not_called()
        assert "Сначала настройте профиль" in message.answer.await_args.args[0]

    asyncio.run(_run())


def test_handle_csv_report_exports_profile_csv() -> None:
    async def _run() -> None:
        message = AsyncMock()
        message.from_user = SimpleNamespace(id=42, username="alice")
        api_client = AsyncMock()
        api_client.get_profile.return_value = {
            "target_role": "Data Analyst",
            "target_grade": "Middle",
            "current_skills": ["Python"],
        }
        api_client.export_persona_csv.return_value = b"skill,share\nPython,0.8\n"

        await pdf_report.handle_csv_report(message, api_client)

        api_client.export_persona_csv.assert_awaited_once()
        document_call = message.answer_document.await_args
        assert document_call.args[0].filename == "skill_gap_42.csv"
        assert document_call.kwargs["caption"] == "CSV skill-gap"

    asyncio.run(_run())


def test_handle_share_report_returns_public_link(monkeypatch) -> None:
    async def _run() -> None:
        message = AsyncMock()
        message.from_user = SimpleNamespace(id=42, username="alice")
        api_client = AsyncMock()
        api_client.get_profile.return_value = {
            "target_role": "Data Analyst",
            "target_grade": "Middle",
            "current_skills": ["Python"],
        }
        api_client.create_persona_share.return_value = {"token": "abc123"}
        monkeypatch.setenv("SKILLRA_PUBLIC_BASE_URL", "https://skillra.ru")

        await pdf_report.handle_share_report(message, api_client)

        api_client.create_persona_share.assert_awaited_once()
        assert message.answer.await_args.args[0] == "Ссылка на skill-gap: https://skillra.ru/share/abc123"

    asyncio.run(_run())
