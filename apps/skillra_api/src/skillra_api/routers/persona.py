import asyncio
import csv
import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

import pandas as pd
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse
from reportlab.lib import colors  # type: ignore[import-untyped]
from reportlab.lib.pagesizes import A4  # type: ignore[import-untyped]
from reportlab.lib.styles import getSampleStyleSheet  # type: ignore[import-untyped]
from reportlab.lib.units import cm  # type: ignore[import-untyped]
from reportlab.platypus import (  # type: ignore[import-untyped]
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from skillra_api.config import Settings, get_settings
from skillra_api.datastore import DataStore, DataUnavailableError
from skillra_api.deps import get_datastore_dependency, get_settings_dependency
from skillra_api.deps.auth import require_user_or_service_token
from skillra_api.limiter import limiter
from skillra_api.metrics import PERSONA_ANALYSES_TOTAL
from skillra_api.schemas import CareerTrajectoryOut, PersonaAnalysisResponse, PersonaProfile
from skillra_api.services.analytics import (
    _prepare_persona,
    compute_persona_analysis,
)
from skillra_api.services.responses import data_unavailable_error
from skillra_api.services.share_service import create_share, get_share
from skillra_pda.personas import Persona, analyze_persona, plot_persona_skill_gap

router = APIRouter(prefix="/v1", dependencies=[Depends(require_user_or_service_token)], tags=["persona"])
public_router = APIRouter(prefix="/v1", tags=["persona"])
GRADE_ORDER = ["junior", "jun", "middle", "senior", "lead", "principal"]
GRADE_RANK = {grade: index for index, grade in enumerate(GRADE_ORDER)}


def _render_skill_gap_chart(features_df: pd.DataFrame, persona: Persona) -> bytes:
    """Run persona analysis and render chart to bytes (CPU-bound, runs in thread pool)."""

    analysis = analyze_persona(features_df, persona)
    gap_df = analysis.get("skill_gap")
    with TemporaryDirectory() as tmpdir:
        image_path = plot_persona_skill_gap(gap_df, persona, output_dir=Path(tmpdir))
        return image_path.read_bytes()


def _format_optional_number(value: object, suffix: str = "") -> str:
    if value is None or pd.isna(value):
        return "н/д"
    return f"{int(float(value)):,}{suffix}"


def _format_optional_percent(value: object) -> str:
    if value is None or pd.isna(value):
        return "н/д"
    return f"{float(value) * 100:.0f}%"


def _analysis_payload(analysis: PersonaAnalysisResponse) -> dict[str, Any]:
    return analysis.model_dump(mode="json")


def _trust_metadata(analysis: dict[str, Any]) -> dict[str, Any]:
    market_summary = analysis.get("market_summary") or {}
    return {
        "dataset_run_id": analysis.get("dataset_run_id") or market_summary.get("dataset_run_id"),
        "generated_at": analysis.get("generated_at") or market_summary.get("generated_at"),
        "generated_at_utc": analysis.get("generated_at_utc") or market_summary.get("generated_at_utc"),
        "freshness": analysis.get("freshness") or market_summary.get("freshness"),
        "sample_size": analysis.get("sample_size") or market_summary.get("sample_size"),
        "confidence": analysis.get("confidence") or market_summary.get("confidence"),
        "salary_coverage_share": market_summary.get("salary_coverage_share"),
    }


def _trust_headers(metadata: dict[str, Any]) -> dict[str, str]:
    header_map = {
        "dataset_run_id": "X-Skillra-Dataset-Run-Id",
        "generated_at": "X-Skillra-Generated-At",
        "generated_at_utc": "X-Skillra-Generated-At-Utc",
        "freshness": "X-Skillra-Freshness",
        "sample_size": "X-Skillra-Sample-Size",
        "confidence": "X-Skillra-Confidence",
        "salary_coverage_share": "X-Skillra-Salary-Coverage-Share",
    }
    return {header: str(metadata[key]) for key, header in header_map.items() if metadata.get(key) is not None}


def _csv_metadata_value(value: Any) -> Any:
    return "" if value is None else value


@router.post(
    "/persona/analyze",
    response_model=PersonaAnalysisResponse,
    response_class=JSONResponse,
)
@limiter.limit(get_settings().rate_limit_persona)
async def persona_analyze(
    request: Request,  # noqa: ARG001
    profile: PersonaProfile,
    datastore: DataStore = Depends(get_datastore_dependency),
    settings: Settings = Depends(get_settings_dependency),
) -> PersonaAnalysisResponse | JSONResponse:
    """Analyze persona market fit and skill gaps."""

    result = await compute_persona_analysis(datastore, profile, min_market_n=settings.min_market_n)
    if not isinstance(result, JSONResponse):
        PERSONA_ANALYSES_TOTAL.inc()
    return result


@router.get("/persona/career-trajectory", response_model=CareerTrajectoryOut, response_class=JSONResponse)
async def career_trajectory(
    role: str,
    grade: str,
    skills: str | None = None,
    datastore: DataStore = Depends(get_datastore_dependency),
) -> CareerTrajectoryOut | JSONResponse:
    """Return recommended next career step for a role/grade."""

    if not datastore.is_ready:
        return data_unavailable_error(datastore)
    features_df = datastore.get_features_df()
    user_skills = [skill.strip() for skill in (skills or "").split(",") if skill.strip()]
    recommendation = _recommend_next_step(role, grade, user_skills, features_df, datastore.get_snapshot_history_df())
    return CareerTrajectoryOut(**recommendation)


def _recommend_next_step(
    role: str,
    grade: str,
    user_skills: list[str],
    features_df: pd.DataFrame,
    history_df: pd.DataFrame | None = None,
) -> dict[str, Any]:
    try:
        from skillra_pda.career_path import recommend_next_step  # type: ignore[import-not-found]

        return recommend_next_step(role, grade, user_skills, features_df, history_df=history_df)
    except Exception:  # noqa: BLE001
        return _fallback_next_step(role, grade, user_skills, features_df)


def _fallback_next_step(role: str, grade: str, user_skills: list[str], features_df: pd.DataFrame) -> dict[str, Any]:
    grade_col = "grade_final" if "grade_final" in features_df.columns else "grade"
    base: dict[str, Any] = {
        "current_role": role,
        "current_grade": grade,
        "next_grade": grade,
        "salary_current_p50": None,
        "salary_next_p50": None,
        "salary_delta_pct": None,
        "skills_to_add": [],
        "weeks_trend": 12,
    }
    if features_df.empty or "primary_role" not in features_df.columns or grade_col not in features_df.columns:
        return base

    role_df = features_df[features_df["primary_role"] == role]
    ordered_grades = sorted(role_df[grade_col].dropna().unique(), key=_grade_sort_key)
    grade_lower = grade.lower()
    current_index = next((idx for idx, item in enumerate(ordered_grades) if str(item).lower() == grade_lower), None)
    if current_index is None or current_index + 1 >= len(ordered_grades):
        return base

    next_grade = str(ordered_grades[current_index + 1])
    current_df = role_df[role_df[grade_col].astype(str).str.lower() == grade_lower]
    next_df = role_df[role_df[grade_col] == ordered_grades[current_index + 1]]
    current_salary = _salary_p50(current_df)
    next_salary = _salary_p50(next_df)
    user_skill_set = {skill.lower() for skill in user_skills}
    current_skill_set = {skill.lower() for skill in _top_skills(current_df)}
    skills_to_add = [
        skill
        for skill in _top_skills(next_df)
        if skill.lower() not in user_skill_set and skill.lower() not in current_skill_set
    ][:5]
    return {
        **base,
        "next_grade": next_grade,
        "salary_current_p50": current_salary,
        "salary_next_p50": next_salary,
        "salary_delta_pct": _salary_delta_pct(current_salary, next_salary),
        "skills_to_add": skills_to_add,
    }


def _top_skills(df: pd.DataFrame) -> list[str]:
    skill_cols = [col for col in df.columns if col.startswith("skill_") or col.startswith("has_")]
    if skill_cols:
        means = df[skill_cols].fillna(False).astype(bool).mean().sort_values(ascending=False)
        return [col.removeprefix("skill_").removeprefix("has_") for col, value in means.items() if value > 0][:10]
    if "top_skills" in df.columns and not df["top_skills"].dropna().empty:
        return _skill_list(df["top_skills"].dropna().iloc[0])
    return []


def _skill_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value]
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return [item.strip() for item in value.split(",") if item.strip()]
        if isinstance(parsed, list):
            return [str(item) for item in parsed]
    return []


def _salary_p50(df: pd.DataFrame) -> float | None:
    for column in ("salary_mid_rub_capped", "salary_mid_rub", "salary_mid", "salary_median"):
        if column in df.columns and df[column].notna().any():
            return float(df[column].median())
    return None


def _salary_delta_pct(current: float | None, next_value: float | None) -> float | None:
    if current in (None, 0) or next_value is None:
        return None
    return round(((next_value - current) / current) * 100, 2)


def _grade_sort_key(grade: Any) -> tuple[int, str]:
    normalized = str(grade).lower()
    return (GRADE_RANK.get(normalized, 999), normalized)


@router.post(
    "/persona/export-csv",
    response_model=None,
    response_class=StreamingResponse,
)
async def persona_export_csv(
    profile: PersonaProfile,
    datastore: DataStore = Depends(get_datastore_dependency),
    settings: Settings = Depends(get_settings_dependency),
) -> StreamingResponse | JSONResponse:
    """Export skill gap analysis results as CSV (Sprint-008 TASK-06)."""

    if not datastore.is_ready:
        return data_unavailable_error(datastore)

    analysis_result = await compute_persona_analysis(datastore, profile, min_market_n=settings.min_market_n)
    if isinstance(analysis_result, JSONResponse):
        return analysis_result
    analysis = _analysis_payload(analysis_result)
    trust = _trust_metadata(analysis)

    def _generate_csv() -> str:
        skill_gap = analysis.get("skill_gap") or []
        output = io.StringIO()
        fieldnames = [
            "dataset_run_id",
            "generated_at_utc",
            "freshness",
            "sample_size",
            "confidence",
            "salary_coverage_share",
            "skill_name",
            "market_share",
            "persona_has",
            "gap",
        ]
        writer = csv.DictWriter(output, fieldnames=fieldnames)
        writer.writeheader()
        for row in skill_gap:
            writer.writerow(
                {
                    "dataset_run_id": _csv_metadata_value(trust.get("dataset_run_id")),
                    "generated_at_utc": _csv_metadata_value(trust.get("generated_at_utc")),
                    "freshness": _csv_metadata_value(trust.get("freshness")),
                    "sample_size": _csv_metadata_value(trust.get("sample_size")),
                    "confidence": _csv_metadata_value(trust.get("confidence")),
                    "salary_coverage_share": _csv_metadata_value(trust.get("salary_coverage_share")),
                    "skill_name": row.get("skill_name", ""),
                    "market_share": row.get("market_share", 0),
                    "persona_has": row.get("persona_has", False),
                    "gap": row.get("gap", False),
                }
            )
        return output.getvalue()

    csv_content = await asyncio.to_thread(_generate_csv)

    return StreamingResponse(
        io.StringIO(csv_content),
        media_type="text/csv",
        headers={
            "Content-Disposition": "attachment; filename=skill_gap.csv",
            **_trust_headers(trust),
        },
    )


@router.post(
    "/persona/skill-gap-chart",
    response_class=Response,
)
async def persona_skill_gap_chart(
    profile: PersonaProfile,
    datastore: DataStore = Depends(get_datastore_dependency),
    settings: Settings = Depends(get_settings_dependency),
) -> Response:
    """Render a skill-gap chart for the provided persona."""

    if not datastore.is_ready:
        return data_unavailable_error(datastore)

    try:
        features_df = datastore.get_features_df()
    except DataUnavailableError:
        return data_unavailable_error(datastore)

    persona, error_response, _ = _prepare_persona(profile, features_df, min_market_n=settings.min_market_n)
    if error_response:
        return error_response
    assert persona is not None  # noqa: S101

    try:
        image_bytes = await asyncio.to_thread(_render_skill_gap_chart, features_df, persona)
    except ValueError as exc:
        analysis = await asyncio.to_thread(analyze_persona, features_df, persona)
        return JSONResponse(
            status_code=400,
            content={
                "error_code": "PERSONA_SKILL_GAP_UNAVAILABLE",
                "message": str(exc),
                "details": {"warnings": analysis.get("warnings", [])},
            },
        )

    return Response(content=image_bytes, media_type="image/png")


# ---------------------------------------------------------------------------
# Sprint-009 TASK-12: PDF export
# ---------------------------------------------------------------------------
@router.post(
    "/persona/export-pdf",
    response_model=None,
    response_class=StreamingResponse,
)
async def persona_export_pdf(
    profile: PersonaProfile,
    datastore: DataStore = Depends(get_datastore_dependency),
    settings: Settings = Depends(get_settings_dependency),
) -> StreamingResponse | JSONResponse:
    """Export skill gap analysis as PDF report (Sprint-009 TASK-12)."""
    if not datastore.is_ready:
        return data_unavailable_error(datastore)

    try:
        features_df = datastore.get_features_df()
    except DataUnavailableError:
        return data_unavailable_error(datastore)

    persona, error_response, _ = _prepare_persona(profile, features_df, min_market_n=settings.min_market_n)
    if error_response:
        return error_response
    assert persona is not None  # noqa: S101

    # B-NEW-01 fix: compute_persona_analysis is async — call directly (not via to_thread)
    analysis_result = await compute_persona_analysis(datastore, profile, min_market_n=settings.min_market_n)
    if isinstance(analysis_result, JSONResponse):
        return analysis_result
    analysis = _analysis_payload(analysis_result)
    trust = _trust_metadata(analysis)

    def _generate_pdf() -> bytes:
        buf = io.BytesIO()
        doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=2 * cm, rightMargin=2 * cm)
        styles = getSampleStyleSheet()
        elements: list = []

        role_name = profile.target_role or "—"
        grade_name = profile.target_grade or "any"
        elements.append(Paragraph(f"Skill Gap Report: {role_name} ({grade_name})", styles["h1"]))
        elements.append(Spacer(1, 0.5 * cm))

        ms = analysis.get("market_summary") or {}
        vacancy_count = ms.get("vacancy_count", 0)
        salary_median = ms.get("salary_median")
        remote_share = ms.get("remote_share")

        summary_data = [
            ["Метрика", "Значение"],
            ["Вакансий в сегменте", str(vacancy_count)],
            ["Медианная зарплата", _format_optional_number(salary_median, " RUB")],
            ["Доля удалёнки", _format_optional_percent(remote_share)],
        ]
        summary_table = Table(summary_data, colWidths=[8 * cm, 8 * cm])
        summary_table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E8EAF6")),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F5F5F5")]),
                ]
            )
        )
        elements.append(summary_table)
        elements.append(Spacer(1, 0.5 * cm))

        trust_data = [
            ["Data trust", "Value"],
            ["Dataset run", str(trust.get("dataset_run_id") or "n/a")],
            ["Generated at UTC", str(trust.get("generated_at_utc") or "n/a")],
            ["Freshness", str(trust.get("freshness") or "unknown")],
            ["Sample size", _format_optional_number(trust.get("sample_size"))],
            ["Confidence", str(trust.get("confidence") or "unknown")],
            ["Salary coverage", _format_optional_percent(trust.get("salary_coverage_share"))],
        ]
        trust_table = Table(trust_data, colWidths=[8 * cm, 8 * cm])
        trust_table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E8EAF6")),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F5F5F5")]),
                ]
            )
        )
        elements.append(trust_table)
        elements.append(Spacer(1, 0.5 * cm))

        skill_gap = analysis.get("skill_gap") or []
        if skill_gap:
            elements.append(Paragraph("Skill Gap", styles["h2"]))
            gap_data = [["Навык", "Спрос", "Есть", "Gap"]]
            for entry in skill_gap[:20]:
                gap_data.append(
                    [
                        str(entry.get("skill_name", "")),
                        f"{entry.get('market_share', 0) * 100:.0f}%",
                        "+" if entry.get("persona_has") else "-",
                        "!" if entry.get("gap") else "",
                    ]
                )
            gap_table = Table(gap_data, colWidths=[8 * cm, 3 * cm, 2 * cm, 2 * cm])
            gap_table.setStyle(
                TableStyle(
                    [
                        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E8EAF6")),
                        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F5F5F5")]),
                    ]
                )
            )
            elements.append(gap_table)
            elements.append(Spacer(1, 0.5 * cm))

        recommended = analysis.get("recommended_skills") or []
        if recommended:
            elements.append(Paragraph("Рекомендуем к изучению", styles["h2"]))
            for skill in recommended[:10]:
                elements.append(Paragraph(f"• {skill}", styles["Normal"]))

        doc.build(elements)
        buf.seek(0)
        return buf.read()

    pdf_bytes = await asyncio.to_thread(_generate_pdf)
    safe_role = (profile.target_role or "skill_gap").replace(" ", "_").replace("/", "-")[:40]
    return StreamingResponse(
        io.BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={
            "Content-Disposition": f"attachment; filename=skill_gap_{safe_role}.pdf",
            **_trust_headers(trust),
        },
    )


# ---------------------------------------------------------------------------
# Sprint-009 TASK-13: Share analysis result
# ---------------------------------------------------------------------------
@router.post("/persona/share", response_class=JSONResponse)
async def create_share_link(
    request: Request,
    profile: PersonaProfile,
    datastore: DataStore = Depends(get_datastore_dependency),
    settings: Settings = Depends(get_settings_dependency),
) -> JSONResponse:
    """Create a short-lived share token for persona analysis (Sprint-009 TASK-13).

    Stores result in Redis with 7-day TTL.
    """
    if not datastore.is_ready:
        return data_unavailable_error(datastore)

    redis = getattr(request.app.state, "redis", None)

    try:
        features_df = datastore.get_features_df()
    except DataUnavailableError:
        return data_unavailable_error(datastore)

    persona, error_response, _ = _prepare_persona(profile, features_df, min_market_n=settings.min_market_n)
    if error_response:
        return error_response
    assert persona is not None  # noqa: S101

    # B-NEW-01 fix: compute_persona_analysis is async — call directly (not via to_thread)
    share_result = await compute_persona_analysis(datastore, profile, min_market_n=settings.min_market_n)
    if isinstance(share_result, JSONResponse):
        return share_result
    result = share_result.model_dump() if hasattr(share_result, "model_dump") else {}

    session_maker = getattr(request.app.state, "session_maker", None)
    try:
        if session_maker is None:
            token = await create_share(result if isinstance(result, dict) else {}, redis=redis)
        else:
            async with session_maker() as session:
                token = await create_share(result if isinstance(result, dict) else {}, redis=redis, session=session)
    except RuntimeError as exc:
        return JSONResponse(status_code=503, content={"error": str(exc)})
    return JSONResponse(content={"token": token, "expires_in": 604800})


@public_router.get("/persona/share/{share_token}", response_class=JSONResponse)
async def get_shared_analysis(
    share_token: str,
    request: Request,
) -> JSONResponse:
    """Retrieve shared persona analysis by token (no auth required, Sprint-009 TASK-13)."""
    redis = getattr(request.app.state, "redis", None)
    session_maker = getattr(request.app.state, "session_maker", None)

    if session_maker is None:
        payload = await get_share(share_token, redis=redis)
    else:
        async with session_maker() as session:
            payload = await get_share(share_token, redis=redis, session=session)
    if not payload:
        return JSONResponse(status_code=404, content={"error": "Share link expired or not found"})
    return JSONResponse(content=payload)
