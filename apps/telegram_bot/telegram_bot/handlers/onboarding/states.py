"""FSM states and shared constants for the onboarding and settings flows."""

from __future__ import annotations

from aiogram.fsm.state import State, StatesGroup

# ---------------------------------------------------------------------------
# FSM state groups
# ---------------------------------------------------------------------------


class ProfileOnboarding(StatesGroup):
    role = State()
    grade = State()
    city_tier = State()
    work_mode = State()
    domain = State()
    skills = State()
    confirm_skills = State()
    upload_resume = State()
    waiting_resume_file = State()


class ProfileSettings(StatesGroup):
    editing_skills = State()


# ---------------------------------------------------------------------------
# Default fallback options (used when meta API is unavailable)
# ---------------------------------------------------------------------------

DEFAULT_ROLES = ["Data Analyst", "Data Engineer", "Product Analyst"]
DEFAULT_GRADES = ["Junior", "Middle", "Senior"]
DEFAULT_CITY_TIERS = ["Tier-1", "Tier-2", "Tier-3"]
DEFAULT_WORK_MODES = ["Office", "Hybrid", "Remote"]
DEFAULT_DOMAINS = ["Fintech", "E-commerce", "EdTech"]

ONBOARDING_PAGE_SIZE = 6
ONBOARDING_STEPS = ("role", "grade", "city_tier", "work_mode", "domain", "skills", "confirm_skills")
ONBOARDING_TOTAL = len(ONBOARDING_STEPS)

# ---------------------------------------------------------------------------
# Callback data constants
# ---------------------------------------------------------------------------

CONFIRM_CALLBACK = "skills:confirm"
EDIT_CALLBACK = "skills:edit"
RESUME_UPLOAD_CALLBACK = "resume:upload"
RESUME_SKIP_CALLBACK = "resume:skip"
SETTINGS_FIELD_PREFIX = "settings:field"
SETTINGS_VALUE_PREFIX = "settings:value"
PROFILE_EDIT_CALLBACK = "profile:edit"
START_RESUME_CALLBACK = "start:resume"
START_RESTART_CALLBACK = "start:restart"
START_UPDATE_PROFILE_CALLBACK = "start:update"
START_KEEP_PROFILE_CALLBACK = "start:keep"

# ---------------------------------------------------------------------------
# Settings field definitions
# ---------------------------------------------------------------------------

SETTINGS_FIELDS = (
    ("target_role", "Роль"),
    ("target_grade", "Грейд"),
    ("target_city_tier", "Город"),
    ("target_work_mode", "Формат"),
    ("target_domain", "Домен"),
    ("current_skills", "Навыки"),
)
