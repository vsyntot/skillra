"""B2B organization, invite and cohort analytics helpers."""

from __future__ import annotations

import csv
import hashlib
import io
import re
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from skillra_api.db.models import (
    ApplicationOutcomeEvent,
    CareerAction,
    CareerPlan,
    Cohort,
    CohortMembership,
    Organization,
    OrganizationMembership,
    ProductEvent,
    User,
    UserProfile,
    WeeklySubscription,
)
from skillra_api.schemas import CohortAnalyticsOut, CohortMetricOut, CohortSkillHeatmapRowOut
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

ORG_ADMIN_ROLES = {"owner", "admin"}
INVITE_TOKEN_BYTES = 24
DEFAULT_INVITE_TTL_DAYS = 14


def org_error(
    status_code: int,
    error_code: str,
    message: str,
    details: dict[str, object] | None = None,
) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail={"error_code": error_code, "message": message, "details": details or {}},
    )


def slugify(value: str, *, fallback: str = "org") -> str:
    normalized = re.sub(r"[^a-z0-9-]+", "-", value.strip().lower())
    normalized = re.sub(r"-+", "-", normalized).strip("-")
    return (normalized or fallback)[:64]


def generate_invite_token() -> tuple[str, str]:
    token = secrets.token_urlsafe(INVITE_TOKEN_BYTES)
    return token, invite_token_hash(token)


def invite_token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def ensure_aware_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


async def current_user_from_request_state(session: AsyncSession, telegram_user_id: int | None) -> User:
    if telegram_user_id is None:
        raise org_error(403, "USER_API_KEY_REQUIRED", "B2B workspace access requires a user API key.")
    user = await session.scalar(select(User).where(User.telegram_user_id == telegram_user_id))
    if user is None:
        raise org_error(403, "USER_API_KEY_REQUIRED", "B2B workspace access requires a registered user.")
    return user


async def org_membership(
    session: AsyncSession,
    *,
    organization_id: int,
    user_id: int,
) -> OrganizationMembership | None:
    return await session.scalar(
        select(OrganizationMembership).where(
            OrganizationMembership.organization_id == organization_id,
            OrganizationMembership.user_id == user_id,
            OrganizationMembership.status == "active",
        )
    )


async def require_org_member(
    session: AsyncSession,
    *,
    organization_id: int,
    user_id: int,
) -> OrganizationMembership:
    membership = await org_membership(session, organization_id=organization_id, user_id=user_id)
    if membership is None:
        raise org_error(403, "ORG_ACCESS_FORBIDDEN", "Нет доступа к этой организации.")
    return membership


async def require_org_admin(
    session: AsyncSession,
    *,
    organization_id: int,
    user_id: int,
) -> OrganizationMembership:
    membership = await require_org_member(session, organization_id=organization_id, user_id=user_id)
    if membership.role not in ORG_ADMIN_ROLES:
        raise org_error(403, "ORG_ADMIN_REQUIRED", "Доступно только администратору организации.")
    return membership


async def get_organization_or_404(session: AsyncSession, organization_id: int) -> Organization:
    organization = await session.scalar(
        select(Organization).where(Organization.id == organization_id, Organization.archived_at.is_(None))
    )
    if organization is None:
        raise org_error(404, "ORG_NOT_FOUND", "Организация не найдена.", {"organization_id": organization_id})
    return organization


async def get_cohort_or_404(session: AsyncSession, *, organization_id: int, cohort_id: int) -> Cohort:
    cohort = await session.scalar(
        select(Cohort).where(
            Cohort.id == cohort_id,
            Cohort.organization_id == organization_id,
            Cohort.archived_at.is_(None),
        )
    )
    if cohort is None:
        raise org_error(404, "COHORT_NOT_FOUND", "Когорта не найдена.", {"cohort_id": cohort_id})
    return cohort


async def count_org_members(session: AsyncSession, organization_id: int) -> int:
    return int(
        await session.scalar(
            select(func.count(OrganizationMembership.id)).where(
                OrganizationMembership.organization_id == organization_id,
                OrganizationMembership.status == "active",
            )
        )
        or 0
    )


async def count_org_cohorts(session: AsyncSession, organization_id: int) -> int:
    return int(
        await session.scalar(
            select(func.count(Cohort.id)).where(Cohort.organization_id == organization_id, Cohort.archived_at.is_(None))
        )
        or 0
    )


async def count_cohort_members(session: AsyncSession, cohort_id: int) -> int:
    return int(
        await session.scalar(
            select(func.count(CohortMembership.id)).where(
                CohortMembership.cohort_id == cohort_id,
                CohortMembership.status == "active",
            )
        )
        or 0
    )


def member_count_bucket(member_count: int, min_cohort_n: int) -> str:
    if member_count < min_cohort_n:
        return f"<{min_cohort_n}"
    return str(member_count)


def metric_rate(count: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round(count / denominator, 4)


async def cohort_user_ids(session: AsyncSession, cohort_id: int) -> list[int]:
    rows = (
        await session.scalars(
            select(CohortMembership.user_id).where(
                CohortMembership.cohort_id == cohort_id,
                CohortMembership.status == "active",
            )
        )
    ).all()
    return [int(row) for row in rows]


async def _count_distinct_users(session: AsyncSession, stmt) -> int:
    return int(await session.scalar(stmt) or 0)


async def _event_users(session: AsyncSession, user_ids: list[int], event_names: set[str], since: datetime) -> int:
    if not user_ids:
        return 0
    return await _count_distinct_users(
        session,
        select(func.count(func.distinct(ProductEvent.user_id))).where(
            ProductEvent.user_id.in_(user_ids),
            ProductEvent.event_type.in_(event_names),
            ProductEvent.occurred_at >= since,
        ),
    )


async def build_cohort_analytics(
    session: AsyncSession,
    *,
    organization_id: int,
    cohort: Cohort,
    days: int,
    min_cohort_n: int,
    min_cell_n: int,
) -> CohortAnalyticsOut:
    now = datetime.now(timezone.utc)
    since = now - timedelta(days=days)
    user_ids = await cohort_user_ids(session, cohort.id)
    member_count = len(user_ids)
    bucket = member_count_bucket(member_count, min_cohort_n)
    if member_count < min_cohort_n:
        return CohortAnalyticsOut(
            organization_id=organization_id,
            cohort_id=cohort.id,
            cohort_name=cohort.name,
            window_days=days,
            generated_at=now,
            member_count=member_count,
            member_count_bucket=bucket,
            suppressed=True,
            suppression_reason="small_cohort",
        )

    profile_count = await _count_distinct_users(
        session,
        select(func.count(func.distinct(UserProfile.user_id))).where(UserProfile.user_id.in_(user_ids)),
    )
    plan_count = await _count_distinct_users(
        session,
        select(func.count(func.distinct(CareerPlan.user_id))).where(CareerPlan.user_id.in_(user_ids)),
    )
    plan_action_started = await _count_distinct_users(
        session,
        select(func.count(func.distinct(CareerPlan.user_id)))
        .join(CareerAction, CareerAction.plan_id == CareerPlan.id)
        .where(CareerPlan.user_id.in_(user_ids), CareerAction.status.in_(["planned", "in_progress", "done"])),
    )
    plan_action_done = await _count_distinct_users(
        session,
        select(func.count(func.distinct(CareerPlan.user_id)))
        .join(CareerAction, CareerAction.plan_id == CareerPlan.id)
        .where(CareerPlan.user_id.in_(user_ids), CareerAction.status == "done"),
    )
    saved_vacancy = await _count_distinct_users(
        session,
        select(func.count(func.distinct(CareerPlan.user_id)))
        .join(CareerAction, CareerAction.plan_id == CareerPlan.id)
        .where(CareerPlan.user_id.in_(user_ids), CareerAction.action_type == "saved_vacancy"),
    )
    outcomes = await _count_distinct_users(
        session,
        select(func.count(func.distinct(ApplicationOutcomeEvent.user_id))).where(
            ApplicationOutcomeEvent.user_id.in_(user_ids)
        ),
    )
    digest_subscribers = await _count_distinct_users(
        session,
        select(func.count(func.distinct(WeeklySubscription.user_id))).where(
            WeeklySubscription.user_id.in_(user_ids),
            WeeklySubscription.active.is_(True),
        ),
    )

    raw_metrics = {
        "profile_completion_rate": profile_count,
        "market_view_rate": await _event_users(session, user_ids, {"market_fit_viewed"}, since),
        "skill_gap_view_rate": await _event_users(session, user_ids, {"skill_gap_viewed"}, since),
        "plan_created_rate": plan_count,
        "plan_action_started_rate": plan_action_started,
        "plan_action_done_rate": plan_action_done,
        "vacancy_search_rate": await _event_users(session, user_ids, {"vacancy_search_performed"}, since),
        "saved_vacancy_rate": saved_vacancy,
        "application_outcome_rate": outcomes,
        "digest_subscription_rate": digest_subscribers,
        "digest_engagement_rate": await _event_users(
            session,
            user_ids,
            {"digest_preview_viewed", "digest_opened", "digest_engagement"},
            since,
        ),
        "weekly_return_rate": await _event_users(session, user_ids, {"weekly_return", "weekly_returned"}, since),
    }

    metrics = [
        CohortMetricOut(metric=name, count=count, denominator=member_count, rate=metric_rate(count, member_count))
        for name, count in raw_metrics.items()
    ]
    heatmap = await build_skill_heatmap(session, user_ids=user_ids, member_count=member_count, min_cell_n=min_cell_n)
    return CohortAnalyticsOut(
        organization_id=organization_id,
        cohort_id=cohort.id,
        cohort_name=cohort.name,
        window_days=days,
        generated_at=now,
        member_count=member_count,
        member_count_bucket=bucket,
        metrics=metrics,
        skill_heatmap=heatmap,
    )


async def build_skill_heatmap(
    session: AsyncSession,
    *,
    user_ids: list[int],
    member_count: int,
    min_cell_n: int,
) -> list[CohortSkillHeatmapRowOut]:
    if not user_ids:
        return []
    rows = (
        await session.execute(
            select(CareerAction.skill_name, func.count(func.distinct(CareerPlan.user_id)))
            .join(CareerPlan, CareerPlan.id == CareerAction.plan_id)
            .where(
                CareerPlan.user_id.in_(user_ids),
                CareerAction.recommendation_source == "skill_gap",
                CareerAction.skill_name.is_not(None),
                CareerAction.status.in_(["planned", "in_progress"]),
            )
            .group_by(CareerAction.skill_name)
            .order_by(func.count(func.distinct(CareerPlan.user_id)).desc(), CareerAction.skill_name.asc())
            .limit(25)
        )
    ).all()
    target_roles = dict(
        (
            await session.execute(
                select(UserProfile.target_role, func.count(func.distinct(UserProfile.user_id)))
                .where(UserProfile.user_id.in_(user_ids), UserProfile.target_role.is_not(None))
                .group_by(UserProfile.target_role)
                .order_by(func.count(func.distinct(UserProfile.user_id)).desc())
            )
        ).all()
    )
    target_role = next(iter(target_roles), None)
    heatmap: list[CohortSkillHeatmapRowOut] = []
    for skill_name, users_missing in rows:
        count = int(users_missing or 0)
        suppressed = count < min_cell_n
        heatmap.append(
            CohortSkillHeatmapRowOut(
                skill_name=str(skill_name),
                cohort_member_count=member_count,
                users_missing_count=None if suppressed else count,
                users_missing_share=None if suppressed else metric_rate(count, member_count),
                target_role=target_role,
                suppressed=suppressed,
            )
        )
    return heatmap


def cohort_analytics_csv(analytics: CohortAnalyticsOut) -> str:
    output = io.StringIO()
    fieldnames = [
        "section",
        "organization_id",
        "cohort_id",
        "cohort_name",
        "window_days",
        "generated_at",
        "member_count_bucket",
        "metric",
        "count",
        "denominator",
        "rate",
        "skill_name",
        "users_missing_count",
        "users_missing_share",
        "suppressed",
        "suppression_reason",
    ]
    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()
    base = {
        "organization_id": analytics.organization_id,
        "cohort_id": analytics.cohort_id,
        "cohort_name": analytics.cohort_name,
        "window_days": analytics.window_days,
        "generated_at": analytics.generated_at.isoformat(),
        "member_count_bucket": analytics.member_count_bucket,
        "suppression_reason": analytics.suppression_reason or "",
    }
    if analytics.suppressed:
        writer.writerow({**base, "section": "suppression", "suppressed": "true"})
        return output.getvalue()
    for metric in analytics.metrics:
        writer.writerow(
            {
                **base,
                "section": "metric",
                "metric": metric.metric,
                "count": metric.count,
                "denominator": metric.denominator,
                "rate": metric.rate,
                "suppressed": str(metric.suppressed).lower(),
            }
        )
    for row in analytics.skill_heatmap:
        writer.writerow(
            {
                **base,
                "section": "skill_heatmap",
                "skill_name": row.skill_name,
                "denominator": row.cohort_member_count,
                "users_missing_count": row.users_missing_count,
                "users_missing_share": row.users_missing_share,
                "suppressed": str(row.suppressed).lower(),
            }
        )
    return output.getvalue()
