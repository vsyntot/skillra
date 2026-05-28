"""Onboarding FSM handlers — main flow for profile creation and editing."""

from __future__ import annotations

import logging
import sys as _sys
from html import escape
from typing import Any, Awaitable, Callable

from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from telegram_bot import texts
from telegram_bot.keyboards.onboarding import (
    SKIP_DOMAIN_VALUE,
    PaginationCallbackFactory,
    SelectionCallbackFactory,
)
from telegram_bot.services.api_client import SkillraApiClient, track_product_event_safely
from telegram_bot.services.errors import SkillraApiError, user_message_from_error
from telegram_bot.services.meta_cache import MetaCache
from telegram_bot.services.skills import (
    build_skill_suggestions,
    normalize_skill_name,
    parse_skills,
)

from .keyboards import (
    build_menu_keyboard,
    build_profile_actions_keyboard,
    build_profile_exists_keyboard,
    build_resume_keyboard,
    build_resume_upload_keyboard,
    build_step_keyboard,
    settings_keyboard,
    settings_options_keyboard,
    skills_confirmation_keyboard,
)
from .states import (
    CONFIRM_CALLBACK,
    DEFAULT_CITY_TIERS,
    DEFAULT_DOMAINS,
    DEFAULT_GRADES,
    DEFAULT_ROLES,
    DEFAULT_WORK_MODES,
    EDIT_CALLBACK,
    ONBOARDING_STEPS,
    ONBOARDING_TOTAL,
    PROFILE_EDIT_CALLBACK,
    RESUME_SKIP_CALLBACK,
    RESUME_UPLOAD_CALLBACK,
    SETTINGS_FIELD_PREFIX,
    SETTINGS_VALUE_PREFIX,
    START_KEEP_PROFILE_CALLBACK,
    START_RESTART_CALLBACK,
    START_RESUME_CALLBACK,
    START_UPDATE_PROFILE_CALLBACK,
    ProfileOnboarding,
    ProfileSettings,
)
from .validators import is_settings_flow, match_user_value, validate_skills

logger = logging.getLogger(__name__)

_PKG_NAME = "telegram_bot.handlers.onboarding"


def _resolve(name: str, default: Any) -> Any:
    """Look up *name* via the parent package namespace at call time.

    This indirection allows tests to monkeypatch handlers via
    ``monkeypatch.setattr(onboarding, name, mock)`` without circular imports.
    """
    pkg = _sys.modules.get(_PKG_NAME)
    return getattr(pkg, name, default) if pkg else default


router = Router()
RESUME_MAX_BYTES = 10 * 1024 * 1024

# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------


def format_skill_confirmation(skills: list[str]) -> str:
    skills_list = ", ".join(escape(skill) for skill in skills)
    return "Мы распознали навыки: " f"<b>{skills_list}</b>\n" "Подтвердите список или введите заново."


def format_profile(profile: dict[str, Any]) -> str:
    lines = ["<b>Ваш профиль</b>"]
    lines.append(f"Роль: <b>{escape(profile.get('target_role') or '—')}</b>")
    lines.append(f"Грейд: <b>{escape(profile.get('target_grade') or '—')}</b>")
    lines.append(f"Город: <b>{escape(profile.get('target_city_tier') or '—')}</b>")
    detailed_geo = _format_detailed_geo(profile)
    if detailed_geo:
        lines.append(f"Гео: <b>{detailed_geo}</b>")
    lines.append(f"Формат работы: <b>{escape(profile.get('target_work_mode') or '—')}</b>")
    lines.append(f"Домен: <b>{escape(profile.get('target_domain') or '—')}</b>")

    skills = profile.get("current_skills") or []
    skills_text = ", ".join(escape(skill) for skill in skills) if skills else "—"
    lines.append(f"Навыки: <b>{skills_text}</b>")

    warnings = profile.get("warnings") or []
    if warnings:
        warning_text = "\n".join(f"• {escape(w)}" for w in warnings)
        lines.append(f"⚠️ Предупреждения:\n{warning_text}")

    return "\n".join(lines)


def _progress_line(step: str) -> str:
    if step not in ONBOARDING_STEPS:
        return ""
    current = ONBOARDING_STEPS.index(step) + 1
    filled = "●" * current
    empty = "○" * (ONBOARDING_TOTAL - current)
    return f"Шаг {current}/{ONBOARDING_TOTAL}: {filled}{empty}"


def _with_progress(step: str, prompt: str) -> str:
    line = _progress_line(step)
    return f"{line}\n{prompt}" if line else prompt


def build_profile_payload(user: Any, data: dict[str, Any]) -> dict[str, Any]:
    return {
        "username": getattr(user, "username", None),
        "target_role": data.get("target_role"),
        "target_grade": data.get("target_grade"),
        "target_city_tier": data.get("target_city_tier"),
        "target_country": data.get("target_country"),
        "target_region": data.get("target_region"),
        "target_city": data.get("target_city"),
        "target_geo_scope": data.get("target_geo_scope"),
        "target_work_mode": data.get("target_work_mode"),
        "target_domain": data.get("target_domain"),
        "current_skills": data.get("current_skills", []),
    }


def _format_detailed_geo(profile: dict[str, Any]) -> str:
    parts = [
        profile.get("target_country"),
        profile.get("target_region"),
        profile.get("target_city"),
        profile.get("target_geo_scope"),
    ]
    return " · ".join(escape(str(part)) for part in parts if part)


def _resume_validation_error(document: Any) -> str | None:
    file_size = getattr(document, "file_size", None)
    if file_size is not None and int(file_size) > RESUME_MAX_BYTES:
        return texts.resume_validation_error()

    mime_type = getattr(document, "mime_type", None)
    if mime_type and mime_type != "application/pdf":
        return texts.resume_validation_error()

    file_name = getattr(document, "file_name", None)
    if file_name and not str(file_name).lower().endswith(".pdf"):
        return texts.resume_validation_error()

    return None


def _format_resume_upload_result(skills: list[str], *, profile_updated: bool) -> str:
    if not skills:
        return texts.resume_skills_not_found()

    skills_preview = ", ".join(escape(skill) for skill in skills[:10])
    suffix = "\nПрофиль дополнен найденными навыками." if profile_updated else ""
    return f"Резюме загружено. Найдено навыков: <b>{len(skills)}</b>\n{skills_preview}{suffix}"


# ---------------------------------------------------------------------------
# Private helpers — options loading
# ---------------------------------------------------------------------------


def _step_options_config(
    step: str, api_client: SkillraApiClient, meta_cache: MetaCache
) -> tuple[Callable[[], Awaitable[list[str]]] | None, list[str]]:
    mapping: dict[str, tuple[Callable[[], Awaitable[list[str]]] | None, list[str]]] = {
        "role": (lambda: meta_cache.get_roles(api_client), DEFAULT_ROLES),
        "grade": (lambda: meta_cache.get_grades(api_client), DEFAULT_GRADES),
        "city_tier": (lambda: meta_cache.get_city_tiers(api_client), DEFAULT_CITY_TIERS),
        "work_mode": (lambda: meta_cache.get_work_modes(api_client), DEFAULT_WORK_MODES),
        "domain": (lambda: meta_cache.get_domains(api_client), DEFAULT_DOMAINS),
    }
    return mapping.get(step, (None, []))


def _setting_field_config(
    field: str, api_client: SkillraApiClient, meta_cache: MetaCache
) -> tuple[Callable[[], Awaitable[list[str]]] | None, list[str], str]:
    mapping = {
        "target_role": (lambda: meta_cache.get_roles(api_client), DEFAULT_ROLES, "Выберите новую роль:"),
        "target_grade": (lambda: meta_cache.get_grades(api_client), DEFAULT_GRADES, "Выберите новый грейд:"),
        "target_city_tier": (
            lambda: meta_cache.get_city_tiers(api_client),
            DEFAULT_CITY_TIERS,
            "Выберите уровень города:",
        ),
        "target_work_mode": (
            lambda: meta_cache.get_work_modes(api_client),
            DEFAULT_WORK_MODES,
            "Выберите формат работы:",
        ),
        "target_domain": (
            lambda: meta_cache.get_domains(api_client),
            DEFAULT_DOMAINS,
            "Выберите домен (можно пропустить):",
        ),
    }
    return mapping.get(field, (None, [], ""))


async def _ensure_options(fetcher: Callable[[], Awaitable[list[str]]], fallback: list[str]) -> list[str]:
    options = await fetcher()
    return options if options else fallback


async def _get_options_for_step(
    state: FSMContext,
    step: str,
    fetcher: Callable[[], Awaitable[list[str]]],
    fallback: list[str],
) -> list[str]:
    data = await state.get_data()
    key = f"{step}_options"
    if key in data:
        return data[key]

    try:
        options = await _ensure_options(fetcher, fallback)
    except Exception:  # noqa: BLE001
        logger.exception("Failed to load options for %s", step)
        options = fallback

    await state.update_data({key: options})
    return options


def _get_current_page(data: dict[str, Any], step: str) -> int:
    page = data.get(f"{step}_page")
    if isinstance(page, int) and page > 0:
        return page
    return 1


def _selection_flow(step: str) -> tuple[str | None, str, Any]:
    mapping = {
        "role": ("target_role", "Роль", _ask_grade),
        "grade": ("target_grade", "Грейд", _ask_city_tier),
        "city_tier": ("target_city_tier", "Город", _ask_work_mode),
        "work_mode": ("target_work_mode", "Формат работы", _ask_domain),
        "domain": ("target_domain", "Домен", None),
    }
    return mapping.get(step, (None, "", None))


def _parse_settings_field(data: str) -> str | None:
    parts = data.split(SelectionCallbackFactory.prefix_separator, maxsplit=2)
    if len(parts) != 3:
        return None
    _, _, field = parts
    return field


def _parse_settings_value(data: str) -> tuple[str, str] | None:
    parts = data.split(SelectionCallbackFactory.prefix_separator, maxsplit=3)
    if len(parts) != 4:
        return None
    _, _, field, value = parts
    return field, value


# ---------------------------------------------------------------------------
# Private helpers — ask step
# ---------------------------------------------------------------------------


async def _ask_with_options(
    message: Message,
    state: FSMContext,
    prompt: str,
    fetcher: Callable[[], Awaitable[list[str]]],
    fallback: list[str],
    step: str,
) -> None:
    options = await _get_options_for_step(state, step, fetcher, fallback)
    await state.update_data({f"{step}_page": 1})
    markup = build_step_keyboard(options, step, page=1)
    await message.answer(_with_progress(step, prompt), reply_markup=markup)


async def _ask_role(message: Message, state: FSMContext, api_client: SkillraApiClient, meta_cache: MetaCache) -> None:
    await state.set_state(ProfileOnboarding.role)
    await _ask_with_options(
        message,
        state,
        texts.onboarding_step_prompt("role"),
        fetcher=lambda: meta_cache.get_roles(api_client),
        fallback=DEFAULT_ROLES,
        step="role",
    )


async def _ask_grade(message: Message, state: FSMContext, api_client: SkillraApiClient, meta_cache: MetaCache) -> None:
    await state.set_state(ProfileOnboarding.grade)
    await _ask_with_options(
        message,
        state,
        texts.onboarding_step_prompt("grade"),
        fetcher=lambda: meta_cache.get_grades(api_client),
        fallback=DEFAULT_GRADES,
        step="grade",
    )


async def _ask_city_tier(
    message: Message, state: FSMContext, api_client: SkillraApiClient, meta_cache: MetaCache
) -> None:
    await state.set_state(ProfileOnboarding.city_tier)
    await _ask_with_options(
        message,
        state,
        texts.onboarding_step_prompt("city_tier"),
        fetcher=lambda: meta_cache.get_city_tiers(api_client),
        fallback=DEFAULT_CITY_TIERS,
        step="city_tier",
    )


async def _ask_work_mode(
    message: Message, state: FSMContext, api_client: SkillraApiClient, meta_cache: MetaCache
) -> None:
    await state.set_state(ProfileOnboarding.work_mode)
    await _ask_with_options(
        message,
        state,
        texts.onboarding_step_prompt("work_mode"),
        fetcher=lambda: meta_cache.get_work_modes(api_client),
        fallback=DEFAULT_WORK_MODES,
        step="work_mode",
    )


async def _ask_domain(message: Message, state: FSMContext, api_client: SkillraApiClient, meta_cache: MetaCache) -> None:
    await state.set_state(ProfileOnboarding.domain)
    await _ask_with_options(
        message,
        state,
        texts.onboarding_step_prompt("domain"),
        fetcher=lambda: meta_cache.get_domains(api_client),
        fallback=DEFAULT_DOMAINS,
        step="domain",
    )


async def _prompt_step_again(message: Message, state: FSMContext, step: str, options: list[str], prompt: str) -> None:
    data = await state.get_data()
    page = _get_current_page(data, step)
    markup = build_step_keyboard(options, step, page=page)
    await message.answer(
        f"Не удалось распознать ответ. Выберите значение из кнопок или введите вариант из списка.\n"
        f"{_with_progress(step, prompt)}",
        reply_markup=markup,
    )


async def _ask_setting_option(
    message: Message, api_client: SkillraApiClient, meta_cache: MetaCache, field: str
) -> None:
    fetcher, fallback, prompt = _setting_field_config(field, api_client, meta_cache)
    if fetcher is None:
        await message.answer("Неизвестный параметр для обновления.")
        return

    try:
        options = await _ensure_options(fetcher, fallback)
    except Exception:  # noqa: BLE001
        logger.exception("Failed to load options for %s", field)
        options = fallback

    await message.answer(
        prompt,
        reply_markup=settings_options_keyboard(options, field, allow_skip=field == "target_domain"),
    )


# ---------------------------------------------------------------------------
# Private helpers — error formatting
# ---------------------------------------------------------------------------


async def _format_upsert_error_message(
    exc: SkillraApiError,
    api_client: SkillraApiClient,
    meta_cache: MetaCache,
    *,
    default_message: str,
) -> str:
    payload = exc.payload
    if not isinstance(payload, dict):
        return user_message_from_error(exc, default_message)

    error_code = exc.error_code or payload.get("error_code")
    details = payload.get("details") or {}

    if error_code == "UNKNOWN_SKILLS":
        unknown = [normalize_skill_name(str(skill)) for skill in details.get("unknown_skills") or []]
        if unknown:
            suggestions = await build_skill_suggestions(unknown, api_client, meta_cache)
            return format_unknown_skills_message_local(unknown, suggestions)
        return "Некоторые навыки неизвестны. Исправьте список и попробуйте снова."

    return user_message_from_error(exc, default_message)


def format_unknown_skills_message_local(unknown: list[str], suggestions: dict) -> str:
    from telegram_bot.services.skills import format_unknown_skills_message

    return format_unknown_skills_message(
        unknown,
        suggestions,
        intro="Некоторые навыки неизвестны:",
        action_prompt="Исправьте список и попробуйте снова.",
    )


# ---------------------------------------------------------------------------
# Private helpers — flow helpers
# ---------------------------------------------------------------------------


def _merge_profile(profile: dict[str, Any], updates: dict[str, Any]) -> dict[str, Any]:
    merged = {
        "target_role": profile.get("target_role"),
        "target_grade": profile.get("target_grade"),
        "target_city_tier": profile.get("target_city_tier"),
        "target_country": profile.get("target_country"),
        "target_region": profile.get("target_region"),
        "target_city": profile.get("target_city"),
        "target_geo_scope": profile.get("target_geo_scope"),
        "target_work_mode": profile.get("target_work_mode"),
        "target_domain": profile.get("target_domain"),
        "current_skills": profile.get("current_skills", []),
        "username": profile.get("username"),
    }
    merged.update(updates)
    return merged


async def _start_new_onboarding(
    message: Message, state: FSMContext, api_client: SkillraApiClient, meta_cache: MetaCache
) -> None:
    await state.clear()
    await state.update_data(flow="onboarding")
    await message.answer(texts.welcome_message())
    await _ask_role(message, state, api_client, meta_cache)


async def _resume_onboarding(
    message: Message, state: FSMContext, api_client: SkillraApiClient, meta_cache: MetaCache
) -> None:
    state_name = await state.get_state()
    if not state_name:
        await _start_new_onboarding(message, state, api_client, meta_cache)
        return

    await message.answer("Продолжаем онбординг. Перейдём к текущему шагу.")

    # Use _resolve so that tests can monkeypatch individual _ask_* functions
    onboarding_steps = {
        ProfileOnboarding.role.state: _resolve("_ask_role", _ask_role),
        ProfileOnboarding.grade.state: _resolve("_ask_grade", _ask_grade),
        ProfileOnboarding.city_tier.state: _resolve("_ask_city_tier", _ask_city_tier),
        ProfileOnboarding.work_mode.state: _resolve("_ask_work_mode", _ask_work_mode),
        ProfileOnboarding.domain.state: _resolve("_ask_domain", _ask_domain),
    }

    handler = onboarding_steps.get(state_name)
    if handler:
        await handler(message, state, api_client, meta_cache)
        return

    if state_name == ProfileOnboarding.skills.state:
        await message.answer(_with_progress("skills", texts.skills_prompt()))
        return

    if state_name == ProfileOnboarding.confirm_skills.state:
        data = await state.get_data()
        skills = data.get("current_skills") or []
        if not skills:
            await state.set_state(ProfileOnboarding.skills)
            await message.answer(_with_progress("skills", texts.skills_prompt()))
            return
        await message.answer(
            _with_progress("confirm_skills", format_skill_confirmation(skills)),
            reply_markup=skills_confirmation_keyboard(),
        )
        return

    if state_name == ProfileSettings.editing_skills.state:
        await message.answer(texts.settings_skills_prompt())
        return

    await _start_new_onboarding(message, state, api_client, meta_cache)


async def _start_settings_flow(
    message: Message, telegram_user_id: int, api_client: SkillraApiClient, state: FSMContext
) -> None:
    try:
        profile = await api_client.get_profile(telegram_user_id)
    except SkillraApiError as exc:  # noqa: PERF203
        if exc.status_code == 404:
            await message.answer(texts.profile_not_found_onboarding())
            return
        logger.exception("Failed to load profile for settings")
        await message.answer(user_message_from_error(exc, "Не удалось получить профиль. Попробуйте позже."))
        return

    await state.clear()
    await state.update_data(flow="settings", profile=profile, telegram_user_id=telegram_user_id)
    await message.answer(format_profile(profile))
    await message.answer(texts.settings_intro_message(), reply_markup=settings_keyboard())


async def _handle_text_selection(
    message: Message,
    state: FSMContext,
    api_client: SkillraApiClient,
    meta_cache: MetaCache,
    *,
    step: str,
) -> None:
    user_input = message.text or ""
    fetcher, fallback = _step_options_config(step, api_client, meta_cache)
    if fetcher is None:
        await message.answer("Неизвестный шаг онбординга.")
        return

    options = await _get_options_for_step(state, step, fetcher, fallback)
    allow_skip = step == "domain"
    is_valid, matched = match_user_value(user_input, options, allow_skip=allow_skip)
    if not is_valid:
        await _prompt_step_again(message, state, step, options, texts.onboarding_step_prompt(step))
        return

    await _process_selection(message, state, api_client, meta_cache, step=step, value=matched, user=message.from_user)


async def _process_selection(
    message: Message,
    state: FSMContext,
    api_client: SkillraApiClient,
    meta_cache: MetaCache,
    *,
    step: str,
    value: str | None,
    user: Any | None,
) -> None:
    field, label, next_step = _selection_flow(step)
    if not field:
        return

    normalized_value = None if value == SKIP_DOMAIN_VALUE else value
    await state.update_data({field: normalized_value})
    confirmation = f"{label}: <b>{escape(normalized_value)}</b>" if normalized_value else f"{label}: пропущен"
    await message.answer(confirmation)

    data = await state.get_data()
    if is_settings_flow(data):
        await _save_profile_update(
            message, state, api_client, meta_cache, field=field, value=normalized_value, user=user
        )
        return

    if step == "domain":
        await state.set_state(ProfileOnboarding.skills)
        await message.answer(_with_progress("skills", texts.skills_prompt()))
        return

    if next_step:
        await next_step(message, state, api_client, meta_cache)


async def _save_profile_update(
    message: Message,
    state: FSMContext,
    api_client: SkillraApiClient,
    meta_cache: MetaCache,
    *,
    field: str,
    value: Any,
    user: Any | None = None,
) -> None:
    data = await state.get_data()
    profile = data.get("profile") or {}
    telegram_user_id = data.get("telegram_user_id") or (message.from_user.id if message.from_user else None)
    if telegram_user_id is None:
        await message.answer(texts.cannot_determine_user())
        return
    track_product_event_safely(api_client, telegram_user_id, "user_started", entity_type="onboarding")

    if not profile:
        try:
            profile = await api_client.get_profile(telegram_user_id)
        except SkillraApiError:
            logger.warning("Falling back to empty profile for update", exc_info=True)

    payload = build_profile_payload(user or message.from_user, _merge_profile(profile, {field: value}))
    try:
        saved_profile = await api_client.upsert_profile(telegram_user_id, payload)
    except SkillraApiError as exc:
        logger.exception("Failed to save profile update")
        await message.answer(
            await _format_upsert_error_message(
                exc,
                api_client,
                meta_cache,
                default_message="Не удалось сохранить профиль. Попробуйте позже.",
            )
        )
        return

    await state.update_data(profile=saved_profile, flow="settings")
    await message.answer("Профиль обновлён.\n" + format_profile(saved_profile), reply_markup=settings_keyboard())


async def _download_resume_bytes(bot: Bot, file_id: str) -> bytes:
    telegram_file = await bot.get_file(file_id)
    file_path = getattr(telegram_file, "file_path", None)
    if not file_path:
        msg = "Telegram file path is empty"
        raise RuntimeError(msg)

    downloaded = await bot.download_file(file_path)
    if isinstance(downloaded, bytes):
        return downloaded

    if hasattr(downloaded, "read"):
        content = downloaded.read()
        if isinstance(content, bytes):
            return content

    msg = "Telegram file download returned unsupported payload"
    raise RuntimeError(msg)


async def _merge_resume_skills_into_profile(
    api_client: SkillraApiClient,
    telegram_user_id: int,
    user: Any | None,
    skills: list[str],
) -> bool:
    if not skills or not hasattr(api_client, "get_profile") or not hasattr(api_client, "upsert_profile"):
        return False

    try:
        profile = await api_client.get_profile(telegram_user_id)
        current_skills = list(profile.get("current_skills") or [])
        merged_skills = current_skills.copy()
        normalized_existing = {str(skill).casefold() for skill in merged_skills}
        for skill in skills:
            if str(skill).casefold() not in normalized_existing:
                merged_skills.append(skill)
                normalized_existing.add(str(skill).casefold())

        if merged_skills == current_skills:
            return False

        payload = build_profile_payload(user, _merge_profile(profile, {"current_skills": merged_skills}))
        await api_client.upsert_profile(telegram_user_id, payload)
    except Exception:  # noqa: BLE001
        logger.exception("Failed to merge resume skills into profile")
        return False

    return True


async def _prompt_resume_upload_choice(message: Message, state: FSMContext, telegram_user_id: int) -> None:
    await state.update_data(telegram_user_id=telegram_user_id)
    await state.set_state(ProfileOnboarding.upload_resume)
    await message.answer(texts.resume_upload_offer(), reply_markup=build_resume_upload_keyboard())


async def _prompt_resume_file(message: Message, state: FSMContext, telegram_user_id: int) -> None:
    await state.update_data(telegram_user_id=telegram_user_id, flow="resume_upload")
    await state.set_state(ProfileOnboarding.waiting_resume_file)
    await message.answer(texts.resume_upload_prompt())


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------


@router.message(CommandStart())
async def start_onboarding(
    message: Message, state: FSMContext, api_client: SkillraApiClient, meta_cache: MetaCache
) -> None:
    telegram_user_id = message.from_user.id if message.from_user else None
    if telegram_user_id is None:
        await message.answer(texts.cannot_determine_user())
        return

    current_state = await state.get_state()
    if current_state:
        await message.answer(texts.resume_onboarding_message(), reply_markup=build_resume_keyboard())
        return

    try:
        profile = await api_client.get_profile(telegram_user_id)
    except SkillraApiError as exc:  # noqa: PERF203
        if exc.status_code != 404:
            logger.exception("Failed to fetch profile on /start")
            await message.answer(user_message_from_error(exc, "Не удалось получить профиль. Попробуйте позже."))
            return
        profile = None

    if profile is not None:
        message_text = texts.profile_exists_message()
        parse_mode = None
        if hasattr(api_client, "get_next_best_action"):
            try:
                from telegram_bot.handlers.commands import format_next_best_action_message  # noqa: PLC0415

                next_action = await api_client.get_next_best_action(telegram_user_id, source="bot")
                message_text = message_text + "\n\n" + format_next_best_action_message(next_action)
                parse_mode = "HTML"
            except Exception:  # noqa: BLE001
                logger.exception("Failed to fetch next best action on /start")
        await message.answer(
            message_text,
            parse_mode=parse_mode,
            reply_markup=build_profile_exists_keyboard(),
        )
        return

    await _start_new_onboarding(message, state, api_client, meta_cache)


@router.message(Command("profile"))
async def show_profile(message: Message, api_client: SkillraApiClient) -> None:
    telegram_user_id = message.from_user.id if message.from_user else None
    if telegram_user_id is None:
        await message.answer(texts.cannot_determine_user())
        return

    try:
        profile = await api_client.get_profile(telegram_user_id)
    except SkillraApiError as exc:  # noqa: PERF203
        if exc.status_code == 404:
            await message.answer(texts.profile_not_found())
            return
        logger.exception("Failed to fetch profile")
        await message.answer(user_message_from_error(exc, "Не удалось получить профиль. Попробуйте позже."))
        return

    await message.answer(format_profile(profile), reply_markup=build_profile_actions_keyboard())


@router.callback_query(F.data == PROFILE_EDIT_CALLBACK)
async def edit_profile(callback: CallbackQuery, api_client: SkillraApiClient, state: FSMContext) -> None:
    await callback.answer()
    message = callback.message
    telegram_user_id = callback.from_user.id if callback.from_user else None

    if not message:
        return

    if telegram_user_id is None:
        await message.answer(texts.cannot_determine_user())
        return

    await _start_settings_flow(message, telegram_user_id, api_client, state)


@router.message(Command("settings"))
async def open_settings(message: Message, api_client: SkillraApiClient, state: FSMContext) -> None:
    telegram_user_id = message.from_user.id if message.from_user else None
    if telegram_user_id is None:
        await message.answer(texts.cannot_determine_user())
        return

    await _start_settings_flow(message, telegram_user_id, api_client, state)


@router.message(Command("delete_me"))
async def delete_profile(message: Message, api_client: SkillraApiClient, state: FSMContext) -> None:
    telegram_user_id = message.from_user.id if message.from_user else None
    if telegram_user_id is None:
        await message.answer(texts.cannot_determine_user())
        return

    try:
        await api_client.delete_profile(telegram_user_id)
    except SkillraApiError as exc:  # noqa: PERF203
        if exc.status_code == 404:
            await message.answer("Профиль уже удалён или не найден.")
            return
        logger.exception("Failed to delete profile")
        await message.answer(user_message_from_error(exc, "Не удалось удалить профиль. Попробуйте позже."))
        return

    await state.clear()
    await message.answer(texts.profile_deleted_message())


@router.callback_query(F.data.startswith("role:"))
async def select_role(
    callback: CallbackQuery, state: FSMContext, api_client: SkillraApiClient, meta_cache: MetaCache
) -> None:
    await callback.answer()
    selection = SelectionCallbackFactory.unpack(callback.data or "")
    if not selection or not callback.message:
        return
    _, value = selection
    await _resolve("_process_selection", _process_selection)(
        callback.message, state, api_client, meta_cache, step="role", value=value, user=callback.from_user
    )


@router.callback_query(F.data.startswith("grade:"))
async def select_grade(
    callback: CallbackQuery, state: FSMContext, api_client: SkillraApiClient, meta_cache: MetaCache
) -> None:
    await callback.answer()
    selection = SelectionCallbackFactory.unpack(callback.data or "")
    if not selection or not callback.message:
        return
    _, value = selection
    await _resolve("_process_selection", _process_selection)(
        callback.message, state, api_client, meta_cache, step="grade", value=value, user=callback.from_user
    )


@router.callback_query(F.data.startswith("city_tier:"))
async def select_city_tier(
    callback: CallbackQuery, state: FSMContext, api_client: SkillraApiClient, meta_cache: MetaCache
) -> None:
    await callback.answer()
    selection = SelectionCallbackFactory.unpack(callback.data or "")
    if not selection or not callback.message:
        return
    _, value = selection
    await _resolve("_process_selection", _process_selection)(
        callback.message, state, api_client, meta_cache, step="city_tier", value=value, user=callback.from_user
    )


@router.callback_query(F.data.startswith("work_mode:"))
async def select_work_mode(
    callback: CallbackQuery, state: FSMContext, api_client: SkillraApiClient, meta_cache: MetaCache
) -> None:
    await callback.answer()
    selection = SelectionCallbackFactory.unpack(callback.data or "")
    if not selection or not callback.message:
        return
    _, value = selection
    await _resolve("_process_selection", _process_selection)(
        callback.message, state, api_client, meta_cache, step="work_mode", value=value, user=callback.from_user
    )


@router.callback_query(F.data.startswith("domain:"))
async def select_domain(
    callback: CallbackQuery, state: FSMContext, api_client: SkillraApiClient, meta_cache: MetaCache
) -> None:
    await callback.answer()
    selection = SelectionCallbackFactory.unpack(callback.data or "")
    if not selection or not callback.message:
        return
    _, value = selection
    await _resolve("_process_selection", _process_selection)(
        callback.message, state, api_client, meta_cache, step="domain", value=value, user=callback.from_user
    )


@router.callback_query(F.data.startswith(f"{PaginationCallbackFactory.prefix}:"))
async def paginate_onboarding_options(
    callback: CallbackQuery, state: FSMContext, api_client: SkillraApiClient, meta_cache: MetaCache
) -> None:
    await callback.answer()
    selection = PaginationCallbackFactory.unpack(callback.data or "")
    if not selection or not callback.message:
        return

    step, page = selection
    fetcher, fallback = _step_options_config(step, api_client, meta_cache)
    if fetcher is None:
        return

    options = await _get_options_for_step(state, step, fetcher, fallback)
    await state.update_data({f"{step}_page": page})
    markup = build_step_keyboard(options, step, page=page)
    await callback.message.edit_reply_markup(reply_markup=markup)


@router.message(ProfileOnboarding.role)
async def handle_role_text(
    message: Message, state: FSMContext, api_client: SkillraApiClient, meta_cache: MetaCache
) -> None:
    await _handle_text_selection(message, state, api_client, meta_cache, step="role")


@router.message(ProfileOnboarding.grade)
async def handle_grade_text(
    message: Message, state: FSMContext, api_client: SkillraApiClient, meta_cache: MetaCache
) -> None:
    await _handle_text_selection(message, state, api_client, meta_cache, step="grade")


@router.message(ProfileOnboarding.city_tier)
async def handle_city_tier_text(
    message: Message, state: FSMContext, api_client: SkillraApiClient, meta_cache: MetaCache
) -> None:
    await _handle_text_selection(message, state, api_client, meta_cache, step="city_tier")


@router.message(ProfileOnboarding.work_mode)
async def handle_work_mode_text(
    message: Message, state: FSMContext, api_client: SkillraApiClient, meta_cache: MetaCache
) -> None:
    await _handle_text_selection(message, state, api_client, meta_cache, step="work_mode")


@router.message(ProfileOnboarding.domain)
async def handle_domain_text(
    message: Message, state: FSMContext, api_client: SkillraApiClient, meta_cache: MetaCache
) -> None:
    await _handle_text_selection(message, state, api_client, meta_cache, step="domain")


@router.message(ProfileOnboarding.skills)
async def parse_skills_input(
    message: Message, state: FSMContext, api_client: SkillraApiClient, meta_cache: MetaCache
) -> None:
    text_input = (message.text or "").strip()

    # Sprint-009 TASK-08: If input looks like a partial skill query (no commas, short),
    # show MeiliSearch autocomplete suggestions instead of immediately parsing
    if text_input and "," not in text_input and len(text_input) < 40:
        suggestions: list[str] = []
        if len(text_input) >= 2:
            try:
                result = await api_client.search_skills(text_input, limit=5)
                raw = result.get("hits") or result.get("skills") or []
                if isinstance(raw, list):
                    suggestions = [s.get("name", s) if isinstance(s, dict) else str(s) for s in raw[:5] if s]
            except Exception:  # noqa: BLE001
                pass  # graceful degradation — continue without suggestions

        if suggestions:
            from aiogram.utils.keyboard import InlineKeyboardBuilder as _Builder

            builder = _Builder()
            for skill in suggestions:
                builder.button(text=f"+ {skill}", callback_data=f"skill_add:{skill}")
            builder.button(text="✅ Готово (ввести вручную)", callback_data="skill_manual_confirm")
            builder.adjust(2)
            await message.answer(
                f"Вы ввели: <b>{escape(text_input)}</b>\n\nПодсказки:",
                reply_markup=builder.as_markup(),
                parse_mode="HTML",
            )
            await state.update_data(_skill_partial=text_input)
            return

    skills = parse_skills(text_input)
    if not skills:
        await message.answer("Не удалось распознать навыки. Пожалуйста, перечислите их через запятую.")
        return

    is_valid, error_message = await validate_skills(skills, api_client, meta_cache)
    if not is_valid:
        await message.answer(error_message)
        return

    await state.update_data(current_skills=skills)
    await state.set_state(ProfileOnboarding.confirm_skills)
    await message.answer(
        _with_progress("confirm_skills", format_skill_confirmation(skills)),
        reply_markup=skills_confirmation_keyboard(),
    )


@router.callback_query(ProfileOnboarding.skills, F.data.startswith("skill_add:"))
async def skill_autocomplete_add(
    callback: CallbackQuery, state: FSMContext, api_client: SkillraApiClient, meta_cache: MetaCache
) -> None:
    """Sprint-009 TASK-08: Add a suggested skill from autocomplete inline button."""
    await callback.answer()
    if not callback.data:
        return
    skill_name = callback.data.removeprefix("skill_add:")
    data = await state.get_data()
    existing: list[str] = list(data.get("current_skills") or [])
    if skill_name not in existing:
        existing.append(skill_name)
    await state.update_data(current_skills=existing, _skill_partial=None)
    if callback.message:
        await callback.message.answer(
            f"✅ Добавлен: <b>{escape(skill_name)}</b>\n"
            f"Текущий список: {', '.join(escape(s) for s in existing)}\n\n"
            "Введите ещё навык или нажмите <code>/skills_done</code> для завершения.",
            parse_mode="HTML",
        )


@router.callback_query(ProfileOnboarding.skills, F.data == "skill_manual_confirm")
async def skill_manual_confirm(
    callback: CallbackQuery, state: FSMContext, api_client: SkillraApiClient, meta_cache: MetaCache
) -> None:
    """Sprint-009 TASK-08: User chose to enter skills manually (dismiss autocomplete)."""
    await callback.answer()
    if callback.message:
        await callback.message.answer("Введите навыки через запятую (например: Python, SQL, Docker):")


@router.callback_query(F.data == CONFIRM_CALLBACK)
async def confirm_skills(
    callback: CallbackQuery, state: FSMContext, api_client: SkillraApiClient, meta_cache: MetaCache
) -> None:
    await callback.answer()
    if not callback.message or not callback.from_user:
        return

    data = await state.get_data()
    payload = build_profile_payload(callback.from_user, data)
    try:
        profile = await api_client.upsert_profile(callback.from_user.id, payload)
    except SkillraApiError as exc:
        logger.exception("Failed to save profile")
        await callback.message.answer(
            await _format_upsert_error_message(
                exc,
                api_client,
                meta_cache,
                default_message="Не удалось сохранить профиль. Попробуйте позже.",
            )
        )
        return

    await callback.message.answer(texts.profile_saved_message())
    await callback.message.answer(format_profile(profile))
    await state.update_data(telegram_user_id=callback.from_user.id, profile=profile)
    await _prompt_resume_upload_choice(callback.message, state, callback.from_user.id)


@router.callback_query(ProfileOnboarding.upload_resume, F.data.in_({RESUME_SKIP_CALLBACK, RESUME_UPLOAD_CALLBACK}))
async def handle_resume_choice(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    if not callback.message or not callback.from_user:
        return

    if callback.data == RESUME_SKIP_CALLBACK:
        await state.clear()
        await callback.message.answer("Профиль сохранён.", reply_markup=build_menu_keyboard())
        await callback.message.answer(texts.menu_message())
        return

    await _prompt_resume_file(callback.message, state, callback.from_user.id)


@router.message(Command("resume"))
async def start_resume_upload(message: Message, state: FSMContext) -> None:
    telegram_user_id = message.from_user.id if message.from_user else None
    if telegram_user_id is None:
        await message.answer(texts.cannot_determine_user())
        return

    await state.clear()
    await _prompt_resume_file(message, state, telegram_user_id)


@router.message(ProfileOnboarding.waiting_resume_file, F.document)
async def handle_resume_document(
    message: Message,
    state: FSMContext,
    api_client: SkillraApiClient,
    bot: Bot,
) -> None:
    document = message.document
    if document is None:
        await message.answer(texts.resume_validation_error())
        return

    validation_error = _resume_validation_error(document)
    if validation_error:
        await message.answer(validation_error)
        return

    data = await state.get_data()
    telegram_user_id = data.get("telegram_user_id") or (message.from_user.id if message.from_user else None)
    if telegram_user_id is None:
        await message.answer(texts.cannot_determine_user())
        return

    await message.answer(texts.resume_upload_started())

    try:
        file_bytes = await _download_resume_bytes(bot, document.file_id)
    except Exception:  # noqa: BLE001
        logger.exception("Failed to download resume from Telegram")
        await message.answer("Не удалось скачать файл из Telegram. Попробуйте позже.")
        return

    if len(file_bytes) > RESUME_MAX_BYTES:
        await message.answer(texts.resume_validation_error())
        return

    file_name = getattr(document, "file_name", None) or "resume.pdf"
    try:
        result = await api_client.upload_user_resume(int(telegram_user_id), file_bytes, file_name)
    except SkillraApiError as exc:
        logger.exception("Failed to upload resume")
        await message.answer(user_message_from_error(exc, "Не удалось загрузить резюме. Попробуйте позже."))
        return

    extracted_skills = [str(skill) for skill in result.get("extracted_skills", []) if skill]
    profile_updated = await _merge_resume_skills_into_profile(
        api_client,
        int(telegram_user_id),
        message.from_user,
        extracted_skills,
    )
    await state.clear()
    await message.answer(
        _format_resume_upload_result(extracted_skills, profile_updated=profile_updated),
        reply_markup=build_menu_keyboard(),
    )


@router.message(ProfileOnboarding.waiting_resume_file)
async def handle_resume_non_document(message: Message) -> None:
    await message.answer(texts.resume_validation_error())


@router.callback_query(F.data == START_RESUME_CALLBACK)
async def resume_onboarding(
    callback: CallbackQuery, state: FSMContext, api_client: SkillraApiClient, meta_cache: MetaCache
) -> None:
    await callback.answer()
    if not callback.message:
        return
    await _resume_onboarding(callback.message, state, api_client, meta_cache)


@router.callback_query(F.data == START_RESTART_CALLBACK)
async def restart_onboarding(
    callback: CallbackQuery, state: FSMContext, api_client: SkillraApiClient, meta_cache: MetaCache
) -> None:
    await callback.answer()
    if not callback.message:
        return
    await _start_new_onboarding(callback.message, state, api_client, meta_cache)


@router.callback_query(F.data == START_UPDATE_PROFILE_CALLBACK)
async def update_profile_from_start(
    callback: CallbackQuery, state: FSMContext, api_client: SkillraApiClient, meta_cache: MetaCache
) -> None:
    await callback.answer()
    if not callback.message or not callback.from_user:
        return
    await _start_settings_flow(callback.message, callback.from_user.id, api_client, state)


@router.callback_query(F.data == START_KEEP_PROFILE_CALLBACK)
async def keep_profile_from_start(callback: CallbackQuery) -> None:
    await callback.answer()
    if not callback.message:
        return
    await callback.message.answer("Оставляем профиль без изменений.", reply_markup=build_menu_keyboard())
    await callback.message.answer(texts.menu_message())


@router.callback_query(F.data == EDIT_CALLBACK)
async def edit_skills(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.set_state(ProfileOnboarding.skills)
    if callback.message:
        await callback.message.answer(_with_progress("skills", "Введите навыки заново через запятую."))


@router.callback_query(F.data.startswith(f"{SETTINGS_FIELD_PREFIX}:"))
async def choose_setting_field(
    callback: CallbackQuery, state: FSMContext, api_client: SkillraApiClient, meta_cache: MetaCache
) -> None:
    await callback.answer()
    field = _parse_settings_field(callback.data or "")
    if not field or not callback.message:
        return

    if field == "current_skills":
        await state.set_state(ProfileSettings.editing_skills)
        await callback.message.answer(texts.settings_skills_prompt())
        return

    await _ask_setting_option(callback.message, api_client, meta_cache, field)


@router.callback_query(F.data.startswith(f"{SETTINGS_VALUE_PREFIX}:"))
async def apply_setting_value(
    callback: CallbackQuery, state: FSMContext, api_client: SkillraApiClient, meta_cache: MetaCache
) -> None:
    await callback.answer()
    parsed = _parse_settings_value(callback.data or "")
    if not parsed or not callback.message:
        return
    field, value = parsed
    normalized_value = None if value == SKIP_DOMAIN_VALUE else value
    await _save_profile_update(
        callback.message,
        state,
        api_client,
        meta_cache,
        field=field,
        value=normalized_value,
        user=callback.from_user,
    )


@router.message(ProfileSettings.editing_skills)
async def edit_skills_from_settings(
    message: Message, state: FSMContext, api_client: SkillraApiClient, meta_cache: MetaCache
) -> None:
    skills = parse_skills(message.text or "")
    if not skills:
        await message.answer("Не удалось распознать навыки. Пожалуйста, перечислите их через запятую.")
        return

    is_valid, error_message = await validate_skills(skills, api_client, meta_cache)
    if not is_valid:
        await message.answer(error_message)
        return

    await _save_profile_update(
        message,
        state,
        api_client,
        meta_cache,
        field="current_skills",
        value=skills,
        user=message.from_user,
    )
    await state.set_state(None)
