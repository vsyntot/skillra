from __future__ import annotations

from datetime import datetime, timezone
from parser import hh_scraper


def _vacancy_html(*, salary: str | None = None) -> str:
    salary_html = f"<div data-qa='vacancy-salary'>{salary}</div>" if salary else ""
    return f"""
    <html>
      <body>
        <h1 data-qa="vacancy-title">Python developer</h1>
        {salary_html}
        <a data-qa="vacancy-company-name" href="/employer/1">ACME</a>
        <span data-qa="vacancy-experience">Нет опыта</span>
        <div data-qa="vacancy-description">Python, SQL, аналитика данных</div>
      </body>
    </html>
    """


def test_parse_vacancy_page_keeps_salaryless_record_for_all_vacancies_scope() -> None:
    record = hh_scraper.parse_vacancy_page(
        _vacancy_html(),
        "https://hh.ru/vacancy/123",
        area_id=113,
        scraped_at=datetime.now(timezone.utc),
        require_salary=False,
        dataset_scope="all_vacancies",
    )

    assert record is not None
    assert record.salary_disclosed is False
    assert record.salary_mid is None
    assert record.dataset_scope == "all_vacancies"


def test_parse_vacancy_page_skips_salaryless_record_when_salary_required() -> None:
    record = hh_scraper.parse_vacancy_page(
        _vacancy_html(),
        "https://hh.ru/vacancy/123",
        area_id=113,
        scraped_at=datetime.now(timezone.utc),
        require_salary=True,
        dataset_scope="salary_disclosed",
    )

    assert record is None


def test_parse_vacancy_page_marks_disclosed_salary_scope() -> None:
    record = hh_scraper.parse_vacancy_page(
        _vacancy_html(salary="от 100 000 до 150 000 ₽ на руки"),
        "https://hh.ru/vacancy/123",
        area_id=113,
        scraped_at=datetime.now(timezone.utc),
        require_salary=True,
        dataset_scope="salary_disclosed",
    )

    assert record is not None
    assert record.salary_disclosed is True
    assert record.salary_mid == 125000
    assert record.dataset_scope == "salary_disclosed"
