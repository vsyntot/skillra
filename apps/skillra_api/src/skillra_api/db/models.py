"""ORM models for Skillra API database schema."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func
from sqlalchemy.types import JSON, TypeDecorator

from .session import Base


class StringList(TypeDecorator[list[str]]):
    """Store list of strings as ARRAY in Postgres and JSON elsewhere."""

    impl = ARRAY(String())
    cache_ok = True

    def load_dialect_impl(self, dialect):  # type: ignore[override]
        if dialect.name == "postgresql":
            return dialect.type_descriptor(ARRAY(String()))
        return dialect.type_descriptor(JSON())


class User(Base):
    """Represents a Skillra user identified by Telegram user id."""

    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("telegram_user_id", name="uq_users_telegram_user_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    telegram_user_id: Mapped[int] = mapped_column(BigInteger, nullable=False, unique=True, index=True)
    username: Mapped[Optional[str]] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    profile: Mapped[Optional["UserProfile"]] = relationship(
        back_populates="user", uselist=False, cascade="all, delete-orphan"
    )
    weekly_subscription: Mapped[Optional["WeeklySubscription"]] = relationship(
        back_populates="user", uselist=False, cascade="all, delete-orphan"
    )
    resume: Mapped[Optional["UserResume"]] = relationship(
        back_populates="user", uselist=False, cascade="all, delete-orphan"
    )
    career_plan: Mapped[Optional["CareerPlan"]] = relationship(
        back_populates="user", uselist=False, cascade="all, delete-orphan"
    )
    application_outcomes: Mapped[list["ApplicationOutcomeEvent"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    product_events: Mapped[list["ProductEvent"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    commercial_account: Mapped[Optional["UserCommercialAccount"]] = relationship(
        back_populates="user", uselist=False, cascade="all, delete-orphan"
    )
    organization_memberships: Mapped[list["OrganizationMembership"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    cohort_memberships: Mapped[list["CohortMembership"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class UserProfile(Base):
    """Stores target career preferences and skills for a user."""

    __tablename__ = "user_profiles"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False)

    target_role: Mapped[Optional[str]] = mapped_column(String(100))
    target_grade: Mapped[Optional[str]] = mapped_column(String(50))
    target_city_tier: Mapped[Optional[str]] = mapped_column(String(50))
    target_country: Mapped[Optional[str]] = mapped_column(String(100))
    target_region: Mapped[Optional[str]] = mapped_column(String(100))
    target_city: Mapped[Optional[str]] = mapped_column(String(100))
    target_geo_scope: Mapped[Optional[str]] = mapped_column(String(32))
    target_work_mode: Mapped[Optional[str]] = mapped_column(String(50))
    target_domain: Mapped[Optional[str]] = mapped_column(String(100))
    current_skills: Mapped[list[str]] = mapped_column(StringList(), default=list, nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    user: Mapped[User] = relationship(back_populates="profile")


class WeeklySubscription(Base):
    """Represents weekly digest subscription preferences for a user."""

    __tablename__ = "weekly_subscriptions"

    __table_args__ = (
        CheckConstraint("weekday >= 0 AND weekday <= 6", name="weekday_range"),
        Index("ix_weekly_subscriptions_active_weekday", "active", "weekday"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"), nullable=False)
    weekday: Mapped[int] = mapped_column(Integer, nullable=False)
    time_local: Mapped[str] = mapped_column(String(5), nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False)
    lock: Mapped[Optional[str]] = mapped_column(String(64))
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    last_sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    backoff_until: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    user: Mapped[User] = relationship(back_populates="weekly_subscription")


class DigestHistory(Base):
    """Records of successfully sent weekly digest messages (Sprint-007 TASK-07)."""

    __tablename__ = "digest_history"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    format: Mapped[str] = mapped_column(String(20), nullable=False, server_default=text("'HTML'"))
    text_preview: Mapped[Optional[str]] = mapped_column(String(500))
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))

    user: Mapped[User] = relationship()


class MarketSnapshot(Base):
    """Weekly aggregate market snapshot for trend endpoints."""

    __tablename__ = "market_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "week_start",
            "role",
            "grade",
            "city_tier",
            "work_mode",
            "domain",
            name="uq_market_snapshots_segment_week",
        ),
        Index("ix_market_snapshots_role_grade_week", "role", "grade", "week_start"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    week_start: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    role: Mapped[str] = mapped_column(String(100), nullable=False)
    grade: Mapped[str] = mapped_column(String(50), nullable=False)
    city_tier: Mapped[str] = mapped_column(String(50), nullable=False)
    work_mode: Mapped[str] = mapped_column(String(50), nullable=False)
    domain: Mapped[str] = mapped_column(String(100), nullable=False)
    vacancy_count: Mapped[int] = mapped_column(Integer, nullable=False)
    salary_p25: Mapped[Optional[float]] = mapped_column(Float)
    salary_p50: Mapped[Optional[float]] = mapped_column(Float)
    salary_p75: Mapped[Optional[float]] = mapped_column(Float)
    skill_top10: Mapped[Optional[str]] = mapped_column(Text)


class VacancySnapshot(Base):
    """Raw vacancy snapshot for full-text search via MeiliSearch (Sprint-008 TASK-03)."""

    __tablename__ = "vacancy_snapshots"
    __table_args__ = (
        Index("ix_vacancy_snapshots_role_grade", "primary_role", "grade"),
        Index("ix_vacancy_snapshots_published_at", "published_at"),
        Index("ix_vacancy_snapshots_dataset_run_id", "dataset_run_id"),
        Index("ix_vacancy_snapshots_geo", "country", "region", "city_normalized"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    hh_vacancy_id: Mapped[str] = mapped_column(String(50), unique=True, index=True, nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    primary_role: Mapped[Optional[str]] = mapped_column(String(100))
    grade: Mapped[Optional[str]] = mapped_column(String(50))
    city: Mapped[Optional[str]] = mapped_column(String(100))
    city_tier: Mapped[Optional[str]] = mapped_column(String(50))
    country: Mapped[Optional[str]] = mapped_column(String(100))
    region: Mapped[Optional[str]] = mapped_column(String(100))
    city_normalized: Mapped[Optional[str]] = mapped_column(String(100))
    geo_scope: Mapped[Optional[str]] = mapped_column(String(32))
    salary_from: Mapped[Optional[int]] = mapped_column(Integer)
    salary_to: Mapped[Optional[int]] = mapped_column(Integer)
    skills: Mapped[list[str]] = mapped_column(StringList(), default=list, nullable=False)
    description_snippet: Mapped[Optional[str]] = mapped_column(String(5000))
    url: Mapped[Optional[str]] = mapped_column(String(500))
    hh_url: Mapped[Optional[str]] = mapped_column(String(512))
    published_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    indexed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    dataset_run_id: Mapped[Optional[str]] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class UserApiKey(Base):
    """Per-user API key for authenticating web clients (Sprint-011 TASK-02 / ADR-008)."""

    __tablename__ = "user_api_keys"
    __table_args__ = (Index("ix_user_api_keys_user_id", "user_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    key_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    key_prefix: Mapped[str] = mapped_column(String(8), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_used_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped["User"] = relationship()


class UserResume(Base):
    """Uploaded resume object and parsed skill metadata."""

    __tablename__ = "user_resumes"
    __table_args__ = (Index("ix_user_resumes_user_id", "user_id", unique=True),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    s3_key: Mapped[str] = mapped_column(String(512), nullable=False)
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str] = mapped_column(String(100), nullable=False)
    file_size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    extracted_skills: Mapped[Optional[str]] = mapped_column(Text)

    user: Mapped[User] = relationship(back_populates="resume")


class CareerPlan(Base):
    """User career plan derived from profile and skill-gap analysis."""

    __tablename__ = "career_plans"
    __table_args__ = (
        Index("ix_career_plans_user_id", "user_id", unique=True),
        Index("ix_career_plans_status", "status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True)
    target_role: Mapped[Optional[str]] = mapped_column(String(100))
    target_grade: Mapped[Optional[str]] = mapped_column(String(50))
    target_city_tier: Mapped[Optional[str]] = mapped_column(String(50))
    target_country: Mapped[Optional[str]] = mapped_column(String(100))
    target_region: Mapped[Optional[str]] = mapped_column(String(100))
    target_city: Mapped[Optional[str]] = mapped_column(String(100))
    target_geo_scope: Mapped[Optional[str]] = mapped_column(String(32))
    target_work_mode: Mapped[Optional[str]] = mapped_column(String(50))
    target_domain: Mapped[Optional[str]] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(32), nullable=False, server_default=text("'active'"))
    notes: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    user: Mapped[User] = relationship(back_populates="career_plan")
    actions: Mapped[list["CareerAction"]] = relationship(
        back_populates="plan",
        cascade="all, delete-orphan",
        order_by="CareerAction.priority.asc(), CareerAction.id.asc()",
    )


class CareerAction(Base):
    """Action item inside a career plan."""

    __tablename__ = "career_actions"
    __table_args__ = (
        Index("ix_career_actions_plan_id_status", "plan_id", "status"),
        Index("ix_career_actions_hh_vacancy_id", "hh_vacancy_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    plan_id: Mapped[int] = mapped_column(ForeignKey("career_plans.id", ondelete="CASCADE"), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    action_type: Mapped[str] = mapped_column(String(32), nullable=False, server_default=text("'learning'"))
    status: Mapped[str] = mapped_column(String(32), nullable=False, server_default=text("'planned'"))
    priority: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("100"))
    skill_name: Mapped[Optional[str]] = mapped_column(String(100))
    hh_vacancy_id: Mapped[Optional[str]] = mapped_column(String(50))
    vacancy_title: Mapped[Optional[str]] = mapped_column(String(500))
    vacancy_url: Mapped[Optional[str]] = mapped_column(String(512))
    recommendation_source: Mapped[str] = mapped_column(String(32), nullable=False, server_default=text("'manual'"))
    dataset_run_id: Mapped[Optional[str]] = mapped_column(String(64))
    reason: Mapped[Optional[str]] = mapped_column(Text)
    expected_impact: Mapped[Optional[str]] = mapped_column(String(64))
    effort_estimate: Mapped[Optional[str]] = mapped_column(String(64))
    due_date: Mapped[Optional[date]] = mapped_column(Date)
    evidence: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON)
    application_status: Mapped[Optional[str]] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    plan: Mapped[CareerPlan] = relationship(back_populates="actions")
    outcome_events: Mapped[list["ApplicationOutcomeEvent"]] = relationship(
        back_populates="action", cascade="all, delete-orphan"
    )


class ApplicationOutcomeEvent(Base):
    """Timestamped vacancy/application funnel transition for a user."""

    __tablename__ = "application_outcome_events"
    __table_args__ = (
        Index("ix_application_outcomes_user_occurred", "user_id", "occurred_at"),
        Index("ix_application_outcomes_hh_vacancy_id", "hh_vacancy_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    action_id: Mapped[Optional[int]] = mapped_column(ForeignKey("career_actions.id", ondelete="SET NULL"))
    hh_vacancy_id: Mapped[Optional[str]] = mapped_column(String(50))
    vacancy_title: Mapped[Optional[str]] = mapped_column(String(500))
    vacancy_url: Mapped[Optional[str]] = mapped_column(String(512))
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False, server_default=text("'user'"))
    note: Mapped[Optional[str]] = mapped_column(Text)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    user: Mapped[User] = relationship(back_populates="application_outcomes")
    action: Mapped[Optional[CareerAction]] = relationship(back_populates="outcome_events")


class ProductEvent(Base):
    """PII-light product loop event for activation and outcome metrics."""

    __tablename__ = "product_events"
    __table_args__ = (
        Index("ix_product_events_user_type_occurred", "user_id", "event_type", "occurred_at"),
        Index("ix_product_events_event_type", "event_type"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False, server_default=text("'api'"))
    entity_type: Mapped[Optional[str]] = mapped_column(String(64))
    entity_id: Mapped[Optional[str]] = mapped_column(String(64))
    request_id: Mapped[Optional[str]] = mapped_column(String(128))
    session_id: Mapped[Optional[str]] = mapped_column(String(128))
    correlation_id: Mapped[Optional[str]] = mapped_column(String(128))
    payload: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    user: Mapped[User] = relationship(back_populates="product_events")


class UserCommercialAccount(Base):
    """Commercial plan and entitlement state for a user."""

    __tablename__ = "user_commercial_accounts"
    __table_args__ = (
        CheckConstraint("plan IN ('free', 'trial', 'pro', 'admin')", name="ck_user_commercial_accounts_plan"),
        CheckConstraint(
            "subscription_state IN ('none', 'trialing', 'active', 'cancel_at_period_end', 'expired', 'refunded', "
            "'payment_failed', 'provider_unavailable', 'past_due', 'cancelled')",
            name="ck_user_commercial_accounts_subscription_state",
        ),
        Index("ix_user_commercial_accounts_plan_state", "plan", "subscription_state"),
        UniqueConstraint("user_id", name="uq_user_commercial_accounts_user_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True)
    plan: Mapped[str] = mapped_column(String(32), nullable=False, server_default=text("'free'"))
    subscription_state: Mapped[str] = mapped_column(String(32), nullable=False, server_default=text("'none'"))
    entitlements: Mapped[Optional[list[str]]] = mapped_column(JSON)
    provider: Mapped[Optional[str]] = mapped_column(String(32))
    provider_customer_id: Mapped[Optional[str]] = mapped_column(String(128))
    provider_subscription_id: Mapped[Optional[str]] = mapped_column(String(128))
    trial_started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    trial_ends_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    current_period_ends_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    user: Mapped[User] = relationship(back_populates="commercial_account")


class BillingEvent(Base):
    """Provider-neutral billing webhook event ledger."""

    __tablename__ = "billing_events"
    __table_args__ = (
        UniqueConstraint("provider", "provider_event_id", name="uq_billing_events_provider_event"),
        Index("ix_billing_events_user_provider", "user_id", "provider"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    provider_event_id: Mapped[str] = mapped_column(String(128), nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON)
    processed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class Organization(Base):
    """B2B workspace for cohorts, invites and aggregate reporting."""

    __tablename__ = "organizations"
    __table_args__ = (
        UniqueConstraint("slug", name="uq_organizations_slug"),
        CheckConstraint(
            "organization_type IN ('university', 'bootcamp', 'career_center', 'company', 'other')",
            name="ck_organizations_type",
        ),
        Index("ix_organizations_archived_at", "archived_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    organization_type: Mapped[str] = mapped_column(String(32), nullable=False, server_default=text("'other'"))
    created_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
    archived_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    created_by_user: Mapped[User] = relationship(foreign_keys=[created_by_user_id])
    memberships: Mapped[list["OrganizationMembership"]] = relationship(
        back_populates="organization", cascade="all, delete-orphan"
    )
    cohorts: Mapped[list["Cohort"]] = relationship(back_populates="organization", cascade="all, delete-orphan")
    invites: Mapped[list["OrganizationInvite"]] = relationship(
        back_populates="organization", cascade="all, delete-orphan"
    )


class OrganizationMembership(Base):
    """User membership and role inside an organization workspace."""

    __tablename__ = "organization_memberships"
    __table_args__ = (
        UniqueConstraint("organization_id", "user_id", name="uq_organization_memberships_org_user"),
        CheckConstraint("role IN ('owner', 'admin', 'member')", name="ck_organization_memberships_role"),
        CheckConstraint("status IN ('active', 'revoked')", name="ck_organization_memberships_status"),
        Index("ix_organization_memberships_user_status", "user_id", "status"),
        Index("ix_organization_memberships_org_role", "organization_id", "role"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False, server_default=text("'member'"))
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default=text("'active'"))
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    organization: Mapped[Organization] = relationship(back_populates="memberships")
    user: Mapped[User] = relationship(back_populates="organization_memberships")


class Cohort(Base):
    """B2B cohort inside an organization."""

    __tablename__ = "cohorts"
    __table_args__ = (
        UniqueConstraint("organization_id", "slug", name="uq_cohorts_org_slug"),
        Index("ix_cohorts_organization_archived", "organization_id", "archived_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    slug: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    starts_at: Mapped[Optional[date]] = mapped_column(Date)
    ends_at: Mapped[Optional[date]] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
    archived_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    organization: Mapped[Organization] = relationship(back_populates="cohorts")
    memberships: Mapped[list["CohortMembership"]] = relationship(back_populates="cohort", cascade="all, delete-orphan")
    invites: Mapped[list["OrganizationInvite"]] = relationship(back_populates="cohort")


class CohortMembership(Base):
    """User membership inside a B2B cohort."""

    __tablename__ = "cohort_memberships"
    __table_args__ = (
        UniqueConstraint("cohort_id", "user_id", name="uq_cohort_memberships_cohort_user"),
        CheckConstraint("status IN ('active', 'revoked')", name="ck_cohort_memberships_status"),
        Index("ix_cohort_memberships_user_status", "user_id", "status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    cohort_id: Mapped[int] = mapped_column(ForeignKey("cohorts.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default=text("'active'"))
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    cohort: Mapped[Cohort] = relationship(back_populates="memberships")
    user: Mapped[User] = relationship(back_populates="cohort_memberships")


class OrganizationInvite(Base):
    """Hash-only invite token for joining an organization and optional cohort."""

    __tablename__ = "organization_invites"
    __table_args__ = (
        UniqueConstraint("token_hash", name="uq_organization_invites_token_hash"),
        CheckConstraint("role IN ('admin', 'member')", name="ck_organization_invites_role"),
        CheckConstraint("max_uses >= 1", name="ck_organization_invites_max_uses"),
        CheckConstraint("uses_count >= 0", name="ck_organization_invites_uses_count"),
        Index("ix_organization_invites_org_revoked", "organization_id", "revoked_at"),
        Index("ix_organization_invites_expires_at", "expires_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    cohort_id: Mapped[Optional[int]] = mapped_column(ForeignKey("cohorts.id", ondelete="SET NULL"))
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    role: Mapped[str] = mapped_column(String(16), nullable=False, server_default=text("'member'"))
    max_uses: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    uses_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    organization: Mapped[Organization] = relationship(back_populates="invites")
    cohort: Mapped[Optional[Cohort]] = relationship(back_populates="invites")
    created_by_user: Mapped[User] = relationship(foreign_keys=[created_by_user_id])


class IndexerRun(Base):
    """Persistent vacancy indexer run status."""

    __tablename__ = "indexer_runs"
    __table_args__ = (Index("ix_indexer_runs_started_at", "started_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    source: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    dataset_run_id: Mapped[Optional[str]] = mapped_column(String(64), index=True)
    inserted: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    indexed: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    error_msg: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class DataRun(Base):
    """Persistent end-to-end data pipeline run status."""

    __tablename__ = "data_runs"
    __table_args__ = (
        Index("ix_data_runs_started_at", "started_at"),
        Index("ix_data_runs_state", "state"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    source: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    raw_rows: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    processed_rows: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    error_msg: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    dataset_meta_path: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    manifest_uri: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    quality_report_uri: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    artifact_uris: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)
    raw_quality_report: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)
    processed_quality_report: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)
    product_eligibility: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)
    source_capability_ref: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)


class ActiveDataset(Base):
    """Transactional pointer to the currently published product dataset."""

    __tablename__ = "active_datasets"
    __table_args__ = (
        Index("ix_active_datasets_run_id", "run_id"),
        Index("ix_active_datasets_activated_at", "activated_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[str] = mapped_column(String(64), ForeignKey("data_runs.run_id"), nullable=False)
    activated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    dataset_meta_path: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    manifest_uri: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    quality_report_uri: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    raw_rows: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    processed_rows: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)


class ShareToken(Base):
    """DB fallback storage for persona share links."""

    __tablename__ = "share_tokens"
    __table_args__ = (
        Index("ix_share_tokens_token", "token", unique=True),
        Index("ix_share_tokens_expires_at", "expires_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    token: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    payload: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
