from __future__ import annotations

from telegram_bot.logging_utils import mask_user_id


def test_mask_user_id_obscures_value() -> None:
    raw_user_id = 123456789

    masked = mask_user_id(raw_user_id)

    assert masked != str(raw_user_id)
    assert len(masked) == 10
    assert masked == mask_user_id(raw_user_id)


def test_mask_user_id_handles_none() -> None:
    assert mask_user_id(None) == "anonymous"
