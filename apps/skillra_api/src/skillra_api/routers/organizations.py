from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from skillra_api.config import Settings
from skillra_api.db.models import (
    Cohort,
    CohortMembership,
    Organization,
    OrganizationInvite,
    OrganizationMembership,
    User,
    UserProfile,
)
from skillra_api.deps import get_db_session, get_settings_dependency
from skillra_api.deps.auth import require_user_or_service_token
from skillra_api.schemas import (
    CohortAnalyticsOut,
    CohortIn,
    CohortMemberOut,
    CohortMemberPatch,
    CohortOut,
    InviteAcceptOut,
    OrganizationIn,
    OrganizationInviteIn,
    OrganizationInviteOut,
    OrganizationMemberOut,
    OrganizationMemberPatch,
    OrganizationOut,
    OrganizationPatch,
)
from skillra_api.services.organizations import (
    DEFAULT_INVITE_TTL_DAYS,
    build_cohort_analytics,
    cohort_analytics_csv,
    count_cohort_members,
    count_org_cohorts,
    count_org_members,
    current_user_from_request_state,
    ensure_aware_utc,
    generate_invite_token,
    get_cohort_or_404,
    get_organization_or_404,
    invite_token_hash,
    org_error,
    require_org_admin,
    require_org_member,
    slugify,
)
from skillra_api.services.product_events import build_product_event

router = APIRouter(prefix="/v1", tags=["organizations"])


async def _current_user(request: Request, session: AsyncSession) -> User:
    return await current_user_from_request_state(session, getattr(request.state, "telegram_user_id", None))


async def _organization_out(
    session: AsyncSession,
    organization: Organization,
    membership: OrganizationMembership,
) -> OrganizationOut:
    return OrganizationOut(
        id=organization.id,
        slug=organization.slug,
        name=organization.name,
        organization_type=organization.organization_type,  # type: ignore[arg-type]
        role=membership.role,  # type: ignore[arg-type]
        members_count=await count_org_members(session, organization.id),
        cohorts_count=await count_org_cohorts(session, organization.id),
        created_at=organization.created_at,
        archived_at=organization.archived_at,
    )


async def _cohort_out(session: AsyncSession, cohort: Cohort) -> CohortOut:
    return CohortOut(
        id=cohort.id,
        organization_id=cohort.organization_id,
        slug=cohort.slug,
        name=cohort.name,
        members_count=await count_cohort_members(session, cohort.id),
        starts_at=cohort.starts_at,
        ends_at=cohort.ends_at,
        created_at=cohort.created_at,
        archived_at=cohort.archived_at,
    )


def _invite_out(invite: OrganizationInvite, *, token: str | None = None) -> OrganizationInviteOut:
    return OrganizationInviteOut(
        id=invite.id,
        organization_id=invite.organization_id,
        cohort_id=invite.cohort_id,
        role=invite.role,  # type: ignore[arg-type]
        max_uses=invite.max_uses,
        uses_count=invite.uses_count,
        expires_at=invite.expires_at,
        revoked_at=invite.revoked_at,
        created_at=invite.created_at,
        token=token,
    )


async def _organization_member_out(session: AsyncSession, membership: OrganizationMembership) -> OrganizationMemberOut:
    has_profile = await session.scalar(select(UserProfile.id).where(UserProfile.user_id == membership.user_id))
    return OrganizationMemberOut(
        user_id=membership.user_id,
        role=membership.role,  # type: ignore[arg-type]
        status=membership.status,  # type: ignore[arg-type]
        has_profile=has_profile is not None,
        joined_at=membership.joined_at,
    )


async def _cohort_member_out(session: AsyncSession, membership: CohortMembership) -> CohortMemberOut:
    has_profile = await session.scalar(select(UserProfile.id).where(UserProfile.user_id == membership.user_id))
    return CohortMemberOut(
        user_id=membership.user_id,
        status=membership.status,  # type: ignore[arg-type]
        has_profile=has_profile is not None,
        joined_at=membership.joined_at,
    )


async def _ensure_org_slug_available(session: AsyncSession, slug: str) -> None:
    exists = await session.scalar(select(Organization.id).where(Organization.slug == slug))
    if exists is not None:
        raise org_error(409, "ORG_SLUG_EXISTS", "Организация с таким slug уже существует.", {"slug": slug})


async def _ensure_cohort_slug_available(session: AsyncSession, organization_id: int, slug: str) -> None:
    exists = await session.scalar(
        select(Cohort.id).where(Cohort.organization_id == organization_id, Cohort.slug == slug)
    )
    if exists is not None:
        raise org_error(409, "COHORT_SLUG_EXISTS", "Когорта с таким slug уже существует.", {"slug": slug})


async def _revoke_member_cohort_memberships(
    session: AsyncSession,
    *,
    organization_id: int,
    user_id: int,
) -> int:
    cohort_ids = (
        await session.scalars(
            select(Cohort.id).where(
                Cohort.organization_id == organization_id,
                Cohort.archived_at.is_(None),
            )
        )
    ).all()
    if not cohort_ids:
        return 0
    memberships = (
        await session.scalars(
            select(CohortMembership).where(
                CohortMembership.cohort_id.in_(cohort_ids),
                CohortMembership.user_id == user_id,
                CohortMembership.status == "active",
            )
        )
    ).all()
    for membership in memberships:
        membership.status = "revoked"
    return len(memberships)


def _add_org_audit_event(
    session: AsyncSession,
    *,
    actor_user_id: int,
    event_name: str,
    organization_id: int,
    metadata: dict[str, object],
) -> None:
    session.add(
        build_product_event(
            user_id=actor_user_id,
            event_name=event_name,
            surface="admin",
            entity_type="organization",
            entity_id=str(organization_id),
            metadata=metadata,
        )
    )


@router.post(
    "/organizations",
    response_model=OrganizationOut,
    response_class=JSONResponse,
    dependencies=[Depends(require_user_or_service_token)],
)
async def create_organization(
    payload: OrganizationIn,
    request: Request,
    session: AsyncSession = Depends(get_db_session),
) -> OrganizationOut:
    user = await _current_user(request, session)
    slug = slugify(payload.slug or payload.name)
    await _ensure_org_slug_available(session, slug)

    organization = Organization(
        slug=slug,
        name=payload.name,
        organization_type=payload.organization_type,
        created_by_user_id=user.id,
    )
    session.add(organization)
    await session.flush()
    membership = OrganizationMembership(organization_id=organization.id, user_id=user.id, role="owner")
    session.add(membership)
    await session.commit()

    await session.refresh(organization)
    await session.refresh(membership)
    return await _organization_out(session, organization, membership)


@router.get(
    "/organizations",
    response_model=list[OrganizationOut],
    response_class=JSONResponse,
    dependencies=[Depends(require_user_or_service_token)],
)
async def list_organizations(
    request: Request,
    session: AsyncSession = Depends(get_db_session),
) -> list[OrganizationOut]:
    user = await _current_user(request, session)
    rows = (
        await session.execute(
            select(Organization, OrganizationMembership)
            .join(OrganizationMembership, OrganizationMembership.organization_id == Organization.id)
            .where(
                OrganizationMembership.user_id == user.id,
                OrganizationMembership.status == "active",
                Organization.archived_at.is_(None),
            )
            .order_by(Organization.created_at.desc(), Organization.id.desc())
        )
    ).all()
    return [await _organization_out(session, organization, membership) for organization, membership in rows]


@router.get(
    "/organizations/{organization_id}",
    response_model=OrganizationOut,
    response_class=JSONResponse,
    dependencies=[Depends(require_user_or_service_token)],
)
async def get_organization(
    organization_id: int,
    request: Request,
    session: AsyncSession = Depends(get_db_session),
) -> OrganizationOut:
    user = await _current_user(request, session)
    organization = await get_organization_or_404(session, organization_id)
    membership = await require_org_member(session, organization_id=organization_id, user_id=user.id)
    return await _organization_out(session, organization, membership)


@router.patch(
    "/organizations/{organization_id}",
    response_model=OrganizationOut,
    response_class=JSONResponse,
    dependencies=[Depends(require_user_or_service_token)],
)
async def update_organization(
    organization_id: int,
    payload: OrganizationPatch,
    request: Request,
    session: AsyncSession = Depends(get_db_session),
) -> OrganizationOut:
    user = await _current_user(request, session)
    organization = await get_organization_or_404(session, organization_id)
    membership = await require_org_admin(session, organization_id=organization_id, user_id=user.id)
    if payload.name is not None:
        organization.name = payload.name
    if payload.organization_type is not None:
        organization.organization_type = payload.organization_type
    await session.commit()
    await session.refresh(organization)
    return await _organization_out(session, organization, membership)


@router.get(
    "/organizations/{organization_id}/members",
    response_model=list[OrganizationMemberOut],
    response_class=JSONResponse,
    dependencies=[Depends(require_user_or_service_token)],
)
async def list_organization_members(
    organization_id: int,
    request: Request,
    session: AsyncSession = Depends(get_db_session),
) -> list[OrganizationMemberOut]:
    user = await _current_user(request, session)
    await get_organization_or_404(session, organization_id)
    await require_org_admin(session, organization_id=organization_id, user_id=user.id)
    rows = (
        await session.execute(
            select(OrganizationMembership, UserProfile.id)
            .join(User, User.id == OrganizationMembership.user_id)
            .join(UserProfile, UserProfile.user_id == User.id, isouter=True)
            .where(OrganizationMembership.organization_id == organization_id)
            .order_by(OrganizationMembership.joined_at.asc(), OrganizationMembership.id.asc())
        )
    ).all()
    return [
        OrganizationMemberOut(
            user_id=membership.user_id,
            role=membership.role,  # type: ignore[arg-type]
            status=membership.status,  # type: ignore[arg-type]
            has_profile=profile_id is not None,
            joined_at=membership.joined_at,
        )
        for membership, profile_id in rows
    ]


@router.patch(
    "/organizations/{organization_id}/members/{member_user_id}",
    response_model=OrganizationMemberOut,
    response_class=JSONResponse,
    dependencies=[Depends(require_user_or_service_token)],
)
async def update_organization_member(
    organization_id: int,
    member_user_id: int,
    payload: OrganizationMemberPatch,
    request: Request,
    session: AsyncSession = Depends(get_db_session),
) -> OrganizationMemberOut:
    user = await _current_user(request, session)
    await get_organization_or_404(session, organization_id)
    actor_membership = await require_org_admin(session, organization_id=organization_id, user_id=user.id)
    membership = await session.scalar(
        select(OrganizationMembership).where(
            OrganizationMembership.organization_id == organization_id,
            OrganizationMembership.user_id == member_user_id,
        )
    )
    if membership is None:
        raise org_error(404, "ORG_MEMBER_NOT_FOUND", "Участник организации не найден.")
    if membership.role == "owner" and payload.status == "revoked":
        raise org_error(409, "ORG_OWNER_REVOKE_FORBIDDEN", "Нельзя отозвать владельца организации.")

    original_role = membership.role
    original_status = membership.status
    revoked_cohort_memberships = 0
    owner_transferred = False

    if payload.role == "owner" and payload.status == "revoked":
        raise org_error(
            409,
            "ORG_OWNER_TRANSFER_TARGET_INACTIVE",
            "Передать владение можно только активному участнику организации.",
        )

    if payload.role is not None:
        if payload.role == "owner" and membership.role != "owner":
            if actor_membership.role != "owner":
                raise org_error(
                    403,
                    "ORG_OWNER_TRANSFER_OWNER_REQUIRED",
                    "Передача владельца доступна только текущему владельцу организации.",
                )
            if membership.status != "active":
                raise org_error(
                    409,
                    "ORG_OWNER_TRANSFER_TARGET_INACTIVE",
                    "Передать владение можно только активному участнику организации.",
                )
            membership.role = "owner"
            if actor_membership.user_id != membership.user_id:
                actor_membership.role = "admin"
            owner_transferred = True
        elif membership.role == "owner" and payload.role != "owner":
            raise org_error(
                409,
                "ORG_OWNER_DEMOTE_FORBIDDEN",
                "Для смены владельца назначьте роль owner другому активному участнику.",
            )
        else:
            membership.role = payload.role
    if payload.status is not None:
        membership.status = payload.status
        if payload.status == "revoked":
            revoked_cohort_memberships = await _revoke_member_cohort_memberships(
                session,
                organization_id=organization_id,
                user_id=membership.user_id,
            )

    if owner_transferred:
        _add_org_audit_event(
            session,
            actor_user_id=user.id,
            event_name="organization_owner_transferred",
            organization_id=organization_id,
            metadata={
                "target_user_id": membership.user_id,
                "previous_owner_user_id": user.id,
                "previous_target_role": original_role,
            },
        )
    elif original_role != membership.role or original_status != membership.status:
        _add_org_audit_event(
            session,
            actor_user_id=user.id,
            event_name="organization_member_updated",
            organization_id=organization_id,
            metadata={
                "target_user_id": membership.user_id,
                "from_role": original_role,
                "to_role": membership.role,
                "from_status": original_status,
                "to_status": membership.status,
                "revoked_cohort_memberships": revoked_cohort_memberships,
            },
        )

    await session.commit()
    return await _organization_member_out(session, membership)


@router.post(
    "/organizations/{organization_id}/cohorts",
    response_model=CohortOut,
    response_class=JSONResponse,
    dependencies=[Depends(require_user_or_service_token)],
)
async def create_cohort(
    organization_id: int,
    payload: CohortIn,
    request: Request,
    session: AsyncSession = Depends(get_db_session),
) -> CohortOut:
    user = await _current_user(request, session)
    await get_organization_or_404(session, organization_id)
    await require_org_admin(session, organization_id=organization_id, user_id=user.id)
    slug = slugify(payload.slug or payload.name, fallback="cohort")
    await _ensure_cohort_slug_available(session, organization_id, slug)
    cohort = Cohort(
        organization_id=organization_id,
        slug=slug,
        name=payload.name,
        starts_at=payload.starts_at,
        ends_at=payload.ends_at,
    )
    session.add(cohort)
    await session.commit()
    await session.refresh(cohort)
    return await _cohort_out(session, cohort)


@router.get(
    "/organizations/{organization_id}/cohorts",
    response_model=list[CohortOut],
    response_class=JSONResponse,
    dependencies=[Depends(require_user_or_service_token)],
)
async def list_cohorts(
    organization_id: int,
    request: Request,
    session: AsyncSession = Depends(get_db_session),
) -> list[CohortOut]:
    user = await _current_user(request, session)
    await get_organization_or_404(session, organization_id)
    await require_org_member(session, organization_id=organization_id, user_id=user.id)
    cohorts = (
        await session.scalars(
            select(Cohort)
            .where(Cohort.organization_id == organization_id, Cohort.archived_at.is_(None))
            .order_by(Cohort.created_at.desc(), Cohort.id.desc())
        )
    ).all()
    return [await _cohort_out(session, cohort) for cohort in cohorts]


@router.get(
    "/organizations/{organization_id}/cohorts/{cohort_id}/members",
    response_model=list[CohortMemberOut],
    response_class=JSONResponse,
    dependencies=[Depends(require_user_or_service_token)],
)
async def list_cohort_members(
    organization_id: int,
    cohort_id: int,
    request: Request,
    session: AsyncSession = Depends(get_db_session),
) -> list[CohortMemberOut]:
    user = await _current_user(request, session)
    await get_cohort_or_404(session, organization_id=organization_id, cohort_id=cohort_id)
    await require_org_admin(session, organization_id=organization_id, user_id=user.id)
    rows = (
        await session.execute(
            select(CohortMembership, UserProfile.id)
            .join(User, User.id == CohortMembership.user_id)
            .join(UserProfile, UserProfile.user_id == User.id, isouter=True)
            .where(CohortMembership.cohort_id == cohort_id)
            .order_by(CohortMembership.joined_at.asc(), CohortMembership.id.asc())
        )
    ).all()
    return [
        CohortMemberOut(
            user_id=membership.user_id,
            status=membership.status,  # type: ignore[arg-type]
            has_profile=profile_id is not None,
            joined_at=membership.joined_at,
        )
        for membership, profile_id in rows
    ]


@router.patch(
    "/organizations/{organization_id}/cohorts/{cohort_id}/members/{member_user_id}",
    response_model=CohortMemberOut,
    response_class=JSONResponse,
    dependencies=[Depends(require_user_or_service_token)],
)
async def update_cohort_member(
    organization_id: int,
    cohort_id: int,
    member_user_id: int,
    payload: CohortMemberPatch,
    request: Request,
    session: AsyncSession = Depends(get_db_session),
) -> CohortMemberOut:
    user = await _current_user(request, session)
    await get_cohort_or_404(session, organization_id=organization_id, cohort_id=cohort_id)
    await require_org_admin(session, organization_id=organization_id, user_id=user.id)
    org_membership = await session.scalar(
        select(OrganizationMembership).where(
            OrganizationMembership.organization_id == organization_id,
            OrganizationMembership.user_id == member_user_id,
            OrganizationMembership.status == "active",
        )
    )
    if org_membership is None:
        raise org_error(409, "ORG_MEMBER_INACTIVE", "Участник должен быть активным в организации.")

    membership = await session.scalar(
        select(CohortMembership).where(
            CohortMembership.cohort_id == cohort_id,
            CohortMembership.user_id == member_user_id,
        )
    )
    if membership is None:
        raise org_error(404, "COHORT_MEMBER_NOT_FOUND", "Участник когорты не найден.")

    original_status = membership.status
    target_membership = membership
    moved_to_cohort_id: int | None = None
    if payload.target_cohort_id is not None and payload.target_cohort_id != cohort_id:
        await get_cohort_or_404(session, organization_id=organization_id, cohort_id=payload.target_cohort_id)
        membership.status = "revoked"
        moved_to_cohort_id = payload.target_cohort_id
        target_membership = await session.scalar(
            select(CohortMembership).where(
                CohortMembership.cohort_id == payload.target_cohort_id,
                CohortMembership.user_id == member_user_id,
            )
        )
        if target_membership is None:
            target_membership = CohortMembership(cohort_id=payload.target_cohort_id, user_id=member_user_id)
            session.add(target_membership)
            await session.flush()
        else:
            target_membership.status = "active"

    if payload.status is not None and moved_to_cohort_id is None:
        target_membership.status = payload.status

    _add_org_audit_event(
        session,
        actor_user_id=user.id,
        event_name="cohort_member_updated",
        organization_id=organization_id,
        metadata={
            "target_user_id": member_user_id,
            "from_cohort_id": cohort_id,
            "to_cohort_id": moved_to_cohort_id or cohort_id,
            "from_status": original_status,
            "to_status": target_membership.status,
            "moved": moved_to_cohort_id is not None,
        },
    )
    await session.commit()
    return await _cohort_member_out(session, target_membership)


@router.post(
    "/organizations/{organization_id}/invites",
    response_model=OrganizationInviteOut,
    response_class=JSONResponse,
    dependencies=[Depends(require_user_or_service_token)],
)
async def create_invite(
    organization_id: int,
    payload: OrganizationInviteIn,
    request: Request,
    session: AsyncSession = Depends(get_db_session),
) -> OrganizationInviteOut:
    user = await _current_user(request, session)
    await get_organization_or_404(session, organization_id)
    await require_org_admin(session, organization_id=organization_id, user_id=user.id)
    if payload.cohort_id is not None:
        await get_cohort_or_404(session, organization_id=organization_id, cohort_id=payload.cohort_id)
    token, token_hash = generate_invite_token()
    expires_at = ensure_aware_utc(payload.expires_at) or datetime.now(timezone.utc) + timedelta(
        days=DEFAULT_INVITE_TTL_DAYS
    )
    invite = OrganizationInvite(
        organization_id=organization_id,
        cohort_id=payload.cohort_id,
        token_hash=token_hash,
        role=payload.role,
        max_uses=payload.max_uses,
        expires_at=expires_at,
        created_by_user_id=user.id,
    )
    session.add(invite)
    await session.commit()
    await session.refresh(invite)
    return _invite_out(invite, token=token)


@router.get(
    "/organizations/{organization_id}/invites",
    response_model=list[OrganizationInviteOut],
    response_class=JSONResponse,
    dependencies=[Depends(require_user_or_service_token)],
)
async def list_invites(
    organization_id: int,
    request: Request,
    session: AsyncSession = Depends(get_db_session),
) -> list[OrganizationInviteOut]:
    user = await _current_user(request, session)
    await get_organization_or_404(session, organization_id)
    await require_org_admin(session, organization_id=organization_id, user_id=user.id)
    invites = (
        await session.scalars(
            select(OrganizationInvite)
            .where(OrganizationInvite.organization_id == organization_id)
            .order_by(OrganizationInvite.created_at.desc(), OrganizationInvite.id.desc())
        )
    ).all()
    return [_invite_out(invite) for invite in invites]


@router.delete(
    "/organizations/{organization_id}/invites/{invite_id}",
    response_model=OrganizationInviteOut,
    response_class=JSONResponse,
    dependencies=[Depends(require_user_or_service_token)],
)
async def revoke_invite(
    organization_id: int,
    invite_id: int,
    request: Request,
    session: AsyncSession = Depends(get_db_session),
) -> OrganizationInviteOut:
    user = await _current_user(request, session)
    await get_organization_or_404(session, organization_id)
    await require_org_admin(session, organization_id=organization_id, user_id=user.id)
    invite = await session.scalar(
        select(OrganizationInvite).where(
            OrganizationInvite.id == invite_id,
            OrganizationInvite.organization_id == organization_id,
        )
    )
    if invite is None:
        raise org_error(404, "INVITE_NOT_FOUND", "Инвайт не найден.")
    invite.revoked_at = invite.revoked_at or datetime.now(timezone.utc)
    await session.commit()
    await session.refresh(invite)
    return _invite_out(invite)


@router.post(
    "/invites/{invite_token}/accept",
    response_model=InviteAcceptOut,
    response_class=JSONResponse,
    dependencies=[Depends(require_user_or_service_token)],
)
async def accept_invite(
    invite_token: str,
    request: Request,
    session: AsyncSession = Depends(get_db_session),
) -> InviteAcceptOut:
    user = await _current_user(request, session)
    invite = await session.scalar(
        select(OrganizationInvite).where(OrganizationInvite.token_hash == invite_token_hash(invite_token))
    )
    if invite is None:
        raise org_error(404, "INVITE_NOT_FOUND", "Инвайт не найден.")
    now = datetime.now(timezone.utc)
    if invite.revoked_at is not None:
        raise org_error(410, "INVITE_REVOKED", "Инвайт отозван.")
    if ensure_aware_utc(invite.expires_at) < now:
        raise org_error(410, "INVITE_EXPIRED", "Срок действия инвайта истёк.")
    if invite.uses_count >= invite.max_uses:
        raise org_error(409, "INVITE_MAX_USES_REACHED", "Инвайт уже использован максимальное число раз.")

    organization = await get_organization_or_404(session, invite.organization_id)
    membership = await session.scalar(
        select(OrganizationMembership).where(
            OrganizationMembership.organization_id == invite.organization_id,
            OrganizationMembership.user_id == user.id,
        )
    )
    if membership is None:
        membership = OrganizationMembership(organization_id=invite.organization_id, user_id=user.id, role=invite.role)
        session.add(membership)
    else:
        membership.status = "active"
        if membership.role == "member" and invite.role == "admin":
            membership.role = "admin"

    cohort_payload = None
    if invite.cohort_id is not None:
        cohort = await get_cohort_or_404(
            session,
            organization_id=invite.organization_id,
            cohort_id=invite.cohort_id,
        )
        cohort_membership = await session.scalar(
            select(CohortMembership).where(
                CohortMembership.cohort_id == invite.cohort_id,
                CohortMembership.user_id == user.id,
            )
        )
        if cohort_membership is None:
            session.add(CohortMembership(cohort_id=invite.cohort_id, user_id=user.id))
        else:
            cohort_membership.status = "active"
        cohort_payload = cohort

    invite.uses_count += 1
    await session.commit()
    await session.refresh(membership)
    return InviteAcceptOut(
        organization=await _organization_out(session, organization, membership),
        cohort=await _cohort_out(session, cohort_payload) if cohort_payload is not None else None,
    )


@router.get(
    "/organizations/{organization_id}/cohorts/{cohort_id}/analytics",
    response_model=CohortAnalyticsOut,
    response_class=JSONResponse,
    dependencies=[Depends(require_user_or_service_token)],
)
async def get_cohort_analytics(
    organization_id: int,
    cohort_id: int,
    request: Request,
    days: int = Query(30, ge=1, le=366),
    session: AsyncSession = Depends(get_db_session),
    settings: Settings = Depends(get_settings_dependency),
) -> CohortAnalyticsOut:
    user = await _current_user(request, session)
    cohort = await get_cohort_or_404(session, organization_id=organization_id, cohort_id=cohort_id)
    await require_org_admin(session, organization_id=organization_id, user_id=user.id)
    return await build_cohort_analytics(
        session,
        organization_id=organization_id,
        cohort=cohort,
        days=days,
        min_cohort_n=settings.b2b_min_cohort_n,
        min_cell_n=settings.b2b_min_cell_n,
    )


@router.get(
    "/organizations/{organization_id}/cohorts/{cohort_id}/export.csv",
    response_class=StreamingResponse,
    dependencies=[Depends(require_user_or_service_token)],
)
async def export_cohort_analytics_csv(
    organization_id: int,
    cohort_id: int,
    request: Request,
    days: int = Query(30, ge=1, le=366),
    session: AsyncSession = Depends(get_db_session),
    settings: Settings = Depends(get_settings_dependency),
) -> StreamingResponse:
    user = await _current_user(request, session)
    cohort = await get_cohort_or_404(session, organization_id=organization_id, cohort_id=cohort_id)
    await require_org_admin(session, organization_id=organization_id, user_id=user.id)
    analytics = await build_cohort_analytics(
        session,
        organization_id=organization_id,
        cohort=cohort,
        days=days,
        min_cohort_n=settings.b2b_min_cohort_n,
        min_cell_n=settings.b2b_min_cell_n,
    )
    csv_payload = cohort_analytics_csv(analytics)
    return StreamingResponse(
        iter([csv_payload]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="cohort-{cohort.id}-analytics.csv"'},
    )
