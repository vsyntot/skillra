import subprocess
import sys
import warnings
from parser.hh_scraper import build_search_params, parse_employer_page
from pathlib import Path


def test_hh_scraper_direct_cli_imports_job_source_contract() -> None:
    repo_root = Path(__file__).resolve().parents[1]

    result = subprocess.run(
        [sys.executable, "parser/hh_scraper.py", "--help"],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    )

    assert "HH.ru" in result.stdout


def test_build_search_params_includes_publication_date_bounds() -> None:
    params = build_search_params(
        query="python",
        area_id=113,
        page=2,
        salary_only=False,
        exp_filter="between1And3",
        date_from="2025-12-01T00:00:00",
        date_to="2025-12-01T23:59:59",
    )

    assert params["text"] == "python"
    assert params["area"] == 113
    assert params["page"] == 2
    assert params["experience"] == "between1And3"
    assert params["date_from"] == "2025-12-01T00:00:00"
    assert params["date_to"] == "2025-12-01T23:59:59"


def test_employer_page_parser_handles_json_escaped_slashes_without_warnings() -> None:
    html = (
        r'<script>{"url":"https:\/\/hh.ru\/employer\/1",'
        r'"employerReviews":{"totalRating":4.7,"reviewsCount":12}}</script>'
    )

    with warnings.catch_warnings():
        warnings.simplefilter("error", DeprecationWarning)
        parsed = parse_employer_page(html)

    assert parsed["employer_rating"] == 4.7
    assert parsed["employer_reviews_count"] == 12
