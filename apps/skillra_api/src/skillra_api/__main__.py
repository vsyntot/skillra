"""Entry point for running the Skillra API module."""

from __future__ import annotations

import uvicorn
from dotenv import load_dotenv

from .config import get_settings
from .main import create_app


def main() -> None:
    load_dotenv(override=False)
    settings = get_settings()
    app = create_app(settings)
    uvicorn.run(app, host=settings.api_host, port=settings.api_port, log_level=settings.log_level.lower())


if __name__ == "__main__":
    main()
