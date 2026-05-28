from __future__ import annotations

"""HH.ru official API source adapter for controlled source-capability probes."""

import csv
import os
import time
from datetime import datetime, timezone
from parser import hh_scraper
from parser.job_source import (
    CollectionReport,
    CollectionRequest,
    CollectionResult,
    ShardResult,
    compute_sha256,
    write_collection_report,
)
from typing import Any

import requests

API_SEARCH_URL = "https://api.hh.ru/vacancies"
DEFAULT_USER_AGENT = "SkillraDataPlatform/1.0 (admin@skillra.ru)"


class HHApiSourceAdapter:
    """Collect a small controlled vacancy sample through the official HH API.

    This adapter is intentionally scoped to source-capability checks. It writes
    rows in the existing raw-vacancy CSV shape so date semantics and raw gates
    can inspect the same critical fields as the HTML collector.
    """

    source_mode = "hh_api"

    def collect(self, request: CollectionRequest) -> CollectionResult:
        started = datetime.now(timezone.utc)
        monotonic_start = time.monotonic()
        request.output_path.parent.mkdir(parents=True, exist_ok=True)
        records: list[dict[str, Any]] = []
        shard_results: list[ShardResult] = []
        errors: list[str] = []
        seen_ids: set[str] = set()
        session = requests.Session()

        try:
            for area_id in request.area_ids or (113,):
                if len(records) >= request.limit:
                    break
                shard = self._collect_area(session, request, int(area_id), records, seen_ids)
                shard_results.append(shard)
                errors.extend(shard.errors)
        except Exception as exc:
            errors.append(f"{exc.__class__.__name__}: {exc}")
            self._write_rows(request.output_path, records)
            report = self._build_report(
                request=request,
                started=started,
                monotonic_start=monotonic_start,
                records=records,
                shard_results=shard_results,
                errors=errors,
                status="failed",
            )
            write_collection_report(request.collection_report_path, report)
            raise
        finally:
            session.close()

        self._write_rows(request.output_path, records)
        report = self._build_report(
            request=request,
            started=started,
            monotonic_start=monotonic_start,
            records=records,
            shard_results=shard_results,
            errors=errors,
            status="success" if not errors else "warning",
        )
        write_collection_report(request.collection_report_path, report)
        return CollectionResult(records=records, output_path=request.output_path, report=report)

    def _collect_area(
        self,
        session: requests.Session,
        request: CollectionRequest,
        area_id: int,
        records: list[dict[str, Any]],
        seen_ids: set[str],
    ) -> ShardResult:
        page = 0
        pages_succeeded = 0
        pages_requested = 0
        found = 0
        duplicates = 0
        errors: list[str] = []

        while len(records) < request.limit:
            if request.max_pages is not None and page >= request.max_pages:
                break
            per_page = min(100, max(1, request.limit - len(records)))
            params = build_search_params(request=request, area_id=area_id, page=page, per_page=per_page)
            pages_requested += 1
            response = session.get(API_SEARCH_URL, params=params, headers=build_headers(), timeout=20)
            if response.status_code >= 400:
                detail = response.text[:500].replace("\n", " ")
                raise RuntimeError(
                    f"HH API search returned status={response.status_code} area={area_id} page={page}: {detail}"
                )

            payload = response.json()
            items = payload.get("items") if isinstance(payload, dict) else None
            if not isinstance(items, list):
                raise RuntimeError(f"HH API search returned malformed items area={area_id} page={page}")
            found = int(payload.get("found") or found or 0)
            pages_succeeded += 1
            for item in items:
                if not isinstance(item, dict):
                    continue
                vacancy_id = str(item.get("id") or "")
                if not vacancy_id:
                    continue
                if vacancy_id in seen_ids:
                    duplicates += 1
                    continue
                seen_ids.add(vacancy_id)
                records.append(normalize_api_item(item, area_id=area_id, dataset_scope=request.dataset_scope))
                if len(records) >= request.limit:
                    break

            pages = int(payload.get("pages") or 0)
            if not items or (pages and page + 1 >= pages):
                break
            page += 1
            if request.delay > 0:
                time.sleep(request.delay)

        return ShardResult(
            source_mode=self.source_mode,
            area_id=area_id,
            pages_requested=pages_requested,
            pages_succeeded=pages_succeeded,
            search_result_count=found,
            records_collected=len([row for row in records if int(row.get("search_area_id") or 0) == area_id]),
            duplicates_skipped=duplicates,
            errors=errors,
        )

    def _build_report(
        self,
        *,
        request: CollectionRequest,
        started: datetime,
        monotonic_start: float,
        records: list[dict[str, Any]],
        shard_results: list[ShardResult],
        errors: list[str],
        status: str,
    ) -> CollectionReport:
        finished = datetime.now(timezone.utc)
        return CollectionReport(
            source_mode=self.source_mode,
            adapter_name=self.__class__.__name__,
            status=status,
            started_at_utc=started.isoformat(),
            finished_at_utc=finished.isoformat(),
            duration_sec=round(time.monotonic() - monotonic_start, 2),
            requested_limit=request.limit,
            row_count=len(records),
            output_path=str(request.output_path),
            sha256=compute_sha256(request.output_path) if request.output_path.exists() else None,
            dataset_scope=request.dataset_scope,
            salary_only=request.salary_only,
            shard_results=shard_results,
            errors=errors,
        )

    @staticmethod
    def _write_rows(path: Any, records: list[dict[str, Any]]) -> None:
        fieldnames = list(hh_scraper.VacancyRecord.__dataclass_fields__)
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(records)


def build_headers() -> dict[str, str]:
    headers = {
        "Accept": "application/json",
        "User-Agent": os.getenv("HH_API_USER_AGENT", DEFAULT_USER_AGENT),
    }
    token = os.getenv("HH_API_TOKEN") or os.getenv("SKILLRA_HH_API_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def build_search_params(*, request: CollectionRequest, area_id: int, page: int, per_page: int) -> dict[str, Any]:
    params: dict[str, Any] = {
        "text": request.query,
        "area": area_id,
        "page": page,
        "per_page": per_page,
        "order_by": "publication_time",
    }
    if request.salary_only:
        params["label"] = "with_salary"
    if request.date_from:
        params["date_from"] = request.date_from
    if request.date_to:
        params["date_to"] = request.date_to
    return params


def normalize_api_item(item: dict[str, Any], *, area_id: int, dataset_scope: str) -> dict[str, Any]:
    salary = item.get("salary") if isinstance(item.get("salary"), dict) else {}
    employer = item.get("employer") if isinstance(item.get("employer"), dict) else {}
    area = item.get("area") if isinstance(item.get("area"), dict) else {}
    experience = item.get("experience") if isinstance(item.get("experience"), dict) else {}
    schedule = item.get("schedule") if isinstance(item.get("schedule"), dict) else {}
    employment = item.get("employment") if isinstance(item.get("employment"), dict) else {}
    published_at = str(item.get("published_at") or "")
    salary_from = salary.get("from")
    salary_to = salary.get("to")
    salary_mid = _salary_mid(salary_from, salary_to)
    row = {field: None for field in hh_scraper.VacancyRecord.__dataclass_fields__}
    row.update(
        {
            "vacancy_id": str(item.get("id") or ""),
            "title": str(item.get("name") or ""),
            "company": str(employer.get("name") or ""),
            "salary_from": salary_from,
            "salary_to": salary_to,
            "currency": salary.get("currency"),
            "salary_gross": salary.get("gross"),
            "salary_mid": salary_mid,
            "salary_range_width": _salary_width(salary_from, salary_to),
            "salary_is_exact": salary_mid is not None and (salary_from is None or salary_to is None),
            "city": str(area.get("name") or ""),
            "address": "",
            "has_metro": False,
            "metro_primary": "",
            "metro_count": 0,
            "address_has_district": False,
            "search_area_id": area_id,
            "experience": str(experience.get("name") or experience.get("id") or ""),
            "exp_is_no_experience": experience.get("id") == "noExperience",
            "employment_type": str(employment.get("name") or employment.get("id") or ""),
            "schedule": str(schedule.get("name") or schedule.get("id") or ""),
            "work_format_raw": "",
            "work_format": "",
            "is_remote": schedule.get("id") == "remote",
            "is_hybrid": False,
            "description": "",
            "description_len_chars": 0,
            "description_len_words": 0,
            "description_bullets_count": 0,
            "description_paragraphs_count": 0,
            "requirements_count": 0,
            "responsibilities_count": 0,
            "optional_skills_count": 0,
            "must_have_skills_count": 0,
            "skills": "",
            "skills_count": 0,
            "published_at_raw": published_at,
            "published_at_iso": published_at[:10] or None,
            "scraped_at_utc": datetime.now(timezone.utc).isoformat(),
            "vacancy_code": "",
            "grade": "unknown",
            "vacancy_url": str(item.get("alternate_url") or item.get("url") or ""),
            "employer_url": str(employer.get("alternate_url") or employer.get("url") or ""),
            "dataset_scope": dataset_scope,
            "salary_disclosed": salary_from is not None or salary_to is not None,
        }
    )
    for field in hh_scraper.VacancyRecord.__dataclass_fields__:
        if field.startswith(("role_", "has_", "skill_", "benefit_", "soft_", "domain_")) and row[field] is None:
            row[field] = False
    return row


def _salary_mid(salary_from: Any, salary_to: Any) -> float | None:
    if salary_from is not None and salary_to is not None:
        return (float(salary_from) + float(salary_to)) / 2
    if salary_from is not None:
        return float(salary_from)
    if salary_to is not None:
        return float(salary_to)
    return None


def _salary_width(salary_from: Any, salary_to: Any) -> int | None:
    if salary_from is None or salary_to is None:
        return None
    return int(salary_to) - int(salary_from)
