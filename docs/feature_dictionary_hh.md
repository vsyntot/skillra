# HH Dataset (Skillra) — Feature Dictionary & Classification

Документ описывает признаки датасета вакансий hh.ru, собранного парсером Skillra, включая:
- список колонок по смысловым блокам,
- логику их извлечения/расчёта,
- и то, зачем каждый блок нужен продукту Career & Job Market Navigator.

### Политика NaN/`unknown`
- текстовые маркеры неопределённости (`unknown`, `не указано`, пустые строки, `n/a` и т.п.) нормализуются в `NaN`;
- без глобального заполнения: числовые признаки (включая `salary_from`, `salary_to`, `salary_mid`, `employer_rating`) остаются `NaN`, исключение — явные счётчики (`*_count`, `employer_reviews_count` и др.), которые приводятся к `0`;
- строковые признаки НЕ заполняются `"unknown"` глобально; осмысленный `"unknown"` сохраняется только в ограниченном наборе колонок (`grade`, `grade_final`, `work_format`, `work_mode`, `employment_type`, `schedule`, `city_tier`, `lang_english_level`, `employer_type`), для остальных пропуски остаются `NaN` и показываются как «не указано» на уровне EDA;
- булевы столбцы нормализуются в `boolean` с `NaN`, если данные отсутствуют;
- в отчёте явно показывается доля `NaN`/`unknown` по ключевым блокам (зарплата, формат работы, английский, грейд) чтобы не терять покрытие.

---

## 0) Идентификаторы и базовая «паспортная» информация вакансии

**Колонки**
- `vacancy_id`
- `vacancy_url`
- `vacancy_code`
- `title`
- `company`

**Логика**
- `vacancy_id` — числовой ID вакансии из URL (`/vacancy/123456789`). Уникальный ключ строки.
- `vacancy_url` — полный URL страницы вакансии на hh (удобно для отладки и перехода к источнику).
- `vacancy_code` — внутренний код вакансии, если указан работодателем в тексте (ищется по паттернам вида «Код вакансии XXX»). Часто пустой.
- `title` — заголовок вакансии.
- `company` — название работодателя.

**Зачем продукту**
- базовая связка «кто / на какую роль»;
- `vacancy_id` помогает сшивать данные с историей/другими источниками;
- `title` нужен для классификации роли и сторителлинга (персоны смотрят подходящие вакансии).

---

## 1) Зарплата и валюта

**Колонки**
- `salary_from`
- `salary_to`
- `currency`
- `salary_gross`
- `salary_mid`
- `salary_range_width`
- `salary_is_exact`
- `salary_bucket`

**Логика**
- парсится блок «зарплата» на hh:
  - `salary_from` — нижняя граница («от X» или `X–Y`)
  - `salary_to` — верхняя граница («до Y» или `X–Y`)
  - `currency` — код валюты (`RUB`, `USD`, `EUR`, `KZT`)
  - `salary_gross`:
    - `True` если указано «до вычета налогов»,
    - `False` если «на руки»,
    - `None` если не указано.
- производные:
  - `salary_mid`:
    - только «от X» → `X`
    - только «до Y» → `Y`
    - `X–Y` → `(X+Y)/2`
  - `salary_range_width` = `salary_to - salary_from` (или `0`, если точка)
  - `salary_is_exact` = `True`, если точка/фактически нет вилки; `False`, если реальная вилка
  - `salary_bucket` — квантильная категория `low/mid/high` по `salary_mid_rub_capped` (для стабильных разрезов без экстремумов)

**Зачем продукту**
- карта зарплат по городам/уровням/ролям;
- подготовка к предсказанию зарплат;
- `salary_mid` удобнее «сырой вилки» для пользовательских выводов;
- `salary_range_width` — сигнал неопределённости/торга (широкие вилки vs точные офферы).

---

## 2) Локация и доступность

**Колонки**
- `city`
- `address`
- `address_has_district`
- `has_metro`
- `metro_primary`
- `metro_count`
- `search_area_id`
- `city_tier`

**Логика**
- `city` — город (обычно первая часть адреса до запятой).
- `address` — полный строковый адрес из hh.
- `address_has_district` — `True`, если упоминается район/АО (р-н, район, АО).
- `has_metro` — есть ли упоминание метро.
- `metro_primary` — первая найденная станция метро.
- `metro_count` — число станций метро в адресе.
- `search_area_id` — `area`, по которому выполнялся запрос (сейчас `113 = Россия`; в будущем поможет отличать РФ/BY/KZ и т.п.).
- `city_tier` — нормализованный уровень города: `Moscow / SPb / Million+ / Other RU / KZ/Other / unknown`.

**Зачем продукту**
- гео-аналитика зарплат: Москва/СПб/регионы/СНГ;
- анализ “дорогих” районов/локаций в мегаполисах;
- укрупнение городов в кластеры (Москва/СПб/миллионники/прочие).

---

## 3) Даты и «свежесть» вакансии

**Колонки**
- `published_at_raw`
- `published_at_iso`
- `scraped_at_utc`
- `vacancy_age_days`
- `published_weekday`
- `published_month`
- `is_weekend_post`

**Логика**
- `published_at_raw` — текст с hh («сегодня», «вчера», «26 ноября 2025»).
- `published_at_iso` — нормализованная дата `YYYY-MM-DD`.
- `scraped_at_utc` — момент запуска парсера (`datetime.now(timezone.utc)`).
- `vacancy_age_days` — дней между публикацией и сбором (`scraped_at - published_at`).
- `published_weekday` — день недели публикации (0 = понедельник, 6 = воскресенье).
- `published_month` — номер месяца публикации (1–12).
- `is_weekend_post` — булев флаг «вакансия опубликована в выходные».

**Зачем продукту**
- фильтровать актуальные вакансии;
- смотреть динамику по времени;
- в будущем — оценка “скорости закрытия” (на истории).

---

## 4) Работодатель: качество и тип компании

**Колонки**
- `employer_url`
- `employer_rating`
- `employer_reviews_count`
- `employer_has_remote`
- `employer_has_flexible_schedule`
- `employer_has_med_insurance`
- `employer_has_education`
- `employer_accredited_it`
- `employer_type`

**Логика**
- `employer_url` — страница работодателя на hh.
- `employer_rating` — рейтинг (0–5), парсится из JSON блока `employerReviews.totalRating`.
- `employer_reviews_count` — число отзывов (`reviewsCount`).
- `employer_has_remote` — удалёнка как системный плюс по преимуществам/отзывам.
- `employer_has_flexible_schedule` — упоминание гибкого графика.
- `employer_has_med_insurance` — ДМС/страховка как системный перк.
- `employer_has_education` — обучение/курсы за счёт компании.
- `employer_accredited_it` — флаг аккредитованной IT-компании (по бейджу/тексту).
- `employer_type` — `"direct"` (прямой работодатель), `"agency"` (кадровое агентство), `"other"`/`None`.

**Зачем продукту**
- различать “сильных” и “сомнительных” работодателей (рейтинг/отзывы);
- фильтры по типу работодателя;
- аккредитация IT важна для льгот;
- DMS/обучение/график — часть привлекательности оффера, не только зарплата.

---

## 5) Формат работы и занятость

**Колонки**
- `employment_type`
- `schedule`
- `work_format_raw`
- `work_format`
- `is_remote`
- `is_hybrid`
- `work_mode`

**Логика**
- `employment_type` — тип занятости (полная/частичная, проектная, стажировка и т.п.).
- `schedule` — график (полный день, сменный, гибкий и т.д.).
- `work_format_raw` — исходная формулировка формата (офис/удалённо/гибрид).
- `work_format` — нормализованное: `office / remote / hybrid / field / unknown`.
- `is_remote` — допускает полную удалёнку.
- `is_hybrid` — гибрид (часть офис, часть удалёнка).
- `work_mode` — агрегированный формат с приоритетом явного `work_format`, затем `is_remote`/`is_hybrid`; значения `remote / hybrid / office / field / unknown`.
- `unknown` в `work_mode` — формат не распознан и явно показан в отчёте, чтобы доли форматов интерпретировались корректно.

**Зачем продукту**
- удалёнка — ключевой фильтр и фактор выбора;
- сравнение зарплат по форматам;
- важный атрибут для “персон” (например, студент в другом городе).

---

## 6) Опыт и уровень позиции

**Колонки**
- `experience` (сырой текст)
- `exp_min_years`
- `exp_max_years`
- `exp_is_no_experience`
- `grade` (junior/middle/senior/lead/...)
- `grade_from_experience`
- `grade_final`
- `is_junior_friendly`
- `battle_experience`

**Логика**
- `experience` — строка hh («не требуется», «1–3 года», «3–6 лет», «более 6 лет»).
- `exp_min_years` / `exp_max_years` — числовые границы (0/3/6 и т.п.).
- `exp_is_no_experience` — `True` для «не требуется опыт».
- `grade` — нормализованный грейд по title/description:
  - junior/стажёр/младший → `junior`
  - middle/без указания → `middle` (по умолчанию)
  - senior/ведущий/старший → `senior`
  - возможны `lead`, `head` и т.п.
- `grade_from_experience` — грейд-прокси из опыта: 0–1 → `intern`, 1–3 → `junior`, 3–5 → `middle`, 5–8 → `senior`, 8+ → `lead`
  (использует числовые границы `exp_min_years`/`exp_max_years`, иначе fallback по тексту `experience`).
- `grade_final` — итоговый грейд для аналитики: берём `grade`, если он известен, иначе `grade_from_experience`; используется во всех графиках и персона-аналитике.
- `is_junior_friendly` — булев флаг, если вакансия явно допускает студентов/без опыта/входит в junior-пул (объединение `is_for_juniors`, `allows_students`, `exp_is_no_experience`).
- `battle_experience` — обратный флаг к `is_junior_friendly`, подчёркивает требование «боевого» опыта.

**Зачем продукту**
- карта «зарплата vs уровень» (ядро MVP);
- “где я сейчас / куда хочу”;
- `exp_min/max` пригодятся для прогнозов времени роста.

---

## 7) Роль в команде / тип позиции (role_*)

**Колонки (role_*)**
- `role_backend`, `role_frontend`, `role_fullstack`, `role_mobile`
- `role_data`, `role_ml`, `role_devops`, `role_qa`
- `role_manager`, `role_product`, `role_analyst`
- `role_count`
- `primary_role`

**Логика**
- классификация по словарям/регэкспам в `title + description`:
  - backend/frontend/fullstack/mobile,
  - data/BI/DWH → `role_data`,
  - DS/ML/ML engineer → `role_ml`,
  - DevOps/SRE → `role_devops`,
  - QA/тестирование → `role_qa`,
  - руководители → `role_manager`,
  - продакты → `role_product`,
  - широкие аналитики → `role_analyst`.
- одна вакансия может иметь несколько ролей (например, data + analyst).
- агрегаты:
  - `role_count` — количество сработавших флагов `role_*`;
  - `primary_role` — приоритезированная основная роль (ML → Data → DevOps → Backend → … → Analyst). Категориальный признак для аккуратных разрезов.

**Зачем продукту**
- разрезы зарплат и требований по трекам;
- карьерные переходы “из X в Y”;
- персонализация фильтрации под пользователя.

---

## 8) Текст описания и его структура

**Колонки**
- `description`
- `description_len_chars`
- `description_len_words`
- `description_bullets_count`
- `description_paragraphs_count`
- `requirements_count`
- `responsibilities_count`
- `optional_skills_count`
- `must_have_skills_count`

**Логика**
- `description` — чистый текст описания (без HTML).
- длины: `*_len_chars`, `*_len_words`
- структура:
  - `description_bullets_count` — количество буллетов (`<li>`, `-`, `•`)
  - `description_paragraphs_count` — количество параграфов (`<p>`/переносов)
- секции по маркерам «Обязанности», «Требования», «Условия», «Будет плюсом»:
  - `responsibilities_count` — число пунктов в обязанностях
  - `requirements_count` — число пунктов в требованиях
  - `must_have_skills_count` — число найденных skill-паттернов внутри секции требований
  - `optional_skills_count` — число skill-паттернов внутри «Будет плюсом»

**Зачем продукту**
- метрики структурированности/информативности вакансии;
- оценка “жёсткости” требований (must-have vs optional);
- хороший материал для качественных инсайтов (перегруженные требования, структура описаний).

---

## 9) Key skills (из блока hh) и агрегаты

**Колонки**
- `skills` — список навыков через запятую
- `skills_count`

**Логика**
- `skills` — “чипсы” keySkills на hh, объединённые в строку.
- `skills_count` — количество навыков в блоке.

**Зачем продукту**
- статистика топ-скиллов по рынку;
- сравнение профиля пользователя с требованиями рынка (“есть 3 из 8”).

---

## 10) Hard skills и стек технологий (has_*, skill_*, агрегаты)

**Таксономия hard skills в EDA**

- используем объединение столбцов `skill_*` и технологических `has_*` (функция `eda.hard_skill_columns`);
- явно исключаем нефункциональные флаги (`has_metro`, `has_test_task`, `has_mentoring` и другие, которые не описывают навык);
- доли навыков на графиках считаются как доля вакансий с флагом навыка (market share); этот же список используется в ноутбуке, HTML и persona skill-gap, чтобы избежать разъезда вселенных навыков.

### 10.1. Языки и фреймворки (has_*) — ~44 признака
**Языки программирования**
- `has_python`, `has_java`, `has_kotlin`, `has_csharp`, `has_cpp`, `has_go`, `has_php`
- `has_javascript`, `has_typescript`, `has_scala`, `has_rust`, `has_ruby`

**Backend / web**
- `has_django`, `has_flask`, `has_fastapi`, `has_dotnet`, `has_spring`
- `has_nodejs`, `has_express`, `has_nestjs`

**Frontend**
- `has_react`, `has_vue`, `has_angular`, `has_nextjs`, `has_nuxt`, `has_svelte`

**Data/ML библиотеки**
- `has_pandas`, `has_numpy`, `has_sklearn`, `has_pytorch`, `has_tensorflow`

**Data platform / streaming**
- `has_airflow`, `has_spark`, `has_kafka`

**DevOps/инфраструктура**
- `has_docker`, `has_kubernetes`, `has_terraform`, `has_ansible`, `has_jenkins`, `has_gitlab_ci`, `has_cicd`

**Особые флаги**
- `has_metro` (по адресу — фактически дубль из “локации”)
- `has_mentoring`, `has_test_task` (флаги по описанию: наставничество / тестовое задание)

**Логика**
- поиск упоминаний в `title + description + skills` по паттернам/регэкспам (case-insensitive, с вариантами написания).
- флаг `True`, если технология упоминается явно.
- Сервисные флаги `has_metro`/`has_mentoring`/`has_test_task` сохраняются для аналитики формата/джуниорности, но исключаются из `hard_skill_columns`, чтобы не попадать в топ навыков или persona skill-gap.

### 10.2. Специализированные data-навыки (skill_*)
**Колонки**
- `skill_sql`, `skill_excel`, `skill_powerbi`, `skill_tableau`
- `skill_clickhouse`, `skill_bigquery`, `skill_r`
- `skill_airflow`
- `skill_ab_testing`
- `skill_product_metrics`

**Логика**
- аналогично (паттерны в тексте), но сфокусировано на аналитике/BI/данных:
  - `skill_ab_testing` — A/B, AB-test, эксперименты
  - `skill_product_metrics` — продуктовые метрики, конверсия, retention, LTV, воронка, unit-экономика и т.п.

### 10.3. Агрегаты по стеку
**Колонки**
- `core_data_skills_count`
- `ml_stack_count`
- `tech_stack_size`
- `hard_stack_count`
- `skills_count` (агрегат по булевым `skill_*`)
- `benefits_count`
- `soft_skills_count`

**Логика**
- `core_data_skills_count` — количество “базовых” data-навыков из заданного набора (SQL, Excel, BI-инструменты, Python/R).
- `ml_stack_count` — количество ML-инструментов (sklearn, PyTorch, TensorFlow, Airflow, Spark, Kafka и т.п.).
- `tech_stack_size` — общее число `True` среди `has_*` и `skill_*`.
- `hard_stack_count` — число флагов `has_*` (ядро технологического стека вакансии).
- `skills_count` (агрегат) — число флагов `skill_*` (аналитические навыки из специализированного словаря).
- `benefits_count` — сколько преимуществ/плюшек указано (`benefit_*`).
- `soft_skills_count` — количество найденных soft skills (`soft_*`).

**Зачем продукту**
- heatmap «навык × зарплата/город/уровень»;
- профили вакансий (BI vs hardcore ML);
- skill-gap для пользователя (“не хватает X из Y”).

---

## 11) Языки (natural languages)

**Колонки**
- `lang_english_required`
- `lang_english_level` (none/basic/intermediate/upper_intermediate/advanced)
- `lang_other_count`

**Логика**
- парсинг упоминаний языков:
  - `lang_english_required` — факт требования английского,
  - `lang_english_level` — по ключам (B1/Intermediate, B2/Upper-Intermediate, C1/Advanced, fluent/свободный),
  - `lang_other_count` — сколько других языков упомянуто.
- `no_english/unknown` означает отсутствие явного требования; ~3.5% строк не позволяют восстановить уровень, поэтому доли по уровню английского немного смещены.

**Зачем продукту**
- английский как фильтр топ/международных вакансий;
- честная рекомендация персоне (“на dream вакансии нужен Upper-Intermediate+”).

---

## 12) Образование

**Колонки**
- `edu_required`
- `edu_level` (например, any_he / bachelor_or_higher / master_or_higher / none)
- `edu_technical`
- `edu_math_or_cs`
- `unknown`/отсутствие метки в `edu_*` означает, что требование не указано работодателем; в текущей выборке явных требований нет (≈100% строк), поэтому по образованию строим только вспомогательные признаки и не делаем рыночных выводов.

**Логика**
- по тексту `description`:
  - `edu_required` — “обязательно высшее/профильное”
  - `edu_level` — уровень требования (высшее/магистр/степень)
  - `edu_technical` — техническое образование
  - `edu_math_or_cs` — упоминание математики/информатики/прикладной математики

**Зачем продукту**
- важно для студентов/свитчеров (“достаточно ли образования”);
- сравнение вилок и доступности вакансий с/без требований к диплому.

---

## 13) Junior-friendly сигналы

**Колонки**
- `is_for_juniors`
- `allows_students`
- `has_mentoring`
- `has_test_task`

**Логика**
- `is_for_juniors`:
  - наличие junior/intern/стажёр/младший,
  - или `exp_is_no_experience == True`.
- `allows_students` — “для студентов”, “можно без полного высшего” и т.п.
- `has_mentoring` — наставничество/менторство.
- `has_test_task` — тестовое задание, coding challenge и т.п.

**Зачем продукту**
- точки входа для ключевых персон (магистр по данным, свитчер);
- фильтр вакансий “для старта”;
- сторителлинг (“часто есть менторство, но и тестовые”).

---

## 14) Бенефиты и условия (benefit_*)

**Колонки**
- `benefit_dms`
- `benefit_insurance`
- `benefit_sick_leave_paid`
- `benefit_vacation_paid`
- `benefit_relocation`
- `benefit_sport`
- `benefit_education`
- `benefit_remote_compensation`
- `benefit_stock`
- `benefits_count`

**Логика**
- по тексту условий:
  - ДМС/страховки, оплачиваемые больничные/отпуска,
  - релокация, спорт,
  - обучение/курсы,
  - компенсация удалёнки (интернет/домашний офис),
  - опционы/RSU/доли.

**Зачем продукту**
- total compensation (зарплата ≠ всё);
- сравнение пакетов у вакансий с разными вилками;
- помощь в выборе между офферами.

---

## 15) Soft skills

**Колонки**
- `soft_communication`
- `soft_teamwork`
- `soft_leadership`
- `soft_result_oriented`
- `soft_structured_thinking`
- `soft_critical_thinking`
- `soft_skills_count`

**Логика**
- по тексту требований:
  - коммуникация/взаимодействие,
  - командность,
  - лидерство,
  - ориентация на результат/проактивность,
  - структурное мышление,
  - критическое мышление.

**Зачем продукту**
- баланс hard/soft в карьерном навигаторе;
- дополнительные инсайты “что рынок просит”;
- потенциальная связь со “ставкой” (soft-навыки как маркер уровня).

---

## 16) Тематика / домен бизнеса (domain_*)

**Колонки**
- `domain_finance`
- `domain_ecommerce`
- `domain_telecom`
- `domain_state`
- `domain_retail`
- `domain_it_product`

**Логика**
- по ключевым словам в описании компании/проекта:
  - финансы/финтех/инвестиции,
  - e-commerce/маркетплейсы,
  - телеком/операторы,
  - госсектор/госкомпании,
  - ритейл,
  - продуктовые IT-компании.

**Зачем продукту**
- сравнение зарплат/требований по доменам;
- сценарии “аналитик в финтехе vs e-commerce”;
- персонализация рекомендаций по интересам.

---

## 17) Прочее / «связки» (клей)

Ключевые связующие признаки, используемые во многих аналитиках:
- `currency` (валютная шкала),
- `city`, `search_area_id` (гео),
- `is_remote`, `is_hybrid` (формат),
- `core_data_skills_count`, `ml_stack_count`, `tech_stack_size` (ширина требований),
- `vacancy_age_days` (актуальность/свежесть),
- все `is_*`, `has_*`, `skill_*` совместно образуют детальную “матрицу рынка”.

---

## Engineered features — быстрый справочник

| Признак | Тип | Источник/база | Назначение |
| --- | --- | --- | --- |
| `published_weekday`, `published_month`, `is_weekend_post` | int/bool | календарь из `published_at_iso` | сезонность публикаций, фильтр выходных |
| `vacancy_age_days` | int | `scraped_at_utc` и `published_at_iso` | свежесть вакансии, фильтр актуальных |
| `salary_mid_rub`, `salary_mid_rub_capped` | float | пересчёт зарплат в рубли и обрезка экстремумов | сопоставимая шкала компенсаций и устойчивые квантильные разрезы |
| `salary_bucket` | category | квантиль по `salary_mid_rub_capped` | стабильные разрезы зарплат без влияния выбросов |
| `city_tier` | category | нормализация `city` | укрупнённые города: Москва/СПб/миллионники/прочие/KZ |
| `work_mode` | category | агрегат `work_format`, `is_remote`, `is_hybrid` | единый формат для аналитики по удалёнке/гибриду |
| `grade_from_experience`, `grade_final` | category | правила на основе `exp_*` и fallback из `experience` | прокси-грейд и итоговый грейд для аналитики/персон; `grade_final` стабилизирует долю unknown в графиках |
| `role_count`, `primary_role` | int / category | сумма и приоритизация `role_*` | ширина роли и аккуратные срезы по основной роли |
| `is_junior_friendly`, `battle_experience` | bool | агрегат `is_for_juniors`/`allows_students`/`exp_is_no_experience` | фильтры «подходит новичкам» vs «нужен боевой опыт» |
| `description_len_chars`, `description_len_words` | int | длина `description` | полнота описания |
| `requirements_count`, `responsibilities_count`, `must_have_skills_count`, `optional_skills_count` | int | разметка секций описания | жёсткость требований и прозрачность обязанностей |
| `core_data_skills_count`, `ml_stack_count`, `tech_stack_size` | int | подсчёт `skill_*`/`has_*` по группам | насыщенность базового data-стека, ML-стека и всего стека |
| `hard_stack_count`, `skills_count`, `benefits_count`, `soft_skills_count`, `role_count` | int | сумма булевых `has_*`/`skill_*`/`benefit_*`/`soft_*`/`role_*` | размер технологического и компенсационного пакетов |
| `junior_friendly_flag`, `remote_flag` | bool | подготовленные флаги для `market_view` | вычисление долей junior-friendly и удалёнки в агрегатах |
| `vacancy_count_total` | int | агрегация в `market_view` | мощность сегмента роли × грейд × город/домен (все вакансии) |
| `vacancy_count_salary` | int | агрегация в `market_view` | сколько вакансий в сегменте имеют зарплату для расчёта квантилей (`salary_mid_rub_capped` не NaN) |
| `salary_median`, `salary_q25`, `salary_q75` | float | квантильные метрики `market_view` по `salary_mid_rub_capped` | устойчивые зарплатные ориентиры по сегменту на сопоставимой рублёвой шкале |
| `junior_friendly_share`, `remote_share` | float | средние по флагам в `market_view` | доля вакансий, допускающих новичков/удалёнку |
| `median_tech_stack_size` | float | медиана `tech_stack_size` в `market_view` | сложность технологических требований сегмента |
| `top_skills` | str | форматирование средних по `has_*`/`skill_*` в `market_view` | сжатый список самых востребованных навыков с долями |

---

## Итоговая иерархия признаков (сводка)
- **ID/паспорт вакансии**: `vacancy_*`, `title`, `company`, `vacancy_url`
- **Компенсация**: `salary_*`, `currency`
- **Локация**: `city`, `address*`, `has_metro`, `metro_*`, `search_area_id`
- **Время**: `published_*`, `vacancy_age_days`, `scraped_at_utc`
- **Работодатель**: `employer_*`
- **Формат работы**: `employment_type`, `schedule`, `work_format*`, `is_remote`, `is_hybrid`
- **Опыт/уровень**: `experience`, `exp_*`, `grade`
- **Роль**: `role_*`
- **Hard skills/стек**: `has_*`, `skill_*`, `core_data_skills_count`, `ml_stack_count`, `tech_stack_size`
- **Текст и структура**: `description`, `description_*`, `requirements_count`, `responsibilities_count`, `must_have_skills_count`, `optional_skills_count`
- **Key skills**: `skills`, `skills_count`
- **Языки/образование**: `lang_*`, `edu_*`
- **Junior-friendly**: `is_for_juniors`, `allows_students`, `has_mentoring`, `has_test_task`
- **Бенефиты**: `benefit_*`
- **Soft skills**: `soft_*`
- **Домен**: `domain_*`

Все блоки поддерживают цели Skillra:
- карта зарплат по регионам/уровням/ролям,
- топ-навыки и их комбинации,
- сценарии персон "что подтянуть, чтобы попасть в нужные вакансии",
- и дальнейшее развитие: ML-слой (прогноз зарплат и траекторий).
