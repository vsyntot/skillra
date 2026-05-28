from __future__ import annotations

import argparse
import json
import os
import uuid
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen


class TelegramSmokeFailure(RuntimeError):
    pass


def normalize_username(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip().removeprefix("@").lower()
    return normalized or None


def validate_get_me(
    payload: dict,
    *,
    expected_username: str | None,
    forbidden_username: str | None,
) -> dict:
    if payload.get("ok") is not True:
        raise TelegramSmokeFailure(f"Telegram getMe returned ok={payload.get('ok')!r}")
    result = payload.get("result")
    if not isinstance(result, dict):
        raise TelegramSmokeFailure("Telegram getMe result must be an object")
    if result.get("is_bot") is not True:
        raise TelegramSmokeFailure("Telegram getMe result is not a bot account")

    actual_username = normalize_username(result.get("username"))
    expected = normalize_username(expected_username)
    forbidden = normalize_username(forbidden_username)
    if expected and actual_username != expected:
        raise TelegramSmokeFailure(
            f"Telegram bot username mismatch: expected @{expected}, got @{actual_username or '<missing>'}"
        )
    if forbidden and actual_username == forbidden:
        raise TelegramSmokeFailure(f"Telegram bot username @{actual_username} is forbidden for this contour")
    return result


def validate_webhook_info(payload: dict, *, expected_url: str | None) -> dict:
    if payload.get("ok") is not True:
        raise TelegramSmokeFailure(f"Telegram getWebhookInfo returned ok={payload.get('ok')!r}")
    result = payload.get("result")
    if not isinstance(result, dict):
        raise TelegramSmokeFailure("Telegram getWebhookInfo result must be an object")

    webhook_url = result.get("url")
    if expected_url and webhook_url != expected_url:
        raise TelegramSmokeFailure(f"Telegram webhook URL mismatch: expected {expected_url!r}, got {webhook_url!r}")
    return result


def _hostname(value: str | None) -> str | None:
    if not value:
        return None
    return (urlparse(value).hostname or "").lower() or None


def validate_contour(
    *,
    expected_contour: str | None,
    bot_username: str | None,
    webhook_url: str | None,
    public_health_url: str | None,
) -> None:
    contour = (expected_contour or "").strip().lower()
    if not contour:
        return
    if contour not in {"local", "staging", "prod"}:
        raise TelegramSmokeFailure("--expected-contour must be one of: local, staging, prod")

    normalized_username = normalize_username(bot_username)
    if contour == "staging":
        if normalized_username == "skillra_bot":
            raise TelegramSmokeFailure("@skillra_bot is forbidden for staging Telegram smoke")
        webhook_host = _hostname(webhook_url)
        if webhook_host and webhook_host != "tg.staging.skillra.ru":
            raise TelegramSmokeFailure(f"staging webhook host must be tg.staging.skillra.ru, got {webhook_host}")
        health_host = _hostname(public_health_url)
        if health_host and health_host != "tg.staging.skillra.ru":
            raise TelegramSmokeFailure(f"staging public health host must be tg.staging.skillra.ru, got {health_host}")
    elif contour == "prod":
        webhook_host = _hostname(webhook_url)
        if webhook_host and webhook_host != "tg.skillra.ru":
            raise TelegramSmokeFailure(f"prod webhook host must be tg.skillra.ru, got {webhook_host}")
        health_host = _hostname(public_health_url)
        if health_host and health_host != "tg.skillra.ru":
            raise TelegramSmokeFailure(f"prod public health host must be tg.skillra.ru, got {health_host}")


def request_json(method: str, url: str, *, payload: dict | None = None, timeout: float = 5.0) -> dict:
    body = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"

    request = Request(url, data=body, headers=headers, method=method)
    try:
        with urlopen(request, timeout=timeout) as response:
            raw = response.read()
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise TelegramSmokeFailure(f"{method} {url} failed with HTTP {exc.code}: {detail}") from exc
    except URLError as exc:
        raise TelegramSmokeFailure(f"{method} {url} failed: {exc}") from exc

    try:
        payload_obj = json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise TelegramSmokeFailure(f"{method} {url} returned non-JSON response") from exc
    if not isinstance(payload_obj, dict):
        raise TelegramSmokeFailure(f"{method} {url} returned non-object JSON")
    return payload_obj


def check_url(url: str, *, timeout: float) -> None:
    request = Request(url, headers={"Accept": "*/*"}, method="GET")
    try:
        with urlopen(request, timeout=timeout):
            return
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise TelegramSmokeFailure(f"GET {url} failed with HTTP {exc.code}: {detail}") from exc
    except URLError as exc:
        raise TelegramSmokeFailure(f"GET {url} failed: {exc}") from exc


def telegram_method_url(bot_api_base_url: str, token: str, method: str) -> str:
    return f"{bot_api_base_url.rstrip('/')}/bot{token}/{method}"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Smoke-check a dedicated Telegram bot contour.")
    parser.add_argument("--token", default=os.getenv("TELEGRAM_BOT_TOKEN"), help="Telegram bot token.")
    parser.add_argument(
        "--expected-username",
        default=os.getenv("TELEGRAM_BOT_USERNAME"),
        help="Expected bot username for this contour.",
    )
    parser.add_argument(
        "--forbid-username",
        default=os.getenv("TELEGRAM_PROD_BOT_USERNAME", "skillra_bot"),
        help="Username that must not be used by this contour.",
    )
    parser.add_argument(
        "--bot-api-base-url",
        default=os.getenv("TELEGRAM_BOT_API_BASE_URL", "https://api.telegram.org"),
    )
    parser.add_argument(
        "--webhook-url",
        default=os.getenv("TELEGRAM_WEBHOOK_URL"),
        help="Expected webhook URL. When omitted, webhook URL is not asserted.",
    )
    parser.add_argument(
        "--public-health-url",
        default=os.getenv("TELEGRAM_PUBLIC_HEALTH_URL"),
        help="Optional public bot health URL to check.",
    )
    parser.add_argument(
        "--send-message-chat-id",
        default=os.getenv("TELEGRAM_SMOKE_CHAT_ID"),
        help="Optional chat id for an explicit sendMessage smoke.",
    )
    parser.add_argument(
        "--expected-contour",
        default=os.getenv("SKILLRA_EXPECTED_RUNTIME_ENV"),
        help="Optional contour guard: local, staging, or prod.",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=None,
        help="Optional JSON report path for acceptance evidence.",
    )
    parser.add_argument("--timeout", type=float, default=5.0)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if not args.token:
        raise SystemExit("TELEGRAM_BOT_TOKEN is required")

    get_me = request_json(
        "GET",
        telegram_method_url(args.bot_api_base_url, args.token, "getMe"),
        timeout=args.timeout,
    )
    bot = validate_get_me(
        get_me,
        expected_username=args.expected_username,
        forbidden_username=args.forbid_username,
    )

    webhook_info = request_json(
        "GET",
        telegram_method_url(args.bot_api_base_url, args.token, "getWebhookInfo"),
        timeout=args.timeout,
    )
    webhook = validate_webhook_info(webhook_info, expected_url=args.webhook_url)
    validate_contour(
        expected_contour=args.expected_contour,
        bot_username=bot.get("username"),
        webhook_url=webhook.get("url") or args.webhook_url,
        public_health_url=args.public_health_url,
    )

    if args.public_health_url:
        check_url(args.public_health_url, timeout=args.timeout)

    sent_message = False
    if args.send_message_chat_id:
        text = f"Skillra staging Telegram smoke {uuid.uuid4()}"
        query = urlencode(
            {
                "chat_id": args.send_message_chat_id,
                "text": text,
                "disable_notification": "true",
            }
        )
        request_json(
            "POST",
            f"{telegram_method_url(args.bot_api_base_url, args.token, 'sendMessage')}?{query}",
            timeout=args.timeout,
        )
        sent_message = True

    report = {
        "status": "ok",
        "contour": args.expected_contour,
        "username": bot.get("username"),
        "webhook_url": webhook.get("url"),
        "health_checked": bool(args.public_health_url),
        "message_sent": sent_message,
    }
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
