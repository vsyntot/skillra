from __future__ import annotations

import argparse
import json
import socket
import time
import uuid
from datetime import datetime, timedelta, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urljoin
from urllib.request import Request, urlopen


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Send a synthetic alert to Alertmanager and verify acceptance.")
    parser.add_argument("--alertmanager-url", default="http://localhost:9093")
    parser.add_argument("--alertname", default="SkillraSmokeAlert")
    parser.add_argument("--timeout", type=float, default=2.0)
    parser.add_argument("--poll-seconds", type=float, default=10.0)
    parser.add_argument("--keep-firing", action="store_true", help="Do not resolve the synthetic alert at the end.")
    return parser.parse_args()


def utc_iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def build_alert(*, alertname: str, run_id: str, resolved: bool = False) -> dict:
    now = datetime.now(timezone.utc)
    alert = {
        "labels": {
            "alertname": alertname,
            "severity": "info",
            "job": "skillra-alert-smoke",
            "instance": socket.gethostname(),
            "skillra_smoke_run_id": run_id,
        },
        "annotations": {
            "summary": "Skillra alert delivery smoke",
            "description": "Synthetic alert created by scripts/smoke_alert_delivery.py.",
        },
        "startsAt": utc_iso(now),
        "generatorURL": "skillra://smoke/alert-delivery",
    }
    if resolved:
        alert["endsAt"] = utc_iso(now)
    else:
        alert["endsAt"] = utc_iso(now + timedelta(minutes=5))
    return alert


def request_json(method: str, url: str, *, payload: object | None = None, timeout: float = 2.0) -> object:
    body = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"

    request = Request(url, data=body, headers=headers, method=method)
    try:
        with urlopen(request, timeout=timeout) as response:
            raw = response.read()
            if not raw:
                return {}
            return json.loads(raw.decode("utf-8"))
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{method} {url} failed with HTTP {exc.code}: {detail}") from exc
    except URLError as exc:
        raise RuntimeError(f"{method} {url} failed: {exc}") from exc


def post_alert(alertmanager_url: str, alert: dict, *, timeout: float) -> None:
    request_json("POST", urljoin(alertmanager_url.rstrip("/") + "/", "api/v2/alerts"), payload=[alert], timeout=timeout)


def list_active_alerts(alertmanager_url: str, *, run_id: str, timeout: float) -> list[dict]:
    query = urlencode(
        {
            "active": "true",
            "silenced": "false",
            "inhibited": "false",
            "filter": f"skillra_smoke_run_id={run_id}",
        }
    )
    payload = request_json(
        "GET",
        urljoin(alertmanager_url.rstrip("/") + "/", f"api/v2/alerts?{query}"),
        timeout=timeout,
    )
    if not isinstance(payload, list):
        raise RuntimeError("Alertmanager active alerts response must be a JSON list")
    return payload


def has_smoke_alert(alerts: list[dict], *, run_id: str) -> bool:
    for alert in alerts:
        labels = alert.get("labels", {}) if isinstance(alert, dict) else {}
        if labels.get("skillra_smoke_run_id") == run_id:
            return True
    return False


def main() -> None:
    args = parse_args()
    run_id = f"smoke-{uuid.uuid4()}"

    firing_alert = build_alert(alertname=args.alertname, run_id=run_id)
    post_alert(args.alertmanager_url, firing_alert, timeout=args.timeout)

    deadline = time.monotonic() + args.poll_seconds
    accepted = False
    while time.monotonic() <= deadline:
        if has_smoke_alert(
            list_active_alerts(args.alertmanager_url, run_id=run_id, timeout=args.timeout), run_id=run_id
        ):
            accepted = True
            break
        time.sleep(1)

    if not args.keep_firing:
        post_alert(
            args.alertmanager_url,
            build_alert(alertname=args.alertname, run_id=run_id, resolved=True),
            timeout=args.timeout,
        )

    if not accepted:
        raise SystemExit(f"Alertmanager did not expose synthetic alert run_id={run_id} within {args.poll_seconds}s")

    print(json.dumps({"status": "ok", "alertname": args.alertname, "run_id": run_id}, ensure_ascii=False))


if __name__ == "__main__":
    main()
