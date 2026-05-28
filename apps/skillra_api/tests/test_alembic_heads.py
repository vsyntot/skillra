from __future__ import annotations

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory


def test_alembic_has_single_head_revision() -> None:
    app_dir = Path(__file__).resolve().parents[1]
    config = Config(str(app_dir / "alembic.ini"))
    config.set_main_option("script_location", str(app_dir / "alembic"))

    heads = ScriptDirectory.from_config(config).get_heads()

    assert heads == ["6a708092a0b1"]
