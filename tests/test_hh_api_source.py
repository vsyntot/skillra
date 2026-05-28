from __future__ import annotations

import csv
import json
from parser import hh_api_source
from parser.hh_api_source import HHApiSourceAdapter
from parser.job_source import CollectionRequest
from pathlib import Path


class FakeResponse:
    status_code = 200
    text = "{}"

    def json(self) -> dict[str, object]:
        return {
            "found": 1,
            "pages": 1,
            "page": 0,
            "per_page": 5,
            "items": [
                {
                    "id": "123",
                    "name": "Python Developer",
                    "alternate_url": "https://hh.ru/vacancy/123",
                    "url": "https://api.hh.ru/vacancies/123",
                    "published_at": "2025-12-01T10:15:00+0300",
                    "area": {"id": "1", "name": "Москва"},
                    "employer": {"name": "Acme", "alternate_url": "https://hh.ru/employer/1"},
                    "salary": {"from": 100000, "to": 150000, "currency": "RUR", "gross": True},
                    "experience": {"id": "between1And3", "name": "От 1 года до 3 лет"},
                    "schedule": {"id": "remote", "name": "Удаленная работа"},
                    "employment": {"id": "full", "name": "Полная занятость"},
                }
            ],
        }


class FakeSession:
    def __init__(self) -> None:
        self.requests: list[dict[str, object]] = []
        self.closed = False

    def get(
        self,
        url: str,
        *,
        params: dict[str, object],
        headers: dict[str, str],
        timeout: int,
    ) -> FakeResponse:
        self.requests.append({"url": url, "params": params, "headers": headers, "timeout": timeout})
        return FakeResponse()

    def close(self) -> None:
        self.closed = True


def test_hh_api_adapter_writes_capability_probe_csv(monkeypatch, tmp_path: Path) -> None:
    session = FakeSession()
    monkeypatch.setattr(hh_api_source.requests, "Session", lambda: session)
    monkeypatch.setenv("HH_API_TOKEN", "token")
    output = tmp_path / "sample.csv"
    report = tmp_path / "report.json"

    result = HHApiSourceAdapter().collect(
        CollectionRequest(
            query="python",
            limit=5,
            output_path=output,
            dataset_scope="all_vacancies",
            delay=0,
            max_pages=1,
            area_ids=(113,),
            date_from="2025-12-01T00:00:00",
            date_to="2025-12-01T23:59:59",
            collection_report_path=report,
        )
    )

    assert result.report.source_mode == "hh_api"
    assert result.report.row_count == 1
    assert session.closed is True
    assert session.requests[0]["params"]["date_from"] == "2025-12-01T00:00:00"
    assert session.requests[0]["params"]["per_page"] == 5
    assert session.requests[0]["headers"]["Authorization"] == "Bearer token"

    with output.open(encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert rows[0]["vacancy_id"] == "123"
    assert rows[0]["title"] == "Python Developer"
    assert rows[0]["published_at_iso"] == "2025-12-01"
    assert rows[0]["vacancy_url"] == "https://hh.ru/vacancy/123"
    assert rows[0]["salary_mid"] == "125000.0"

    payload = json.loads(report.read_text(encoding="utf-8"))
    assert payload["source_mode"] == "hh_api"
    assert payload["shard_results"][0]["search_result_count"] == 1
