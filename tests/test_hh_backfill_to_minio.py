from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from scripts import hh_backfill_to_minio as backfill


class FakeResponse:
    def __init__(self, text: str, status_code: int = 200) -> None:
        self.text = text
        self.status_code = status_code


class FakeRecord:
    def __init__(
        self,
        vacancy_id: str,
        title: str = "Python developer",
        published_at_iso: str = "2025-12-01",
    ) -> None:
        self.vacancy_id = vacancy_id
        self.title = title
        self.employer_url = ""
        self.published_at_iso = published_at_iso

    def to_dict(self) -> dict[str, str]:
        return {
            "vacancy_id": self.vacancy_id,
            "title": self.title,
            "published_at_iso": self.published_at_iso,
        }


class FakeSession:
    def __init__(self, search_calls: list[dict[str, object]], link_pages: set[int]) -> None:
        self.search_calls = search_calls
        self.link_pages = link_pages

    def get(
        self,
        url: str,
        *,
        params: dict[str, object],
        headers: dict[str, str],
        timeout: int,
    ) -> FakeResponse:
        self.search_calls.append({"url": url, "params": dict(params), "headers": dict(headers), "timeout": timeout})
        page = int(params["page"])
        exp_filter = params.get("experience")
        return FakeResponse("links" if exp_filter is None and page in self.link_pages else "empty")

    def close(self) -> None:
        return None


class FakeS3Client:
    def __init__(self) -> None:
        self.uploaded_files: list[tuple[str, str, str]] = []
        self.uploaded_objects: list[tuple[str, str, bytes]] = []

    def upload_file(self, source: str, bucket: str, key: str, *args: object, **kwargs: object) -> None:
        self.uploaded_files.append((source, bucket, key))

    def put_object(self, **kwargs: object) -> None:
        self.uploaded_objects.append(
            (
                str(kwargs["Bucket"]),
                str(kwargs["Key"]),
                kwargs["Body"] if isinstance(kwargs["Body"], bytes) else bytes(str(kwargs["Body"]), "utf-8"),
            )
        )


def _write_source_capability_report(
    tmp_path: Path,
    *,
    date_from: str = "2025-12-01",
    date_to: str = "2025-12-01",
    query: str = backfill.hh_scraper.DEFAULT_QUERY,
    areas: list[int] | None = None,
    status: str = "supported",
) -> Path:
    path = tmp_path / "source_capability.json"
    path.write_text(
        backfill.json.dumps(
            {
                "source_mode": "hh_html",
                "capability_status": status,
                "requested_query": query,
                "requested_date_from": date_from,
                "requested_date_to": date_to,
                "areas": areas or list(backfill.hh_scraper.DEFAULT_AREA_IDS),
                "dataset_scope": "all_vacancies",
                "salary_only": False,
                "row_count": 1,
                "date_semantics": {"status": "passed"},
            }
        ),
        encoding="utf-8",
    )
    return path


def test_hh_backfill_streams_day_progress_and_uploads_checkpoints(monkeypatch, tmp_path: Path) -> None:
    fake_client = FakeS3Client()
    search_calls: list[dict[str, object]] = []

    monkeypatch.setattr(backfill.hh_scraper, "build_session", lambda proxy=None: FakeSession(search_calls, {0}))
    monkeypatch.setattr(
        backfill.hh_scraper, "parse_search_page", lambda html: ["https://hh.ru/vacancy/1"] if html == "links" else []
    )
    monkeypatch.setattr(backfill.hh_scraper, "fetch", lambda session, url, headers: "vacancy-html")
    monkeypatch.setattr(backfill.hh_scraper, "parse_vacancy_page", lambda *args, **kwargs: FakeRecord("1"))
    monkeypatch.setattr(backfill.hh_scraper, "apply_employer_info", lambda record, info: None)
    monkeypatch.setattr(backfill.time, "sleep", lambda seconds: None)

    monkeypatch.setattr(backfill, "create_s3_client", lambda env: fake_client)

    config = backfill.BackfillConfig(
        date_from=date(2025, 12, 1),
        date_to=date(2025, 12, 1),
        storage_dir=tmp_path,
        bucket="skillra-raw-hh",
        backfill_id="test-backfill",
        query="python",
        areas=(113,),
        delay=0,
        partial_upload_pages=1,
        retry_delay_seconds=0,
        max_attempts_per_day=1,
        source_capability_report=_write_source_capability_report(tmp_path, query="python"),
    )

    backfill.run_backfill(config)

    assert search_calls[0]["params"]["date_from"] == "2025-12-01T00:00:00"
    assert search_calls[0]["params"]["date_to"] == "2025-12-01T23:59:59"
    assert backfill.count_csv_rows(backfill.snapshot_path(config, date(2025, 12, 1))) == 1
    uploaded_keys = [key for _, _, key in fake_client.uploaded_files]
    assert "backfills/test-backfill/date=2025-12-01/progress.json" in uploaded_keys
    assert "backfills/test-backfill/date=2025-12-01/snapshot.partial.csv" in uploaded_keys
    assert "backfills/test-backfill/date=2025-12-01/snapshot.csv" in uploaded_keys
    assert "backfills/test-backfill/date=2025-12-01/metadata.json" in uploaded_keys
    object_keys = [key for _, key, _ in fake_client.uploaded_objects]
    assert "backfills/test-backfill/state.json" in object_keys
    assert "backfills/test-backfill/manifest.jsonl" in object_keys
    state = backfill.load_or_init_state(config)
    assert state.completed_dates == ["2025-12-01"]
    assert state.current_date is None
    assert state.source_capability_ref
    assert state.source_capability_ref["use_case"] == "historical_collection"


def test_hh_backfill_resumes_from_page_progress(monkeypatch, tmp_path: Path) -> None:
    fake_client = FakeS3Client()
    search_calls: list[dict[str, object]] = []
    day = date(2025, 12, 1)

    config = backfill.BackfillConfig(
        date_from=day,
        date_to=day,
        storage_dir=tmp_path,
        bucket="skillra-raw-hh",
        backfill_id="test-backfill",
        query="python",
        areas=(113,),
        delay=0,
        partial_upload_pages=1,
        retry_delay_seconds=0,
        max_attempts_per_day=1,
        source_capability_report=_write_source_capability_report(tmp_path, query="python"),
    )
    temp = backfill.partial_snapshot_path(config, day)
    backfill.ensure_streaming_snapshot(temp)
    with temp.open("a", encoding="utf-8", newline="") as handle:
        writer = backfill.csv.DictWriter(
            handle, fieldnames=list(backfill.hh_scraper.VacancyRecord.__dataclass_fields__)
        )
        writer.writerow({"vacancy_id": "1", "title": "Existing", "published_at_iso": "2025-12-01"})
    progress = backfill.DayProgress(
        date=day.isoformat(),
        area_index=0,
        experience_index=0,
        page=1,
        rows_written=1,
        pages_completed=1,
        started_at_utc=backfill.utc_now(),
    )
    backfill.atomic_write_json(backfill.progress_file(config, day), progress.__dict__)

    monkeypatch.setattr(backfill.hh_scraper, "build_session", lambda proxy=None: FakeSession(search_calls, {1}))
    monkeypatch.setattr(
        backfill.hh_scraper, "parse_search_page", lambda html: ["https://hh.ru/vacancy/2"] if html == "links" else []
    )
    monkeypatch.setattr(backfill.hh_scraper, "fetch", lambda session, url, headers: "vacancy-html")
    monkeypatch.setattr(backfill.hh_scraper, "parse_vacancy_page", lambda *args, **kwargs: FakeRecord("2"))
    monkeypatch.setattr(backfill.hh_scraper, "apply_employer_info", lambda record, info: None)
    monkeypatch.setattr(backfill.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(backfill, "create_s3_client", lambda env: fake_client)

    backfill.run_backfill(config)

    assert search_calls[0]["params"]["page"] == 1
    snapshot = backfill.snapshot_path(config, day).read_text(encoding="utf-8")
    assert ",Existing" in snapshot
    assert ",Python developer" in snapshot
    assert backfill.count_csv_rows(backfill.snapshot_path(config, day)) == 2


def test_hh_backfill_resumes_completed_date_without_scrape(monkeypatch, tmp_path: Path) -> None:
    scrape_called = False

    def fake_scrape(**kwargs: object) -> list[object]:
        nonlocal scrape_called
        scrape_called = True
        return []

    config = backfill.BackfillConfig(
        date_from=date(2025, 12, 1),
        date_to=date(2025, 12, 1),
        storage_dir=tmp_path,
        bucket="skillra-raw-hh",
        backfill_id="test-backfill",
        dry_run=True,
        source_capability_report=_write_source_capability_report(tmp_path),
    )
    state = backfill.BackfillState(
        backfill_id="test-backfill",
        date_from="2025-12-01",
        date_to="2025-12-01",
        bucket="skillra-raw-hh",
        completed_dates=["2025-12-01"],
    )
    backfill.atomic_write_json(backfill.state_file(config), state.__dict__)
    monkeypatch.setattr(backfill.hh_scraper, "scrape", fake_scrape)

    backfill.run_backfill(config)

    assert scrape_called is False


def test_hh_backfill_quarantines_invalid_historical_date(monkeypatch, tmp_path: Path) -> None:
    fake_client = FakeS3Client()
    search_calls: list[dict[str, object]] = []

    monkeypatch.setattr(backfill.hh_scraper, "build_session", lambda proxy=None: FakeSession(search_calls, {0}))
    monkeypatch.setattr(
        backfill.hh_scraper, "parse_search_page", lambda html: ["https://hh.ru/vacancy/1"] if html == "links" else []
    )
    monkeypatch.setattr(backfill.hh_scraper, "fetch", lambda session, url, headers: "vacancy-html")
    monkeypatch.setattr(
        backfill.hh_scraper,
        "parse_vacancy_page",
        lambda *args, **kwargs: FakeRecord("1", published_at_iso="2026-05-25"),
    )
    monkeypatch.setattr(backfill.hh_scraper, "apply_employer_info", lambda record, info: None)
    monkeypatch.setattr(backfill.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(backfill, "create_s3_client", lambda env: fake_client)

    config = backfill.BackfillConfig(
        date_from=date(2025, 12, 1),
        date_to=date(2025, 12, 1),
        storage_dir=tmp_path,
        bucket="skillra-raw-hh",
        backfill_id="test-backfill",
        query="python",
        areas=(113,),
        delay=0,
        partial_upload_pages=1,
        retry_delay_seconds=0,
        max_attempts_per_day=1,
        source_capability_report=_write_source_capability_report(tmp_path, query="python"),
    )

    with pytest.raises(backfill.DateSemanticsError):
        backfill.run_backfill(config)

    state = backfill.load_or_init_state(config)
    assert state.completed_dates == []
    assert backfill.root_quarantine_path(config).exists()
    object_keys = [key for _, key, _ in fake_client.uploaded_objects]
    assert "backfills/test-backfill/_QUARANTINE.json" in object_keys
    assert "backfills/test-backfill/date=2025-12-01/_QUARANTINE.json" in object_keys


def test_hh_backfill_requires_source_capability_report(tmp_path: Path) -> None:
    config = backfill.BackfillConfig(
        date_from=date(2025, 12, 1),
        date_to=date(2025, 12, 1),
        storage_dir=tmp_path,
        bucket="skillra-raw-hh",
        backfill_id="test-backfill",
        dry_run=True,
    )

    with pytest.raises(SystemExit, match="Source capability report is required"):
        backfill.run_backfill(config)


def test_hh_backfill_rejects_unsupported_source_capability_report(tmp_path: Path) -> None:
    config = backfill.BackfillConfig(
        date_from=date(2025, 12, 1),
        date_to=date(2025, 12, 1),
        storage_dir=tmp_path,
        bucket="skillra-raw-hh",
        backfill_id="test-backfill",
        dry_run=True,
        source_capability_report=_write_source_capability_report(tmp_path, status="unsupported"),
    )

    with pytest.raises(SystemExit, match="does not allow this backfill"):
        backfill.run_backfill(config)
