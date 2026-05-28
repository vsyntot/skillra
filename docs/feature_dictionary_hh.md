# HH Feature Dictionary

This document describes the main raw and processed fields used by Skillra.
`parser/DATA_DICTIONARY.md` contains the detailed parser-level CSV dictionary;
this file focuses on product and API contracts.

## Raw Identity Fields

- `vacancy_id`: HH vacancy id extracted from the vacancy URL.
- `vacancy_url`: absolute source URL.
- `employer_url`: employer page URL when available.
- `vacancy_code`: optional employer-side vacancy code.
- `search_area_id`: HH area id used to find the vacancy.
- `scraped_at_utc`: collection timestamp in UTC.

## Publication And Lineage

- `published_at_raw`: raw publication text from HH.
- `published_at_iso`: normalized publication date.
- `vacancy_age_days`: vacancy age at collection time.
- `dataset_scope`: source coverage label such as `all_vacancies` or
  `salary_disclosed`.
- `run_id`: pipeline run id where present.
- `dataset_run_id`: active processed data run id in serving/API records.

## Salary

- `salary_from`, `salary_to`: numeric salary bounds from the source.
- `currency`: normalized salary currency.
- `salary_gross`: tax flag from the source when available.
- `salary_mid`: midpoint of the source salary range.
- `salary_mid_rub`: midpoint converted to RUB.
- `salary_mid_rub_capped`: RUB midpoint capped for robust analytics.
- `salary_range_width`: source range width.
- `salary_is_exact`: true when only one salary boundary is present.
- `salary_disclosed`: true when the source vacancy has at least one salary
  boundary.

## Geography

- `city`: raw city label.
- `address`: raw address text.
- `country`: normalized country.
- `region`: normalized region.
- `city_normalized`: normalized city.
- `geo_scope`: geography scope used for product filtering.
- `city_tier`: city tier such as Moscow, Saint Petersburg, million-plus,
  regional or remote/unknown.
- `has_metro`, `metro_primary`, `metro_count`: metro signals.
- `address_has_district`: district/address-detail signal.

## Role And Grade

- `experience`: raw experience label.
- `exp_min_years`, `exp_max_years`: numeric experience bounds.
- `exp_is_no_experience`: true when no experience is required.
- `grade`: source/heuristic grade.
- `grade_from_experience`: grade inferred from experience.
- `grade_final`: product-grade column used by market, persona and API logic.
- `primary_role`: one primary role chosen from role flags.
- `role_backend`, `role_frontend`, `role_fullstack`, `role_mobile`,
  `role_data`, `role_ml`, `role_devops`, `role_qa`, `role_manager`,
  `role_product`, `role_analyst`: multi-label role flags.

## Work Format

- `employment_type`: source employment type.
- `schedule`: source schedule text.
- `work_format_raw`: raw work-format text.
- `work_format`: normalized source work format.
- `work_mode`: product work-mode dimension.
- `is_remote`, `is_hybrid`: derived format flags.

## Skills And Stack

- `skills`: comma-separated source key skills.
- `skills_count`: number of extracted source skills.
- `has_*`: technology stack boolean flags, for example `has_python`,
  `has_java`, `has_react`, `has_airflow`, `has_kubernetes`.
- `skill_*`: analytical/product skill flags, for example `skill_sql`,
  `skill_excel`, `skill_powerbi`, `skill_clickhouse`, `skill_ab_testing`.
- `core_data_skills_count`: count of core data/BI skills.
- `ml_stack_count`: count of ML/data-platform stack skills.
- `tech_stack_size`: total number of active stack flags.

## Domain

- `domain_finance`
- `domain_ecommerce`
- `domain_telecom`
- `domain_state`
- `domain_retail`
- `domain_it_product`
- `domain`: derived product domain label used by market aggregation when
  present.

## Content And Employer Signals

- `description`: cleaned vacancy description.
- `description_len_chars`, `description_len_words`: description length.
- `description_bullets_count`, `description_paragraphs_count`: structure
  signals.
- `requirements_count`, `responsibilities_count`: section signals.
- `optional_skills_count`, `must_have_skills_count`: skill-section counts.
- `benefit_*`: benefits such as insurance, relocation, education, stock and
  sport.
- `employer_rating`, `employer_reviews_count`: employer reputation signals.
- `employer_has_remote`, `employer_has_flexible_schedule`,
  `employer_has_med_insurance`, `employer_has_education`: employer-level
  benefit signals.
- `employer_accredited_it`, `employer_type`: employer classification.

## Processed Artifacts

`hh_features.parquet` is the main product feature table. `market_view.parquet`
aggregates it by role, grade, geography, work mode and domain where available.

Market view columns include:

- `vacancy_count_total`, `vacancy_count`, `sample_size`;
- `vacancy_count_salary`, `salary_sample_size`;
- `salary_median`, `salary_q25`, `salary_q75`;
- `salary_coverage_share`;
- `junior_friendly_share`, `remote_share`;
- `median_tech_stack_size`;
- `top_skills`;
- `confidence`.

Confidence is derived from vacancy count, salary sample size and salary coverage.
The API exposes this as a user-facing trust signal and may add warnings when a
segment is thin or filters were relaxed.
