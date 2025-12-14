"""Консольный скрапер IT-вакансий HH.ru.

Собирает только вакансии с указанной зарплатой и выгружает расширенный
CSV со структурированными полями. Парсер работает на BeautifulSoup и
включает обход типичных ограничений HH (ротация user-agent, опциональные
прокси, джиттер задержек и HTTP-повторы).
"""

import argparse
import csv
import html as html_lib
import json
import os
import random
import re
import time
from datetime import datetime, timedelta, timezone
from dataclasses import asdict, dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


SEARCH_URL = "https://hh.ru/search/vacancy"
VACANCY_HOST = "https://hh.ru"
DEFAULT_AREA_IDS: Sequence[int] = (
    113,  # Russia
    40,  # Belarus
    159,  # Kazakhstan
    160,  # Armenia
    5,  # Ukraine
    204,  # Azerbaijan
    237,  # Uzbekistan
    246,  # Kyrgyzstan
    111,  # Moldova
    51,  # Georgia
    194,  # Tajikistan
    218,  # Turkmenistan
)
DEFAULT_QUERY = (
    'NAME:('
    # разработка / программирование / QA / data / ML
    'программист OR разработчик OR !developer OR "software engineer" '
    'OR "software developer" OR "инженер-программист" OR devops '
    'OR "data engineer" OR "data scientist" OR "ML engineer" '
    'OR тестировщик OR "QA engineer" OR "QA automation" '
    'OR "automation QA" OR "инженер по автоматизации тестирования" '
    'OR тестир* '

    # SRE / платформенные / инфраструктура
    'OR "site reliability engineer" OR SRE OR "platform engineer" '
    'OR "infrastructure engineer" OR "инженер инфраструктуры" '

    # сисадмины / сети / эксплуатация / support
    'OR "system administrator" OR "system engineer" '
    'OR "системный администратор" OR "сисадмин" OR "системный инженер" '
    'OR "сетевой инженер" OR "сетевой администратор" OR "network engineer" '
    'OR "инженер по эксплуатации" OR "инженер сопровождения" '
    'OR "инженер технической поддержки" OR "инженер поддержки" '
    'OR "специалист технической поддержки" OR "специалист техподдержки" '
    'OR "support engineer" OR "technical support engineer" '
    'OR "IT support engineer" OR "helpdesk engineer" '

    # базы данных / DBA
    'OR "администратор баз данных" OR "администратор БД" OR DBA '
    'OR "database administrator" OR "database engineer" '

    # информационная безопасность
    'OR "инженер по информационной безопасности" '
    'OR "инженер информационной безопасности" '
    'OR "специалист по информационной безопасности" '
    'OR "security engineer" OR DevSecOps '

    # data / BI / аналитика
    'OR "data analyst" OR "аналитик данных" OR "product analyst" '
    'OR "BI аналитик" OR "BI-аналитик" OR "BI analyst" '
    'OR "BI разработчик" OR "BI-разработчик" OR "BI developer" '
    'OR "ETL разработчик" OR "ETL developer" OR "ETL-инженер" '
    'OR "ETL engineer" OR "DWH разработчик" OR "data warehouse developer" '
    'OR "системный аналитик" OR "system analyst" '

    # архитекторы
    'OR "solution architect" OR "software architect" OR "system architect" '
    'OR "архитектор решений" OR "архитектор ПО" '
    'OR "архитектор программного обеспечения" OR "архитектор ИТ" '
    ')'
)
DEFAULT_LIMIT = 10000


def default_output_path() -> str:
    timestamp = datetime.now().strftime("%Y_%m_%d_%H_%M_%S")
    return os.path.join("data", f"hh_moscow_it_{timestamp}.csv")


DEFAULT_OUTPUT = default_output_path()
USER_AGENTS: Sequence[str] = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_3_1) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/16.4 Safari/605.1.15",
    "Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:122.0) Gecko/20100101 Firefox/122.0",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_2 like Mac OS X) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.2 Mobile/15E148 Safari/604.1",
)
CURRENCY_HINTS = {
    "руб": "RUB",
    "₽": "RUB",
    "USD": "USD",
    "EUR": "EUR",
    "$": "USD",
    "€": "EUR",
    "KZT": "KZT",
}

EXPERIENCE_SHARDS: Sequence[Optional[str]] = (
    None,
    "noExperience",
    "between1And3",
    "between3And6",
    "moreThan6",
)

GRADE_KEYWORDS = {
    "intern": [r"\bintern\b", r"\bстаж[её]р\b"],
    "junior": [r"\bjunior\b", r"\bмладший\b", r"\bджуниор\b", r"\bджун\b"],
    "middle": [r"\bmiddle\+?\b", r"\bмидл\b", r"\bmid\b"],
    "senior": [r"\bsenior\+?\b", r"\bсеньор\b", r"\bсиньор\b", r"\bстарший\b"],
    "lead": [
        r"\bteam\s*lead\b",
        r"\btech(nical)?\s*lead\b",
        r"\bтим[- ]?лид\b",
        r"\bведущ(ий|ая)\b",
    ],
    "architect": [r"\barchitect\b", r"\bархитектор\b"],
}

LEAD_STOPWORDS = ["lead generation", "лидогенера"]

ROLE_KEYWORDS = {
    "role_backend": ["backend", "back-end", "бекенд", "бэкенд"],
    "role_frontend": ["frontend", "front-end", "фронтенд", "frontend-разработчик"],
    "role_fullstack": ["fullstack", "full-stack", "фуллстек", "фул-стек"],
    "role_mobile": ["android", "ios", "mobile", "мобиль", "swift", "kotlin"],
    "role_data": ["data engineer", "etl", "dwh", "bi-", "bi ", "dwh "],
    "role_ml": ["machine learning", "ml ", "ml-", "data scientist", "нейросет"],
    "role_devops": ["devops", "sre", "site reliability", "platform engineer"],
    "role_qa": ["qa", "тестир", "quality assurance", "тестиров"],
    "role_manager": ["project manager", "delivery", "scrum", "agile coach", "pm "],
    "role_product": ["product manager", "продакт", "product owner", "po "],
    "role_analyst": ["аналитик", "analyst", "bi", "системный аналитик", "бизнес-аналитик"],
}

TECH_KEYWORDS = {
    "has_python": ["python"],
    "has_java": [" java"],
    "has_kotlin": ["kotlin"],
    "has_csharp": ["c#", ".net", "dotnet"],
    "has_cpp": ["c++"],
    "has_go": [" golang", " go "],
    "has_php": ["php"],
    "has_javascript": ["javascript", " js"],
    "has_typescript": ["typescript", " ts"],
    "has_scala": ["scala"],
    "has_rust": ["rust"],
    "has_ruby": ["ruby", "rails"],
    "has_django": ["django"],
    "has_flask": ["flask"],
    "has_fastapi": ["fastapi"],
    "has_dotnet": [".net", "dotnet"],
    "has_spring": ["spring"],
    "has_nodejs": ["node.js", "nodejs", "node js"],
    "has_express": ["express"],
    "has_nestjs": ["nestjs"],
    "has_react": ["react"],
    "has_vue": ["vue"],
    "has_angular": ["angular"],
    "has_nextjs": ["next.js", "nextjs"],
    "has_nuxt": ["nuxt"],
    "has_svelte": ["svelte"],
    "has_pandas": ["pandas"],
    "has_numpy": ["numpy"],
    "has_sklearn": ["sklearn", "scikit"],
    "has_pytorch": ["pytorch"],
    "has_tensorflow": ["tensorflow"],
    "has_airflow": ["airflow"],
    "has_spark": ["spark"],
    "has_kafka": ["kafka"],
    "has_docker": ["docker"],
    "has_kubernetes": ["kubernetes", "k8s"],
    "has_terraform": ["terraform"],
    "has_ansible": ["ansible"],
    "has_jenkins": ["jenkins"],
    "has_gitlab_ci": ["gitlab ci", "gitlab-ci"],
    "has_cicd": ["ci/cd", "ci cd", "continuous integration", "continuous delivery"],
}

BENEFIT_KEYWORDS = {
    "benefit_dms": ["дмс", "медицинск", "медстрах"],
    "benefit_insurance": ["страховка", "страхование"],
    "benefit_sick_leave_paid": ["оплачиваемые больничные", "оплачиваемый больничный"],
    "benefit_vacation_paid": ["оплачиваемый отпуск", "оплачиваемые отпуска"],
    "benefit_relocation": ["релокац", "переезд"],
    "benefit_sport": ["спорт", "фитнес", "спортзал", "доступ в фитнес"],
    "benefit_education": ["обучени", "курсы", "конференц", "митап"],
    "benefit_remote_compensation": ["компенсац", "интернет", "электричества"],
    "benefit_stock": ["опционы", "rsu", "акци", "опцион"],
}

DATA_SKILL_KEYWORDS = {
    "skill_sql": [
        " sql",
        "postgres",
        "postgresql",
        "mysql",
        "mariadb",
        "mssql",
        "sql server",
        "oracle",
        "clickhouse",
        "bigquery",
    ],
    "skill_excel": ["excel", "ms excel"],
    "skill_powerbi": ["powerbi", "power bi"],
    "skill_tableau": ["tableau"],
    "skill_clickhouse": ["clickhouse"],
    "skill_bigquery": ["bigquery"],
    "skill_r": [" язык r", " r ", " r,", " r.", "rstudio"],
    "skill_airflow": ["airflow"],
    "skill_ab_testing": ["a/b", "ab test", "a/b тест", "a/b-тест"],
    "skill_product_metrics": [
        "продуктов", "метрик", "конверси", "воронк", "ltv", "retention", "unit-эконом",
    ],
}

SOFT_SKILL_KEYWORDS = {
    "soft_communication": ["коммуникац", "общени"],
    "soft_teamwork": ["команд", "team"],
    "soft_leadership": ["лидер", "leadership", "руководств"],
    "soft_result_oriented": ["результат", "result oriented", "ориентаци"],
    "soft_structured_thinking": ["структур", "структурное мышление"],
    "soft_critical_thinking": ["критическ", "critical thinking"],
}

DOMAIN_KEYWORDS = {
    "domain_finance": ["банк", "финтех", "финансов"],
    "domain_ecommerce": ["ecommerce", "маркетплейс", "marketplace", "e-commerce"],
    "domain_telecom": ["телеком", "operator", "оператор связи"],
    "domain_state": ["госкомпания", "государствен"],
    "domain_retail": ["ритейл", "retail", "магазин"],
    "domain_it_product": ["saas", "продуктов", "it-продукт", "digital product"],
}


@dataclass
class VacancyRecord:
    vacancy_id: str
    title: str
    company: str
    salary_from: Optional[int]
    salary_to: Optional[int]
    currency: Optional[str]
    salary_gross: Optional[bool]
    salary_mid: Optional[float]
    salary_range_width: Optional[int]
    salary_is_exact: bool
    city: str
    address: str
    has_metro: bool
    metro_primary: str
    metro_count: int
    address_has_district: bool
    search_area_id: int
    experience: str
    exp_min_years: Optional[int]
    exp_max_years: Optional[int]
    exp_is_no_experience: bool
    employment_type: str
    schedule: str
    work_format_raw: str
    work_format: str
    is_remote: bool
    is_hybrid: bool
    description: str
    description_len_chars: int
    description_len_words: int
    description_bullets_count: int
    description_paragraphs_count: int
    requirements_count: int
    responsibilities_count: int
    optional_skills_count: int
    must_have_skills_count: int
    skills: str
    skills_count: int
    published_at_raw: str
    published_at_iso: Optional[str]
    vacancy_age_days: Optional[int]
    scraped_at_utc: str
    vacancy_code: str
    grade: str
    role_backend: bool
    role_frontend: bool
    role_fullstack: bool
    role_mobile: bool
    role_data: bool
    role_ml: bool
    role_devops: bool
    role_qa: bool
    role_manager: bool
    role_product: bool
    role_analyst: bool
    has_python: bool
    has_java: bool
    has_kotlin: bool
    has_csharp: bool
    has_cpp: bool
    has_go: bool
    has_php: bool
    has_javascript: bool
    has_typescript: bool
    has_scala: bool
    has_rust: bool
    has_ruby: bool
    has_django: bool
    has_flask: bool
    has_fastapi: bool
    has_dotnet: bool
    has_spring: bool
    has_nodejs: bool
    has_express: bool
    has_nestjs: bool
    has_react: bool
    has_vue: bool
    has_angular: bool
    has_nextjs: bool
    has_nuxt: bool
    has_svelte: bool
    has_pandas: bool
    has_numpy: bool
    has_sklearn: bool
    has_pytorch: bool
    has_tensorflow: bool
    has_airflow: bool
    has_spark: bool
    has_kafka: bool
    has_docker: bool
    has_kubernetes: bool
    has_terraform: bool
    has_ansible: bool
    has_jenkins: bool
    has_gitlab_ci: bool
    has_cicd: bool
    skill_sql: bool
    skill_excel: bool
    skill_powerbi: bool
    skill_tableau: bool
    skill_clickhouse: bool
    skill_bigquery: bool
    skill_r: bool
    skill_airflow: bool
    skill_ab_testing: bool
    skill_product_metrics: bool
    core_data_skills_count: int
    ml_stack_count: int
    tech_stack_size: int
    benefit_dms: bool
    benefit_insurance: bool
    benefit_sick_leave_paid: bool
    benefit_vacation_paid: bool
    benefit_relocation: bool
    benefit_sport: bool
    benefit_education: bool
    benefit_remote_compensation: bool
    benefit_stock: bool
    vacancy_url: str
    employer_url: str
    employer_rating: Optional[float] = field(default=None)
    employer_reviews_count: Optional[int] = field(default=None)
    employer_has_remote: bool = field(default=False)
    employer_has_flexible_schedule: bool = field(default=False)
    employer_has_med_insurance: bool = field(default=False)
    employer_has_education: bool = field(default=False)
    employer_accredited_it: Optional[bool] = field(default=None)
    employer_type: Optional[str] = field(default=None)
    edu_required: Optional[bool] = field(default=None)
    edu_level: Optional[str] = field(default=None)
    edu_technical: Optional[bool] = field(default=None)
    edu_math_or_cs: Optional[bool] = field(default=None)
    lang_english_required: Optional[bool] = field(default=None)
    lang_english_level: Optional[str] = field(default=None)
    lang_other_count: Optional[int] = field(default=None)
    is_for_juniors: Optional[bool] = field(default=None)
    allows_students: Optional[bool] = field(default=None)
    has_mentoring: Optional[bool] = field(default=None)
    has_test_task: Optional[bool] = field(default=None)
    soft_communication: bool = field(default=False)
    soft_teamwork: bool = field(default=False)
    soft_leadership: bool = field(default=False)
    soft_result_oriented: bool = field(default=False)
    soft_structured_thinking: bool = field(default=False)
    soft_critical_thinking: bool = field(default=False)
    domain_finance: bool = field(default=False)
    domain_ecommerce: bool = field(default=False)
    domain_telecom: bool = field(default=False)
    domain_state: bool = field(default=False)
    domain_retail: bool = field(default=False)
    domain_it_product: bool = field(default=False)

    def to_dict(self) -> Dict[str, Optional[str]]:
        return asdict(self)


def compute_salary_features(salary_from: Optional[int], salary_to: Optional[int]) -> Dict[str, Optional[object]]:
    salary_mid: Optional[float] = None
    salary_range_width: Optional[int] = None
    salary_is_exact = False

    if salary_from is not None and salary_to is not None:
        salary_mid = (salary_from + salary_to) / 2
        salary_range_width = salary_to - salary_from
    elif salary_from is not None:
        salary_mid = float(salary_from)
        salary_is_exact = True
        salary_range_width = 0
    elif salary_to is not None:
        salary_mid = float(salary_to)
        salary_is_exact = True
        salary_range_width = 0

    return {
        "salary_mid": salary_mid,
        "salary_range_width": salary_range_width,
        "salary_is_exact": salary_is_exact,
    }


def extract_address_features(address: str) -> Tuple[bool, str, int, bool]:
    metro_matches = [
        m.strip()
        for m in re.findall(r"(?:м\\.|метро)\s*([^,;]+)", address, flags=re.IGNORECASE)
    ]
    has_metro = bool(metro_matches)
    metro_primary = metro_matches[0] if metro_matches else ""
    metro_count = len(metro_matches)
    address_has_district = bool(re.search(r"(р-н|район|АО)", address, flags=re.IGNORECASE))
    return has_metro, metro_primary, metro_count, address_has_district


def parse_experience_range(experience: str) -> Tuple[Optional[int], Optional[int], bool]:
    exp_text = experience.lower()
    if "не требуется" in exp_text:
        return 0, 0, True
    if "1–3" in exp_text or "1-3" in exp_text:
        return 1, 3, False
    if "3–6" in exp_text or "3-6" in exp_text:
        return 3, 6, False
    if "более 6" in exp_text or "6+" in exp_text:
        return 6, None, False
    return None, None, False


def detect_grade(text: str) -> str:
    lowered = text.lower()
    for stopword in LEAD_STOPWORDS:
        if stopword in lowered:
            lowered = lowered.replace(stopword, "")

    for grade, patterns in GRADE_KEYWORDS.items():
        for pat in patterns:
            if re.search(pat, lowered):
                return grade
    return "unknown"


def detect_flags(text: str, mapping: Dict[str, List[str]]) -> Dict[str, bool]:
    lowered = text.lower()
    flags = {}
    for key, patterns in mapping.items():
        flags[key] = any(pat.lower() in lowered for pat in patterns)
    return flags


def parse_education_block(full_text: str) -> Dict[str, Optional[object]]:
    lowered = full_text.lower()
    edu_required = None
    edu_level: Optional[str] = None
    edu_technical = None
    edu_math_or_cs = None

    if any(kw in lowered for kw in ["высшее образование", "бакалавр", "магистр", "степень"]):
        edu_required = True
    elif "образование" in lowered:
        edu_required = True
    elif "без образования" in lowered or "можно без" in lowered:
        edu_required = False

    if "неполное высшее" in lowered:
        edu_level = "partial_higher"
    elif "бакалавр" in lowered:
        edu_level = "bachelor_or_higher"
    elif "магистр" in lowered:
        edu_level = "master_or_higher"
    elif "высшее" in lowered:
        edu_level = "any_he"
    elif edu_required is False:
        edu_level = "none"

    if "техническое образование" in lowered or "профильное техническое" in lowered:
        edu_technical = True
    elif "техническое" in lowered:
        edu_technical = True

    if any(kw in lowered for kw in ["математ", "информат", "кибернет", "прикладная математика"]):
        edu_math_or_cs = True

    return {
        "edu_required": edu_required,
        "edu_level": edu_level,
        "edu_technical": edu_technical,
        "edu_math_or_cs": edu_math_or_cs,
    }


def parse_language_requirements(full_text: str) -> Dict[str, Optional[object]]:
    lowered = full_text.lower()
    english_present = "англий" in lowered or "english" in lowered
    english_level = None
    english_required = None
    if english_present:
        english_required = True
        if re.search(r"upper[- ]?intermediate|upper intermediate|b2", lowered):
            english_level = "upper_intermediate"
        elif re.search(r"intermediate|b1", lowered):
            english_level = "intermediate"
        elif re.search(r"advanced|fluent|свободн", lowered):
            english_level = "advanced"
        elif "документац" in lowered:
            english_level = "basic"
    else:
        english_required = False
        english_level = "none"

    other_languages = [
        "немец", "german", "китай", "chinese", "француз", "french", "испан", "spanish", "итальян", "italian",
    ]
    other_count = sum(1 for kw in other_languages if kw in lowered)

    return {
        "lang_english_required": english_required,
        "lang_english_level": english_level,
        "lang_other_count": other_count if other_count else 0,
    }


def detect_data_skills(
    title: str,
    description: str,
    skills_list: Sequence[str],
    tech_flags: Dict[str, bool],
) -> Dict[str, object]:
    combined = f"{title}\n{description}\n{' '.join(skills_list)}".lower()
    data_flags = detect_flags(combined, DATA_SKILL_KEYWORDS)
    ml_candidates = [
        tech_flags.get("has_sklearn"),
        tech_flags.get("has_pytorch"),
        tech_flags.get("has_tensorflow"),
        tech_flags.get("has_airflow") or data_flags.get("skill_airflow"),
        tech_flags.get("has_spark"),
        tech_flags.get("has_kafka"),
    ]
    ml_stack_count = sum(1 for val in ml_candidates if val)

    core_data_skills_count = 0
    if data_flags.get("skill_sql"):
        core_data_skills_count += 1
    if data_flags.get("skill_excel"):
        core_data_skills_count += 1
    if data_flags.get("skill_powerbi") or data_flags.get("skill_tableau"):
        core_data_skills_count += 1
    if tech_flags.get("has_python") or data_flags.get("skill_r"):
        core_data_skills_count += 1

    tech_stack_size = sum(1 for v in tech_flags.values() if v) + sum(
        1 for key, val in data_flags.items() if key.startswith("skill_") and val
    )

    return {
        **data_flags,
        "skills_count": len(skills_list),
        "core_data_skills_count": core_data_skills_count,
        "ml_stack_count": ml_stack_count,
        "tech_stack_size": tech_stack_size,
    }


def detect_soft_skills(full_text: str) -> Dict[str, bool]:
    return detect_flags(full_text, SOFT_SKILL_KEYWORDS)


def detect_domains(full_text: str) -> Dict[str, bool]:
    return detect_flags(full_text, DOMAIN_KEYWORDS)


def count_bullets_in_lines(lines: List[str]) -> int:
    return sum(1 for line in lines if line.strip().startswith(("-", "*", "•")))


def split_description_sections(description_html: str) -> Dict[str, str]:
    soup = BeautifulSoup(description_html or "", "html.parser")
    text = soup.get_text("\n", strip=True)
    sections = {"duties": "", "requirements": "", "conditions": "", "nice_to_have": ""}
    current = None
    for line in text.splitlines():
        lowered = line.lower().strip()
        if any(k in lowered for k in ["обязанности", "что делать", "responsibilit"]):
            current = "duties"
            continue
        if any(k in lowered for k in ["требован", "requirements"]):
            current = "requirements"
            continue
        if any(k in lowered for k in ["услови", "conditions", "we offer"]):
            current = "conditions"
            continue
        if any(k in lowered for k in ["будет плюсом", "nice to have", "желательно"]):
            current = "nice_to_have"
            continue
        if current:
            sections[current] += line + "\n"
    return sections


def count_skill_hits(text: str, *flag_maps: Dict[str, bool]) -> int:
    lowered = text.lower()
    hits: set[str] = set()
    for mapping in flag_maps:
        for key, is_true in mapping.items():
            if isinstance(is_true, bool) and is_true:
                pattern = key.replace("has_", "").replace("skill_", "")
                if pattern in lowered:
                    hits.add(key)
    return len(hits)


def normalize_published_at(raw_text: str, now: datetime) -> Tuple[Optional[str], Optional[int]]:
    lowered = raw_text.lower()
    pub_date: Optional[datetime] = None
    if not raw_text:
        return None, None
    if "сегодня" in lowered:
        pub_date = now
    elif "вчера" in lowered:
        pub_date = now - timedelta(days=1)
    else:
        ago_match = re.search(r"(\d+)\s+дн", lowered)
        if ago_match:
            days = int(ago_match.group(1))
            pub_date = now - timedelta(days=days)
        else:
            date_match = re.search(r"(\d{1,2})\.(\d{1,2})\.(\d{4})", raw_text)
            if date_match:
                day, month, year = map(int, date_match.groups())
                pub_date = datetime(year, month, day, tzinfo=now.tzinfo)
            else:
                month_map = {
                    "январ": 1,
                    "феврал": 2,
                    "март": 3,
                    "апрел": 4,
                    "мая": 5,
                    "май": 5,
                    "июн": 6,
                    "июл": 7,
                    "август": 8,
                    "сентябр": 9,
                    "октябр": 10,
                    "ноябр": 11,
                    "декабр": 12,
                }
                match = re.search(r"(\d{1,2})\s+([а-яA-Я]+)(?:\s+(\d{4}))?", lowered)
                if match:
                    day = int(match.group(1))
                    month_name = match.group(2)
                    year = int(match.group(3)) if match.group(3) else now.year
                    month = next(
                        (val for key, val in month_map.items() if key in month_name), None
                    )
                    if month:
                        pub_date = datetime(year, month, day, tzinfo=now.tzinfo)
    if pub_date:
        iso = pub_date.date().isoformat()
        age_days = (now.date() - pub_date.date()).days
        return iso, age_days
    return None, None


def detect_junior_friendly_signals(full_text: str, exp_is_no_experience: bool) -> Dict[str, Optional[bool]]:
    lowered = full_text.lower()
    is_junior = any(
        kw in lowered for kw in ["junior", "стаж", "intern", "младший", "джун"]
    ) or exp_is_no_experience
    allows_students = any(
        kw in lowered for kw in ["студент", "подходит для студентов", "без полного высшего"]
    )
    has_mentoring = "ментор" in lowered or "наставнич" in lowered
    has_test_task = any(kw in lowered for kw in ["тестовое задание", "test task", "coding challenge"])
    return {
        "is_for_juniors": is_junior,
        "allows_students": allows_students,
        "has_mentoring": has_mentoring,
        "has_test_task": has_test_task,
    }


def classify_work_format(full_text: str, description_text: str) -> Tuple[str, str, bool, bool, str]:
    match_fmt = re.search(r"Формат работы:\s*([^\n]+)", full_text)
    work_format_raw = match_fmt.group(1).strip() if match_fmt else ""
    combined_text = f"{full_text}\n{description_text}".lower()
    is_remote = "удал" in work_format_raw.lower() or "удал" in combined_text or "можно удаленно" in combined_text or "можно удалённо" in combined_text
    is_hybrid = "гибрид" in work_format_raw.lower() or "hybrid" in combined_text
    if is_remote:
        work_format = "remote"
    elif is_hybrid:
        work_format = "hybrid"
    elif "офис" in work_format_raw.lower() or "в офисе" in combined_text:
        work_format = "office"
    elif "разъезд" in combined_text or "field" in combined_text:
        work_format = "field"
    else:
        work_format = "unknown"
    schedule_match = re.search(r"график работы:\s*([^\n]+)", full_text, flags=re.IGNORECASE)
    schedule = schedule_match.group(1).strip() if schedule_match else ""
    return work_format_raw, work_format, is_remote, is_hybrid, schedule


def parse_published_at(full_text: str) -> str:
    match = re.search(r"Вакансия опубликована\s+(.+?)\s+в\s+.+", full_text)
    return match.group(1).strip() if match else ""


def extract_skills(soup: BeautifulSoup) -> str:
    selectors = [
        "[data-qa='bloko-tag__text']",
        "[data-qa='skills-element']",
        "span[data-qa='bloko-tag__text']",
        "span[class*='bloko-tag__text']",
        "div[class*='bloko-tag__text']",
        "a[class*='bloko-tag__text']",
        "[data-qa*='skill']",
        "div[data-qa='skills-block'] span",
    ]
    skill_tags = []
    for selector in selectors:
        skill_tags.extend(soup.select(selector))

    if not skill_tags:
        heading = soup.find(string=re.compile("Ключевые навыки", re.IGNORECASE))
        if heading:
            section = heading.parent if hasattr(heading, "parent") else None
            if section:
                skill_tags.extend(section.find_all("span"))
                for sibling in section.next_siblings:
                    if getattr(sibling, "name", None):
                        skill_tags.extend(sibling.find_all("span"))
                    if len(skill_tags) >= 5:
                        break

    script_skills: List[str] = []
    if not skill_tags:
        for script in soup.find_all("script"):
            text = script.string or script.get_text()
            if not text:
                continue
            if script.get("type") == "application/ld+json":
                try:
                    data = json.loads(text)
                    candidates = data if isinstance(data, list) else [data]
                    for entry in candidates:
                        key_skills = entry.get("keySkills") or entry.get("skills")
                        if isinstance(key_skills, list):
                            for item in key_skills:
                                if isinstance(item, dict) and "name" in item:
                                    script_skills.append(str(item["name"]))
                                elif isinstance(item, str):
                                    script_skills.append(item)
                except json.JSONDecodeError:
                    pass
            if "keySkills" in text:
                matches = re.findall(r"\"name\"\s*:\s*\"([^\"]+)\"", text)
                script_skills.extend(matches)
    if script_skills:
        skill_tags = [BeautifulSoup(f"<span>{name}</span>", "html.parser").span for name in script_skills]

    if not skill_tags:
        skill_block = soup.find("div", attrs={"data-qa": re.compile("skill", re.IGNORECASE)})
        if skill_block:
            skill_tags.extend(skill_block.find_all(["span", "a", "div"]))

    skills = [extract_text(tag) for tag in skill_tags if extract_text(tag)]
    seen = set()
    deduped = []
    for skill in skills:
        if skill.lower() not in seen:
            seen.add(skill.lower())
            deduped.append(skill)
    return ", ".join(deduped)


def description_stats(description: str) -> Tuple[int, int, int, int]:
    desc_len_chars = len(description)
    desc_len_words = len(description.split()) if description else 0
    lines = description.splitlines()
    bullets = sum(1 for line in lines if line.strip().startswith(("-", "*", "•")))
    paragraphs = 0
    prev_blank = True
    for line in lines:
        if line.strip():
            if prev_blank:
                paragraphs += 1
            prev_blank = False
        else:
            prev_blank = True
    if not paragraphs and description:
        paragraphs = 1
    return desc_len_chars, desc_len_words, bullets, paragraphs


def find_vacancy_code(full_text: str) -> str:
    match = re.search(r"Код вакансии\s+([\w-]+)", full_text)
    return match.group(1) if match else ""


def parse_employer_page(employer_html: str) -> Dict[str, Optional[object]]:
    soup = BeautifulSoup(employer_html, "html.parser")
    full_text = soup.get_text("\n", strip=True)
    rating = None
    reviews_count = None

    def normalize_rating(val) -> Optional[float]:
        try:
            rating_val = float(str(val).replace(",", "."))
        except (TypeError, ValueError):
            return None
        return rating_val if 0 <= rating_val <= 5 else None

    def parse_int_with_spaces(text_val: str) -> Optional[int]:
        cleaned = re.sub(r"[^0-9]", "", text_val)
        if not cleaned:
            return None
        try:
            return int(cleaned)
        except ValueError:
            return None

    def extract_balanced_json(text: str, start_index: int) -> Optional[str]:
        depth = 0
        started = False
        for idx in range(start_index, len(text)):
            char = text[idx]
            if char == "{":
                depth += 1
                started = True
            elif char == "}":
                depth -= 1
                if started and depth == 0:
                    return text[start_index : idx + 1]
        return None

    def build_variants(raw_html: str) -> List[str]:
        variants = [raw_html]
        unescaped = html_lib.unescape(raw_html)
        if unescaped != raw_html:
            variants.append(unescaped)
        if "\\" in raw_html:
            variants.append(raw_html.replace("\\/", "/"))
            variants.append(raw_html.replace("\\\"", '"'))
            try:
                variants.append(raw_html.encode("utf-8").decode("unicode_escape", errors="ignore"))
            except UnicodeDecodeError:
                pass
        # Deduplicate while preserving order
        seen_variants: List[str] = []
        for variant in variants:
            if variant not in seen_variants:
                seen_variants.append(variant)
        return seen_variants

    def search_total_rating(raw_html: str) -> Optional[float]:
        nonlocal reviews_count
        for variant in build_variants(raw_html):
            for match in re.finditer(
                r"\"employerReviews\"\s*:\s*\{",
                variant,
                flags=re.IGNORECASE,
            ):
                json_fragment = extract_balanced_json(variant, match.end() - 1)
                if not json_fragment:
                    continue
                for review_json in build_variants(json_fragment):
                    try:
                        data = json.loads(review_json)
                    except json.JSONDecodeError:
                        continue
                    if not isinstance(data, dict):
                        continue
                    if reviews_count is None:
                        count_val = (
                            data.get("reviewsCount")
                            or (data.get("ratingInfo") or {}).get("reviewsCount")
                            or (data.get("rating") or {}).get("reviewsCount")
                        )
                        if count_val is not None:
                            reviews_count = parse_int_with_spaces(str(count_val))
                    candidate = normalize_rating(
                        data.get("totalRating")
                        or data.get("rating")
                        or (data.get("ratingInfo") or {}).get("value")
                        or (data.get("rating") or {}).get("value")
                    )
                    if candidate is not None:
                        return candidate

        patterns = [
            r"totalRating\s*[:=]\s*['\"]?([0-9]+(?:[.,][0-9]+)?)",
            r"\"totalRating\"\s*:\s*(?:\{[^}]*?\"value\"\s*:\s*)?['\"]?([0-9]+(?:[.,][0-9]+)?)['\"]?",
            r"totalRating[^0-9]{0,20}([0-9]+(?:[.,][0-9]+)?)",
            r"totalRating\\\"\s*:\s*\\\"([0-9]+(?:[.,][0-9]+)?)",
        ]

        for variant in build_variants(raw_html):
            for pat in patterns:
                for match in re.finditer(pat, variant, flags=re.IGNORECASE | re.DOTALL):
                    candidate = normalize_rating(match.group(1))
                    if candidate is not None:
                        return candidate
        return None

    rating = search_total_rating(employer_html)

    rating_selectors = [
        "[data-qa='employer-rating-value']",
        "[data-qa='employer-review-rating-value']",
        "[data-qa='employer-header-rating-value']",
        "[itemprop='ratingValue']",
        "meta[itemprop='ratingValue']",
        "meta[name='ratingValue']",
        "[data-qa='employer-rating']",
        "[data-qa='employer-review-rating']",
        "[data-qa='rating-score']",
    ]
    for selector in rating_selectors:
        if rating is not None:
            break
        element = soup.select_one(selector)
        if element:
            value = element.get("content") or element.get("value") or extract_text(element)
            candidate = normalize_rating(value)
            if candidate is not None:
                rating = candidate
                break
    if rating is None:
        for agg_json_ld in soup.find_all("script", attrs={"type": "application/ld+json"}):
            try:
                data = json.loads(agg_json_ld.get_text())
            except json.JSONDecodeError:
                continue
            entries = data if isinstance(data, list) else [data]
            for entry in entries:
                if isinstance(entry, dict):
                    agg = entry.get("aggregateRating") or entry.get("rating")
                    if isinstance(agg, dict):
                        val = agg.get("ratingValue") or agg.get("rating") or agg.get("value")
                        rating = normalize_rating(val)
                        if rating is not None:
                            break
                    elif "ratingValue" in entry:
                        rating = normalize_rating(entry.get("ratingValue"))
                if rating is not None:
                    break
            if rating is not None:
                break
    if rating is None:
        for script in soup.find_all("script"):
            text = script.get_text(strip=True)
            try:
                data = json.loads(text)
            except json.JSONDecodeError:
                continue
            entries = data if isinstance(data, list) else [data]
            for entry in entries:
                if isinstance(entry, dict):
                    for key in ("rating", "ratingInfo", "ratingScore", "totalRating"):
                        val = entry.get(key)
                        if isinstance(val, dict):
                            val = val.get("value") or val.get("ratingValue") or val.get("score")
                        rating = normalize_rating(val)
                        if rating is not None:
                            break
                if rating is not None:
                    break
            if rating is not None:
                break
    if rating is None:
        rating = search_total_rating(employer_html)

    if rating is None:
        rating_match = re.search(
            r"ratingValue\s*[:=]\s*([0-9]+(?:[\.,][0-9]+)?)",
            employer_html,
            flags=re.IGNORECASE,
        )
        if rating_match:
            rating = normalize_rating(rating_match.group(1))

    reviews_text = extract_text(soup.select_one("[data-qa='employer-reviews-link']"))
    if reviews_text:
        parsed = parse_int_with_spaces(reviews_text)
        if parsed is not None:
            reviews_count = parsed
    if reviews_count is None:
        reviews_match = re.search(
            r"([0-9\s\u00a0\u202f]+)\s+отзыв",
            full_text.lower(),
        )
        if reviews_match:
            reviews_count = parse_int_with_spaces(reviews_match.group(1))
    if reviews_count is None:
        for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
            try:
                data = json.loads(script.get_text())
            except json.JSONDecodeError:
                continue
            entries = data if isinstance(data, list) else [data]
            for entry in entries:
                agg = entry.get("aggregateRating") or entry.get("rating")
                count_val = None
                if isinstance(agg, dict):
                    count_val = agg.get("ratingCount") or agg.get("reviewCount")
                if count_val is not None:
                    reviews_count = parse_int_with_spaces(str(count_val))
                    if reviews_count is not None:
                        break
            if reviews_count is not None:
                break
    if reviews_count is None:
        reviews_match = re.search(
            r'"reviewsCount"\s*:\s*([0-9\s\u00a0\u202f]+)',
            employer_html,
        )
        if reviews_match:
            reviews_count = parse_int_with_spaces(reviews_match.group(1))

    advantage_flags = {
        "employer_has_remote": False,
        "employer_has_flexible_schedule": False,
        "employer_has_med_insurance": False,
        "employer_has_education": False,
    }

    employer_accredited_it: Optional[bool] = None
    employer_type: Optional[str] = None

    advantages_block = re.search(
        r'"advantages"\s*:\s*(\[[^\]]+\])', employer_html
    )
    if advantages_block:
        try:
            items = json.loads(advantages_block.group(1))
            adv_text = " ".join(items).lower()
        except json.JSONDecodeError:
            adv_text = advantages_block.group(1).lower()
    else:
        adv_text = full_text.lower()

    advantage_flags["employer_has_remote"] = "удал" in adv_text or "remote" in adv_text
    advantage_flags["employer_has_flexible_schedule"] = "гибк" in adv_text or "flexible" in adv_text
    advantage_flags["employer_has_med_insurance"] = "дмс" in adv_text or "мед" in adv_text or "insurance" in adv_text
    advantage_flags["employer_has_education"] = "обуч" in adv_text or "education" in adv_text or "курсы" in adv_text

    if re.search(r"аккредитованн[а-я\s]+it", full_text, flags=re.IGNORECASE):
        employer_accredited_it = True
    elif "аккредитован" in full_text.lower():
        employer_accredited_it = True

    employer_type_text = extract_text(
        soup.select_one("[data-qa='employer-type']")
    ).lower()
    if not employer_type_text:
        employer_type_text = full_text.lower()
    if "прямой работодатель" in employer_type_text:
        employer_type = "direct"
    elif "кадров" in employer_type_text or "агентств" in employer_type_text:
        employer_type = "agency"

    return {
        "employer_rating": rating,
        "employer_reviews_count": reviews_count,
        "employer_accredited_it": employer_accredited_it,
        "employer_type": employer_type,
        **advantage_flags,
    }


def apply_employer_info(record: VacancyRecord, info: Dict[str, Optional[object]]) -> None:
    record.employer_rating = info.get("employer_rating")
    record.employer_reviews_count = info.get("employer_reviews_count")
    record.employer_has_remote = bool(info.get("employer_has_remote"))
    record.employer_has_flexible_schedule = bool(info.get("employer_has_flexible_schedule"))
    record.employer_has_med_insurance = bool(info.get("employer_has_med_insurance"))
    record.employer_has_education = bool(info.get("employer_has_education"))
    record.employer_accredited_it = info.get("employer_accredited_it")
    record.employer_type = info.get("employer_type")


def build_session(proxy: Optional[str] = None) -> requests.Session:
    session = requests.Session()
    retries = Retry(
        total=5,
        backoff_factor=0.5,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=("GET", "HEAD"),
    )
    adapter = HTTPAdapter(max_retries=retries)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    if proxy:
        session.proxies = {"http": proxy, "https": proxy}
    return session


def pick_user_agent() -> str:
    return random.choice(USER_AGENTS)


def parse_salary(text: str) -> Dict[str, Optional[object]]:
    cleaned = text.replace("\xa0", " ").replace("\u202f", " ")
    gross = None
    lowered = cleaned.lower()
    if "до вычета" in lowered:
        gross = True
    if "на руки" in lowered:
        gross = False

    currency = None
    for hint, code in CURRENCY_HINTS.items():
        if hint in cleaned:
            currency = code
            break

    numbers = [int(re.sub(r"\D", "", n)) for n in re.findall(r"\d[\d ]*", cleaned)]
    salary_from = salary_to = None
    if numbers:
        if "от" in cleaned and "до" in cleaned and len(numbers) >= 2:
            salary_from, salary_to = numbers[0], numbers[1]
        elif "от" in cleaned:
            salary_from = numbers[0]
        elif "до" in cleaned:
            salary_to = numbers[0]
        elif len(numbers) == 2:
            salary_from, salary_to = numbers
        elif len(numbers) == 1:
            salary_from = numbers[0]
    return {
        "salary_from": salary_from,
        "salary_to": salary_to,
        "currency": currency,
        "salary_gross": gross,
    }


def extract_text(element) -> str:
    return element.get_text(strip=True) if element else ""


def parse_search_page(html: str) -> List[str]:
    soup = BeautifulSoup(html, "html.parser")
    links = []
    for anchor in soup.select("a[data-qa='serp-item__title']"):
        href = anchor.get("href")
        if href and href.startswith("/"):
            href = f"{VACANCY_HOST}{href}"
        if href:
            links.append(href.split("?")[0])
    return links


def parse_vacancy_page(
    html: str, url: str, area_id: int, scraped_at: datetime
) -> Optional[VacancyRecord]:
    soup = BeautifulSoup(html, "html.parser")
    title = extract_text(soup.select_one("h1[data-qa='vacancy-title']"))
    salary_block = soup.select_one("div[data-qa='vacancy-salary']")
    salary_text = extract_text(salary_block)
    salary_data = parse_salary(salary_text) if salary_text else {
        "salary_from": None,
        "salary_to": None,
        "currency": None,
        "salary_gross": None,
    }
    if not (salary_data["salary_from"] or salary_data["salary_to"]):
        return None

    salary_features = compute_salary_features(
        salary_data["salary_from"], salary_data["salary_to"]
    )

    company_anchor = soup.select_one("a[data-qa='vacancy-company-name']")
    company = extract_text(company_anchor)
    employer_url = company_anchor.get("href") if company_anchor else ""

    address = extract_text(
        soup.select_one(
            "span[data-qa='vacancy-view-raw-address'], span[data-qa='vacancy-view-location']"
        )
    )
    city = address.split(",")[0] if address else "Москва"
    has_metro, metro_primary, metro_count, address_has_district = extract_address_features(address)

    experience = extract_text(soup.select_one("span[data-qa='vacancy-experience']"))
    exp_min_years, exp_max_years, exp_is_no_experience = parse_experience_range(experience)

    full_text = soup.get_text("\n", strip=True)
    employment_match = re.search(
        r"(Полная занятость|Частичная занятость|Стажировка|Проектная работа|Волонтёрство)",
        full_text,
    )
    employment = employment_match.group(1) if employment_match else extract_text(
        soup.select_one("p[data-qa='vacancy-view-employment-mode']")
    )

    description_node = soup.select_one("div[data-qa='vacancy-description']")
    description = (
        description_node.get_text("\n\n", strip=True) if description_node else ""
    )
    description_html = description_node.decode_contents() if description_node else ""
    work_format_raw, work_format, is_remote, is_hybrid, schedule_from_text = classify_work_format(
        full_text, description
    )
    schedule = schedule_from_text or extract_text(soup.select_one("p[data-qa='vacancy-view-emp-mode']"))
    if not schedule:
        schedule = extract_text(soup.select_one("p[data-qa='vacancy-view-schedule']"))

    skills_str = extract_skills(soup)
    published_at_raw = parse_published_at(full_text)
    if not published_at_raw:
        published_at_raw = extract_text(soup.select_one("p[data-qa='vacancy-view-creation-time']"))
    published_at_iso, vacancy_age_days = normalize_published_at(published_at_raw, scraped_at)
    vacancy_code = find_vacancy_code(full_text)
    desc_len_chars, desc_len_words, desc_bullets, desc_paragraphs = description_stats(description)

    sections = split_description_sections(description_html)
    requirements_count = count_bullets_in_lines(sections["requirements"].splitlines()) if sections["requirements"] else 0
    responsibilities_count = count_bullets_in_lines(sections["duties"].splitlines()) if sections["duties"] else 0

    combined_text = f"{title}\n{description}\n{skills_str}".lower()
    grade = detect_grade(combined_text)
    role_flags = detect_flags(combined_text, ROLE_KEYWORDS)
    tech_flags = detect_flags(combined_text, TECH_KEYWORDS)
    benefit_flags = detect_flags(combined_text, BENEFIT_KEYWORDS)
    is_remote = is_remote or benefit_flags.get("benefit_remote_compensation", False)

    skills_list = [s.strip() for s in skills_str.split(",") if s.strip()]
    data_skill_info = detect_data_skills(title, description, skills_list, tech_flags)
    soft_skill_flags = detect_soft_skills(combined_text)
    domain_flags = detect_domains(combined_text)
    education_info = parse_education_block(f"{title}\n{description}")
    language_info = parse_language_requirements(f"{title}\n{description}")
    junior_info = detect_junior_friendly_signals(combined_text, exp_is_no_experience)

    must_have_skills_count = count_skill_hits(
        sections.get("requirements", ""), tech_flags, data_skill_info
    )
    optional_skills_count = count_skill_hits(
        sections.get("nice_to_have", ""), tech_flags, data_skill_info
    )

    vacancy_id_match = re.search(r"vacancy/(\d+)", url)
    vacancy_id = vacancy_id_match.group(1) if vacancy_id_match else ""

    return VacancyRecord(
        vacancy_id=vacancy_id,
        title=title,
        company=company,
        salary_from=salary_data["salary_from"],
        salary_to=salary_data["salary_to"],
        currency=salary_data["currency"],
        salary_gross=salary_data["salary_gross"],
        salary_mid=salary_features["salary_mid"],
        salary_range_width=salary_features["salary_range_width"],
        salary_is_exact=salary_features["salary_is_exact"],
        city=city,
        address=address,
        has_metro=has_metro,
        metro_primary=metro_primary,
        metro_count=metro_count,
        address_has_district=address_has_district,
        search_area_id=area_id,
        experience=experience,
        exp_min_years=exp_min_years,
        exp_max_years=exp_max_years,
        exp_is_no_experience=exp_is_no_experience,
        employment_type=employment,
        schedule=schedule,
        work_format_raw=work_format_raw,
        work_format=work_format,
        is_remote=is_remote,
        is_hybrid=is_hybrid,
        description=description,
        description_len_chars=desc_len_chars,
        description_len_words=desc_len_words,
        description_bullets_count=desc_bullets,
        description_paragraphs_count=desc_paragraphs,
        requirements_count=requirements_count,
        responsibilities_count=responsibilities_count,
        optional_skills_count=optional_skills_count,
        must_have_skills_count=must_have_skills_count,
        skills=skills_str,
        skills_count=data_skill_info.get("skills_count", 0),
        published_at_raw=published_at_raw,
        published_at_iso=published_at_iso,
        vacancy_age_days=vacancy_age_days,
        scraped_at_utc=scraped_at.isoformat(),
        vacancy_code=vacancy_code,
        grade=grade,
        role_backend=role_flags.get("role_backend", False),
        role_frontend=role_flags.get("role_frontend", False),
        role_fullstack=role_flags.get("role_fullstack", False),
        role_mobile=role_flags.get("role_mobile", False),
        role_data=role_flags.get("role_data", False),
        role_ml=role_flags.get("role_ml", False),
        role_devops=role_flags.get("role_devops", False),
        role_qa=role_flags.get("role_qa", False),
        role_manager=role_flags.get("role_manager", False),
        role_product=role_flags.get("role_product", False),
        role_analyst=role_flags.get("role_analyst", False),
        has_python=tech_flags.get("has_python", False),
        has_java=tech_flags.get("has_java", False),
        has_kotlin=tech_flags.get("has_kotlin", False),
        has_csharp=tech_flags.get("has_csharp", False),
        has_cpp=tech_flags.get("has_cpp", False),
        has_go=tech_flags.get("has_go", False),
        has_php=tech_flags.get("has_php", False),
        has_javascript=tech_flags.get("has_javascript", False),
        has_typescript=tech_flags.get("has_typescript", False),
        has_scala=tech_flags.get("has_scala", False),
        has_rust=tech_flags.get("has_rust", False),
        has_ruby=tech_flags.get("has_ruby", False),
        has_django=tech_flags.get("has_django", False),
        has_flask=tech_flags.get("has_flask", False),
        has_fastapi=tech_flags.get("has_fastapi", False),
        has_dotnet=tech_flags.get("has_dotnet", False),
        has_spring=tech_flags.get("has_spring", False),
        has_nodejs=tech_flags.get("has_nodejs", False),
        has_express=tech_flags.get("has_express", False),
        has_nestjs=tech_flags.get("has_nestjs", False),
        has_react=tech_flags.get("has_react", False),
        has_vue=tech_flags.get("has_vue", False),
        has_angular=tech_flags.get("has_angular", False),
        has_nextjs=tech_flags.get("has_nextjs", False),
        has_nuxt=tech_flags.get("has_nuxt", False),
        has_svelte=tech_flags.get("has_svelte", False),
        has_pandas=tech_flags.get("has_pandas", False),
        has_numpy=tech_flags.get("has_numpy", False),
        has_sklearn=tech_flags.get("has_sklearn", False),
        has_pytorch=tech_flags.get("has_pytorch", False),
        has_tensorflow=tech_flags.get("has_tensorflow", False),
        has_airflow=tech_flags.get("has_airflow", False),
        has_spark=tech_flags.get("has_spark", False),
        has_kafka=tech_flags.get("has_kafka", False),
        has_docker=tech_flags.get("has_docker", False),
        has_kubernetes=tech_flags.get("has_kubernetes", False),
        has_terraform=tech_flags.get("has_terraform", False),
        has_ansible=tech_flags.get("has_ansible", False),
        has_jenkins=tech_flags.get("has_jenkins", False),
        has_gitlab_ci=tech_flags.get("has_gitlab_ci", False),
        has_cicd=tech_flags.get("has_cicd", False),
        skill_sql=data_skill_info.get("skill_sql", False),
        skill_excel=data_skill_info.get("skill_excel", False),
        skill_powerbi=data_skill_info.get("skill_powerbi", False),
        skill_tableau=data_skill_info.get("skill_tableau", False),
        skill_clickhouse=data_skill_info.get("skill_clickhouse", False),
        skill_bigquery=data_skill_info.get("skill_bigquery", False),
        skill_r=data_skill_info.get("skill_r", False),
        skill_airflow=data_skill_info.get("skill_airflow", False) or tech_flags.get("has_airflow", False),
        skill_ab_testing=data_skill_info.get("skill_ab_testing", False),
        skill_product_metrics=data_skill_info.get("skill_product_metrics", False),
        core_data_skills_count=data_skill_info.get("core_data_skills_count", 0),
        ml_stack_count=data_skill_info.get("ml_stack_count", 0),
        tech_stack_size=data_skill_info.get("tech_stack_size", 0),
        benefit_dms=benefit_flags.get("benefit_dms", False),
        benefit_insurance=benefit_flags.get("benefit_insurance", False),
        benefit_sick_leave_paid=benefit_flags.get("benefit_sick_leave_paid", False),
        benefit_vacation_paid=benefit_flags.get("benefit_vacation_paid", False),
        benefit_relocation=benefit_flags.get("benefit_relocation", False),
        benefit_sport=benefit_flags.get("benefit_sport", False),
        benefit_education=benefit_flags.get("benefit_education", False),
        benefit_remote_compensation=benefit_flags.get("benefit_remote_compensation", False),
        benefit_stock=benefit_flags.get("benefit_stock", False),
        vacancy_url=url,
        employer_url=employer_url or "",
        edu_required=education_info.get("edu_required"),
        edu_level=education_info.get("edu_level"),
        edu_technical=education_info.get("edu_technical"),
        edu_math_or_cs=education_info.get("edu_math_or_cs"),
        lang_english_required=language_info.get("lang_english_required"),
        lang_english_level=language_info.get("lang_english_level"),
        lang_other_count=language_info.get("lang_other_count"),
        is_for_juniors=junior_info.get("is_for_juniors"),
        allows_students=junior_info.get("allows_students"),
        has_mentoring=junior_info.get("has_mentoring"),
        has_test_task=junior_info.get("has_test_task"),
        soft_communication=soft_skill_flags.get("soft_communication", False),
        soft_teamwork=soft_skill_flags.get("soft_teamwork", False),
        soft_leadership=soft_skill_flags.get("soft_leadership", False),
        soft_result_oriented=soft_skill_flags.get("soft_result_oriented", False),
        soft_structured_thinking=soft_skill_flags.get("soft_structured_thinking", False),
        soft_critical_thinking=soft_skill_flags.get("soft_critical_thinking", False),
        domain_finance=domain_flags.get("domain_finance", False),
        domain_ecommerce=domain_flags.get("domain_ecommerce", False),
        domain_telecom=domain_flags.get("domain_telecom", False),
        domain_state=domain_flags.get("domain_state", False),
        domain_retail=domain_flags.get("domain_retail", False),
        domain_it_product=domain_flags.get("domain_it_product", False),
    )


def load_proxies(path: Optional[str]) -> List[str]:
    if not path or not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as fh:
        return [line.strip() for line in fh if line.strip()]


def rotate_proxy(proxies: List[str], index: int) -> Optional[str]:
    if not proxies:
        return None
    return proxies[index % len(proxies)]


def fetch(session: requests.Session, url: str, headers: Dict[str, str]) -> Optional[str]:
    response = session.get(url, headers=headers, timeout=20)
    if response.status_code >= 400:
        return None
    return response.text


def scrape(
    query: str = DEFAULT_QUERY,
    limit: int = DEFAULT_LIMIT,
    output: str = DEFAULT_OUTPUT,
    delay: float = 1.5,
    max_pages: Optional[int] = None,
    proxy_list: Optional[List[str]] = None,
    area_ids: Optional[Sequence[int]] = None,
) -> List[VacancyRecord]:
    os.makedirs(os.path.dirname(output), exist_ok=True)
    collected: List[VacancyRecord] = []
    seen_vacancy_ids: set[str] = set()
    proxy_index = 0
    proxy_list = proxy_list or []
    employer_cache: Dict[str, Dict[str, Optional[object]]] = {}
    area_ids = list(area_ids) if area_ids is not None else list(DEFAULT_AREA_IDS)
    scraped_at = datetime.now(timezone.utc)

    for area_id in area_ids:
        for exp_filter in EXPERIENCE_SHARDS:
            page = 0
            shard_label = exp_filter or "all_experience"
            while len(collected) < limit:
                if max_pages is not None and page >= max_pages:
                    break
                proxy = rotate_proxy(proxy_list, proxy_index)
                session = build_session(proxy=proxy)
                headers = {
                    "User-Agent": pick_user_agent(),
                    "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
                    "Referer": "https://hh.ru/",
                }
                params = {
                    "text": query,
                    "area": area_id,
                    "only_with_salary": "true",
                    "page": page,
                    "items_on_page": 20,
                    "order_by": "publication_time",
                }
                if exp_filter:
                    params["experience"] = exp_filter
                print(
                    f"[area={area_id} exp={shard_label} page={page}] получаем результаты поиска через прокси={proxy}"
                )
                search_response = session.get(SEARCH_URL, params=params, headers=headers, timeout=20)
                if search_response.status_code == 404:
                    print("Поисковая страница вернула 404 (скорее всего лимит пагинации), переходим к следующему шару")
                    break
                if search_response.status_code >= 400:
                    print(
                        f"Ошибка запроса поисковой страницы {search_response.status_code}, переключаем прокси"
                    )
                    proxy_index += 1
                    time.sleep(delay)
                    continue
                links = parse_search_page(search_response.text)
                if not links:
                    print("В этом шаре вакансий больше не найдено, останавливаем пагинацию.")
                    break

                for link in links:
                    headers["User-Agent"] = pick_user_agent()
                    html = fetch(session, link, headers=headers)
                    if not html:
                        print(f"Пропускаем {link} из-за ошибки загрузки")
                        continue
                    record = parse_vacancy_page(html, link, area_id=area_id, scraped_at=scraped_at)
                    if not record:
                        continue
                    if record.vacancy_id in seen_vacancy_ids:
                        continue
                    seen_vacancy_ids.add(record.vacancy_id)
                    employer_url = record.employer_url
                    if employer_url and employer_url.startswith("/"):
                        employer_url = f"{VACANCY_HOST}{employer_url}"
                        record.employer_url = employer_url
                    employer_info: Dict[str, Optional[object]] = {}
                    if employer_url:
                        if employer_url not in employer_cache:
                            emp_html = fetch(session, employer_url, headers=headers)
                            if emp_html:
                                employer_cache[employer_url] = parse_employer_page(emp_html)
                            else:
                                employer_cache[employer_url] = {}
                        employer_info = employer_cache.get(employer_url, {})
                    apply_employer_info(record, employer_info)
                    collected.append(record)
                    if len(collected) % 50 == 0:
                        print(f"Собрано {len(collected)} вакансий")
                    if len(collected) >= limit:
                        break
                    time.sleep(delay + random.uniform(0, delay))

                page += 1
                proxy_index += 1
                time.sleep(delay)

    if collected:
        with open(output, "w", encoding="utf-8", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=collected[0].to_dict().keys())
            writer.writeheader()
            for rec in collected:
                writer.writerow(rec.to_dict())
    return collected


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Скрапинг IT-вакансий HH.ru с указанной зарплатой через BeautifulSoup "
            "и сохранение в CSV."
        )
    )
    parser.add_argument(
        "--query",
        default=DEFAULT_QUERY,
        help="Поисковый запрос (по умолчанию широкий булевый NAME: фильтр по IT)",
    )
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT, help="Целевое число вакансий")
    parser.add_argument("--delay", type=float, default=1.5, help="Базовая задержка между запросами")
    parser.add_argument("--output", default=DEFAULT_OUTPUT, help="Путь для сохранения CSV")
    parser.add_argument(
        "--max-pages",
        type=int,
        default=None,
        help="Необязательный лимит глубины пагинации (для быстрых тестов)",
    )
    parser.add_argument(
        "--proxies",
        default=None,
        help="Путь к файлу со списком прокси (scheme://user:pass@host:port, по одному на строку)",
    )
    parser.add_argument(
        "--areas",
        nargs="*",
        type=int,
        default=list(DEFAULT_AREA_IDS),
        help=(
            "area_id HH для поиска (например, 113 Россия, 1 Москва, 2 Санкт-Петербург, "
            "40 Беларусь, 159 Казахстан)"
        ),
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    proxies = load_proxies(args.proxies)
    records = scrape(
        query=args.query,
        limit=args.limit,
        output=args.output,
        delay=args.delay,
        max_pages=args.max_pages,
        proxy_list=proxies,
        area_ids=args.areas,
    )
    print(f"Сохранено {len(records)} строк в {args.output}")


if __name__ == "__main__":
    main()
