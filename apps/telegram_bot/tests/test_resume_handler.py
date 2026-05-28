from __future__ import annotations

import asyncio
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock

from telegram_bot.handlers import onboarding


def _callbacks(markup) -> list[str]:
    return [button.callback_data for row in markup.inline_keyboard for button in row]


def test_onboarding_offers_resume_upload() -> None:
    profile = {
        "target_role": "Data Analyst",
        "target_grade": "Middle",
        "target_city_tier": "Tier-1",
        "target_work_mode": "Remote",
        "target_domain": "Fintech",
        "current_skills": ["SQL"],
    }
    callback_message = SimpleNamespace(answer=AsyncMock())
    callback = SimpleNamespace(
        answer=AsyncMock(),
        message=callback_message,
        from_user=SimpleNamespace(id=42, username="alice"),
    )
    state = SimpleNamespace(
        get_data=AsyncMock(return_value=profile),
        update_data=AsyncMock(),
        set_state=AsyncMock(),
    )
    api_client = SimpleNamespace(upsert_profile=AsyncMock(return_value=profile))
    meta_cache = SimpleNamespace()

    asyncio.run(onboarding.confirm_skills(callback, state, api_client, meta_cache))

    state.set_state.assert_awaited_with(onboarding.ProfileOnboarding.upload_resume)
    _, kwargs = callback_message.answer.await_args_list[-1]
    assert onboarding.RESUME_UPLOAD_CALLBACK in _callbacks(kwargs["reply_markup"])
    assert onboarding.RESUME_SKIP_CALLBACK in _callbacks(kwargs["reply_markup"])


def test_resume_upload_updates_profile_skills() -> None:
    pdf_bytes = b"%PDF-1.4"
    document = SimpleNamespace(
        file_id="file-1",
        file_name="resume.pdf",
        mime_type="application/pdf",
        file_size=len(pdf_bytes),
    )
    message = SimpleNamespace(
        document=document,
        from_user=SimpleNamespace(id=42, username="alice"),
        answer=AsyncMock(),
    )
    state = SimpleNamespace(
        get_data=AsyncMock(return_value={"telegram_user_id": 42}),
        clear=AsyncMock(),
    )
    api_client = SimpleNamespace(
        upload_user_resume=AsyncMock(return_value={"extracted_skills": ["Python", "Airflow"]}),
        get_profile=AsyncMock(
            return_value={
                "target_role": "Data Analyst",
                "target_grade": "Middle",
                "target_city_tier": "Tier-1",
                "target_work_mode": "Remote",
                "target_domain": "Fintech",
                "current_skills": ["SQL"],
            }
        ),
        upsert_profile=AsyncMock(return_value={}),
    )
    bot = SimpleNamespace(
        get_file=AsyncMock(return_value=SimpleNamespace(file_path="documents/resume.pdf")),
        download_file=AsyncMock(return_value=BytesIO(pdf_bytes)),
    )

    asyncio.run(onboarding.handle_resume_document(message, state, api_client, bot))

    api_client.upload_user_resume.assert_awaited_once_with(42, pdf_bytes, "resume.pdf")
    saved_payload = api_client.upsert_profile.await_args.args[1]
    assert saved_payload["current_skills"] == ["SQL", "Python", "Airflow"]
    state.clear.assert_awaited_once()
    assert "Найдено навыков" in message.answer.await_args_list[-1].args[0]


def test_resume_too_large_rejected() -> None:
    document = SimpleNamespace(
        file_id="file-1",
        file_name="resume.pdf",
        mime_type="application/pdf",
        file_size=onboarding.RESUME_MAX_BYTES + 1,
    )
    message = SimpleNamespace(document=document, from_user=SimpleNamespace(id=42), answer=AsyncMock())
    state = SimpleNamespace(get_data=AsyncMock(return_value={"telegram_user_id": 42}))
    api_client = SimpleNamespace(upload_user_resume=AsyncMock())
    bot = SimpleNamespace()

    asyncio.run(onboarding.handle_resume_document(message, state, api_client, bot))

    api_client.upload_user_resume.assert_not_awaited()
    message.answer.assert_awaited_once_with("Только PDF до 10 МБ.")


def test_resume_not_pdf_rejected() -> None:
    document = SimpleNamespace(
        file_id="file-1",
        file_name="resume.txt",
        mime_type="text/plain",
        file_size=128,
    )
    message = SimpleNamespace(document=document, from_user=SimpleNamespace(id=42), answer=AsyncMock())
    state = SimpleNamespace(get_data=AsyncMock(return_value={"telegram_user_id": 42}))
    api_client = SimpleNamespace(upload_user_resume=AsyncMock())
    bot = SimpleNamespace()

    asyncio.run(onboarding.handle_resume_document(message, state, api_client, bot))

    api_client.upload_user_resume.assert_not_awaited()
    message.answer.assert_awaited_once_with("Только PDF до 10 МБ.")


def test_resume_command_waits_for_pdf() -> None:
    message = SimpleNamespace(from_user=SimpleNamespace(id=42), answer=AsyncMock())
    state = SimpleNamespace(clear=AsyncMock(), update_data=AsyncMock(), set_state=AsyncMock())

    asyncio.run(onboarding.start_resume_upload(message, state))

    state.clear.assert_awaited_once()
    state.set_state.assert_awaited_with(onboarding.ProfileOnboarding.waiting_resume_file)
    assert "PDF" in message.answer.await_args.args[0]
