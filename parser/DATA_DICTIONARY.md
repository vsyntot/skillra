# Словарь данных: датасет IT-вакансий HH.ru

Документ описывает каждую колонку CSV, которую формирует `hh_scraper.py`. Все существующие поля сохраняются между запусками; новые добавляются в конец файла.

## Идентификаторы и ссылки
- `vacancy_id`: идентификатор вакансии HH, извлечённый из URL.
- `vacancy_url`: абсолютная ссылка на страницу вакансии.
- `employer_url`: абсолютная ссылка на страницу работодателя (если есть).
- `vacancy_code`: опциональный код вакансии со стороны работодателя (из подвала карточки).
- `search_area_id`: `area_id` HH, в рамках которого была найдена вакансия.

## Зарплата
- `salary_from`, `salary_to`: числовые границы вилки зарплаты.
- `currency`: нормализованный код валюты (`RUB`, `USD`, `EUR`, `KZT` и т.д.).
- `salary_gross`: `True`, если указана сумма до вычета налогов, `False` — если «на руки», `None` — если не определено.
- `salary_mid`: середина зарплатного диапазона (или единственная граница, если задан только один конец).
- `salary_range_width`: разница между `salary_to` и `salary_from` (0, если задана одна граница).
- `salary_is_exact`: `True`, когда указана только одна граница.

## Время
- `published_at_raw`: исходный текст о публикации из карточки вакансии.
- `published_at_iso`: нормализованная дата публикации в формате `YYYY-MM-DD`, если парсинг успешен.
- `vacancy_age_days`: число дней между `published_at_iso` и моментом парсинга.
- `scraped_at_utc`: метка времени ISO момента парсинга (UTC).

## Локация
- `city`: город из шапки вакансии.
- `address`: сырой адрес (может включать метро и район).
- `has_metro`: `True`, если в адресе есть упоминания метро.
- `metro_primary`: первая станция метро в адресе.
- `metro_count`: количество упомянутых станций метро.
- `address_has_district`: `True`, если в адресе упоминается район/округ.

## Опыт и грейд
- `experience`: исходный текст про требуемый опыт.
- `exp_min_years`, `exp_max_years`: числовые границы опыта.
- `exp_is_no_experience`: `True`, если опыт не требуется.
- `grade`: классификация грейда (`intern`, `junior`, `middle`, `senior`, `lead`, `architect`, `unknown`).

## Занятость и формат работы
- `employment_type`: тип занятости (полная/частичная/стажировка и т.п.).
- `schedule`: подсказка по графику из шапки вакансии.
- `work_format_raw`: исходный текст формата работы (например, «удалённо», «гибрид»).
- `work_format`: нормализованный формат (`remote`, `hybrid`, `office` и т.д.).
- `is_remote`: флаг удалённого формата.
- `is_hybrid`: флаг гибридного формата.

## Контент вакансии и структура
- `description`: текст описания вакансии (HTML очищен).
- `description_len_chars`, `description_len_words`: длина описания в символах и словах.
- `description_bullets_count`: количество строк-пуллетов в описании.
- `description_paragraphs_count`: приблизительное число абзацев с сохранением переносов.
- `requirements_count`: число пунктов в разделе «Требования».
- `responsibilities_count`: число пунктов в разделе «Обязанности».
- `optional_skills_count`: количество уникальных навыков, встреченных в блоке «Будет плюсом».
- `must_have_skills_count`: количество уникальных навыков, встреченных в блоке «Требования».

## Навыки и технологический стек
- `skills`: список ключевых навыков из карточки вакансии (через запятую).
- `skills_count`: количество ключевых навыков, извлечённых из блока навыков.
- Булевые флаги стека: `has_python`, `has_java`, `has_kotlin`, `has_csharp`, `has_cpp`, `has_go`, `has_php`, `has_javascript`, `has_typescript`, `has_scala`, `has_rust`, `has_ruby`, `has_django`, `has_flask`, `has_fastapi`, `has_dotnet`, `has_spring`, `has_nodejs`, `has_express`, `has_nestjs`, `has_react`, `has_vue`, `has_angular`, `has_nextjs`, `has_nuxt`, `has_svelte`, `has_pandas`, `has_numpy`, `has_sklearn`, `has_pytorch`, `has_tensorflow`, `has_airflow`, `has_spark`, `has_kafka`, `has_docker`, `has_kubernetes`, `has_terraform`, `has_ansible`, `has_jenkins`, `has_gitlab_ci`, `has_cicd`.
- Флаги data/аналитики: `skill_sql`, `skill_excel`, `skill_powerbi`, `skill_tableau`, `skill_clickhouse`, `skill_bigquery`, `skill_r`, `skill_airflow`, `skill_ab_testing`, `skill_product_metrics`.
- Агрегаты: `core_data_skills_count`, `ml_stack_count`, `tech_stack_size`.

## Роли и домены
- Ролевые флаги: `role_backend`, `role_frontend`, `role_fullstack`, `role_mobile`, `role_data`, `role_ml`, `role_devops`, `role_qa`, `role_manager`, `role_product`, `role_analyst`.
- Доменные подсказки: `domain_finance`, `domain_ecommerce`, `domain_telecom`, `domain_state`, `domain_retail`, `domain_it_product`.

## Образование и языки
- `edu_required`: `True`, если явно требуется высшее/профильное образование.
- `edu_level`: уровень образования (`none`, `partial_higher`, `any_he`, `bachelor_or_higher`, `master_or_higher`).
- `edu_technical`: `True`, если требуется техническое образование.
- `edu_math_or_cs`: `True`, если упоминается математика/информатика.
- `lang_english_required`: `True`, если английский язык обязателен или упомянут.
- `lang_english_level`: уровень английского (`none`, `basic`, `intermediate`, `upper_intermediate`, `advanced`).
- `lang_other_count`: количество упоминаний других языков.

## Дружелюбность к джунам
- `is_for_juniors`: позиция явно таргетируется на джунов/стажёров или допускает отсутствие опыта.
- `allows_students`: вакансия подходит студентам.
- `has_mentoring`: упоминается менторство/наставничество.
- `has_test_task`: упоминается тестовое задание.

## Бенефиты и сигналы работодателя
- Бенефиты уровня вакансии: `benefit_dms`, `benefit_insurance`, `benefit_sick_leave_paid`, `benefit_vacation_paid`, `benefit_relocation`, `benefit_sport`, `benefit_education`, `benefit_remote_compensation`, `benefit_stock`.
- Флаги работодателя: `employer_has_remote`, `employer_has_flexible_schedule`, `employer_has_med_insurance`, `employer_has_education`.
- Аккредитация/тип: `employer_accredited_it` (аккредитованная IT-компания), `employer_type` (`direct`, `agency`, `other`/`None`).
- Репутация: `employer_rating` (float 0–5 из отзывов работодателя), `employer_reviews_count` (число отзывов).

## Soft Skills
- `soft_communication`, `soft_teamwork`, `soft_leadership`, `soft_result_oriented`, `soft_structured_thinking`, `soft_critical_thinking` — эвристические индикаторы по ключевым словам.

## Итоговые размерности
- `core_data_skills_count`: количество среди SQL, Excel, BI (PowerBI/Tableau), Python/R.
- `ml_stack_count`: количество среди sklearn, PyTorch, TensorFlow, Airflow, Spark, Kafka.
- `tech_stack_size`: общее число тех-флагов `has_*`/`skill_*`, равных `True`.
