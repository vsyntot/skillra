import asyncio
from types import SimpleNamespace

from telegram_bot.handlers import analytics


class DummyMessage:
    def __init__(self) -> None:
        self.answers: list[str] = []
        self.from_user = SimpleNamespace(id=42, username="alice")

    async def answer(self, text: str, **_: object) -> None:
        self.answers.append(text)


def test_parse_analyze_args_supports_role_with_spaces() -> None:
    parsed = analytics._parse_analyze_args("/analyze role=Data Engineer grade=Middle")

    assert parsed == {"role": "Data Engineer", "grade": "Middle"}


def test_format_market_summary_contains_core_metrics() -> None:
    profile = {
        "target_role": "data",
        "target_grade": "Senior",
        "target_city_tier": "Moscow",
        "target_work_mode": "Remote",
    }
    summary = {
        "vacancy_count": 42,
        "sample_size": 42,
        "salary_sample_size": 21,
        "salary_coverage_share": 0.5,
        "confidence": "medium",
        "salary_median": 120_000.0,
        "salary_q25": 110_000.0,
        "salary_q75": 130_000.0,
        "remote_share": 0.6,
        "junior_friendly_share": 0.2,
        "median_tech_stack_size": 5.0,
        "top_skills": ["Python", "SQL", "Machine Learning", "Docker", "Git", "Extra"],
        "warnings": ["Test warning"],
    }

    text = analytics.format_market_summary(profile, summary)

    assert "Карта рынка" in text
    assert "42" in text
    assert "120 000 ₽" in text
    assert "60%" in text
    assert "среднее" in text
    assert "50%" in text
    assert "21/42" in text
    assert "Топ навыков сегмента" in text
    assert "Python" in text
    assert "⚠️" in text


def test_format_salary_handles_none_and_spacing() -> None:
    assert analytics._format_salary(None) == "—"
    assert analytics._format_salary(150000) == "150 000 ₽"
    assert analytics._format_salary(9876543.21) == "9 876 543 ₽"


def test_format_skill_gap_report_lists_recommendations() -> None:
    analysis = {
        "market_summary": {
            "vacancy_count": 3,
            "sample_size": 3,
            "salary_sample_size": 1,
            "salary_coverage_share": 1 / 3,
            "confidence": "low",
            "remote_share": 0.5,
        },
        "recommended_skills": ["Python", "SQL"],
        "top_skill_demand": [
            {"skill_name": "Python", "market_share": 0.7},
            {"skill_name": "SQL", "market_share": 0.5},
        ],
        "skill_gap": [
            {
                "skill_name": "Airflow",
                "market_share": 0.3,
                "persona_has": False,
                "gap": True,
            }
        ],
        "warnings": ["Data sample is small"],
    }

    text = analytics.format_skill_gap_report(analysis)

    assert "Skill-gap" in text
    assert "Python" in text
    assert "Airflow" in text
    assert "50%" in text
    assert "низкое" in text
    assert "33%" in text
    assert "⚠️" in text


def test_format_trends_report_lists_market_and_career_graph() -> None:
    profile = {
        "target_role": "Data Analyst",
        "target_grade": "Middle",
        "target_city_tier": "Moscow",
        "target_work_mode": "Remote",
    }

    text = analytics.format_trends_report(
        profile,
        {
            "data": [
                {"week_start": "2026-05-04", "value": 200_000},
                {"week_start": "2026-05-11", "value": 240_000},
            ]
        },
        {
            "data": [
                {"week_start": "2026-05-04", "value": 10},
                {"week_start": "2026-05-11", "value": 15},
            ]
        },
        [{"skill": "Python", "data": [{"value": 6}, {"value": 9}]}],
        {
            "transitions": [
                {
                    "from_grade": "Middle",
                    "to_grade": "Senior",
                    "skills_to_add": ["Airflow", "A/B tests"],
                    "salary_delta_pct": 18,
                    "demand_trend": "growing",
                }
            ]
        },
    )

    assert "Тренды рынка" in text
    assert "240 000 ₽" in text
    assert "+40 000 ₽" in text
    assert "Вакансии" in text
    assert "Python" in text
    assert "Middle → Senior" in text
    assert "растёт" in text
    assert "Airflow" in text


def test_format_trends_report_blocks_not_eligible_trend_claims() -> None:
    profile = {
        "target_role": "Data Analyst",
        "target_grade": "Middle",
    }

    text = analytics.format_trends_report(
        profile,
        {
            "claim_status": "blocked",
            "warnings": ["Историческая динамика сейчас заблокирована: gates not passed."],
            "data": [],
        },
        {"claim_status": "blocked", "data": []},
        [],
        {"transitions": [{"from_grade": "Middle", "to_grade": "Senior"}]},
    )

    assert "Историческая динамика сейчас заблокирована" in text
    assert "/market" in text
    assert "Middle → Senior" not in text


def test_handle_trends_uses_profile_filters() -> None:
    async def _run() -> None:
        message = DummyMessage()
        calls: list[tuple[str, object]] = []

        class DummyClient:
            async def get_profile(self, user_id: int) -> dict[str, object]:
                assert user_id == 42
                return {
                    "target_role": "Data Analyst",
                    "target_grade": "Middle",
                    "target_city_tier": "Moscow",
                    "target_country": "Россия",
                    "target_region": "Москва",
                    "target_city": "Москва",
                    "target_geo_scope": "local",
                    "target_work_mode": "Remote",
                    "target_domain": "Fintech",
                }

            async def salary_trend(self, role: str, grade: str) -> dict[str, object]:
                calls.append(("salary", (role, grade)))
                return {"data": [{"value": 200_000}, {"value": 210_000}]}

            async def vacancy_count_trend(self, role: str, *, grade: str) -> dict[str, object]:
                calls.append(("vacancy", (role, grade)))
                return {"data": [{"value": 10}, {"value": 12}]}

            async def market_segment_summary(self, filters: dict[str, object]) -> dict[str, object]:
                calls.append(("summary", filters))
                return {"top_skills": ["Python"]}

            async def career_graph(self, role: str) -> dict[str, object]:
                calls.append(("graph", role))
                return {"transitions": []}

            async def skill_demand_trend(self, skill: str, **kwargs: object) -> dict[str, object]:
                calls.append(("skill", {"skill": skill, **kwargs}))
                return {"skill": skill, "data": [{"value": 4}, {"value": 5}]}

        await analytics.handle_trends(message, DummyClient(), SimpleNamespace())

        assert message.answers
        assert "Тренды рынка" in message.answers[-1]
        assert ("salary", ("Data Analyst", "Middle")) in calls
        assert (
            "summary",
            {
                "role": "Data Analyst",
                "grade": "Middle",
                "city_tier": "Moscow",
                "country": "Россия",
                "region": "Москва",
                "city": "Москва",
                "geo_scope": "local",
                "work_mode": "Remote",
                "domain": "Fintech",
            },
        ) in calls
        assert ("skill", {"skill": "Python", "role": "Data Analyst", "grade": "Middle"}) in calls

    asyncio.run(_run())


def test_build_market_filters_normalizes_profile() -> None:
    filters = analytics.build_market_filters(
        {
            "target_role": "analyst",
            "target_grade": "Junior",
            "target_city_tier": "SPb",
            "target_country": "Россия",
            "target_region": "Санкт-Петербург",
            "target_city": "Санкт-Петербург",
            "target_geo_scope": "local",
            "target_work_mode": "Hybrid",
            "target_domain": "BI",
        }
    )

    assert filters["grade"] == "Junior"
    assert filters["city_tier"] == "SPb"
    assert filters["country"] == "Россия"
    assert filters["region"] == "Санкт-Петербург"
    assert filters["city"] == "Санкт-Петербург"
    assert filters["geo_scope"] == "local"
    assert filters["work_mode"] == "Hybrid"
    assert filters["domain"] == "BI"


def test_build_persona_payload_keeps_constraints() -> None:
    profile = {
        "target_role": "analyst",
        "target_grade": "Junior",
        "target_city_tier": "Moscow",
        "target_country": "Россия",
        "target_region": "Москва",
        "target_city": "Москва",
        "target_geo_scope": "local",
        "target_work_mode": "Office",
        "target_domain": "Analytics",
        "current_skills": ["Python"],
    }

    payload = analytics.build_persona_payload(profile, username="alice")

    assert payload["name"] == "alice"
    assert payload["target_grade"] == "Junior"
    assert payload["target_country"] == "Россия"
    assert payload["target_region"] == "Москва"
    assert payload["target_city"] == "Москва"
    assert payload["target_geo_scope"] == "local"
    assert payload["constraints"]["domain"] == "Analytics"
