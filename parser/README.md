# Скрапер вакансий HH.ru (Россия + СНГ по умолчанию)

Скрипт `hh_scraper.py` собирает вакансии в сфере IT по hh.ru, оставляя только позиции с указанной зарплатой. Парсинг основан на BeautifulSoup, данные сохраняются в CSV (по умолчанию `data/hh_moscow_it_YYYY_MM_DD_HH_MM_SS.csv`) с расширенным набором признаков на вакансию (зарплатные производные, опыт, формат работы, грейд, роли, стек, бенефиты, статистика текста, фичи работодателя). По умолчанию обходятся все страны СНГ (Россия, Беларусь, Казахстан, Армения, Украина, Азербайджан, Узбекистан, Киргизстан, Молдова, Грузия, Таджикистан, Туркмения) — при желании можно ограничиться конкретными `area_id` через флаг `--areas`.

Полный перечень собираемых полей и их описания приведён в [DATA_DICTIONARY.md](DATA_DICTIONARY.md).

## Установка зависимостей

```bash
python -m venv .venv
source .venv/bin/activate
pip install requests beautifulsoup4
```

## Запуск

Быстрый старт (парсинг по умолчанию до 10 000 вакансий, ~8 часов на полном прогоне):

```bash
python hh_scraper.py
```

Полезные флаги:

- `--query` — поисковая фраза (по умолчанию широкий `NAME:(...)` булевый фильтр, охватывающий разработку/QA/data/ML, SRE/платформенные роли, системное администрирование и поддержку, DBA, ИБ, аналитиков и архитекторов — см. DEFAULT_QUERY в коде).
- `--limit` — целевое число строк в датасете (по умолчанию 10000; для smoke-теста используйте `--limit 50` или временно поставьте `DEFAULT_LIMIT = 50`).
- `--delay` — базовая задержка между запросами с джиттером (по умолчанию 1.5 секунды).
- `--output` — путь для сохранения CSV.
- `--max-pages` — ограничение глубины пагинации для тестов.
- `--proxies` — путь к файлу со списком прокси (`scheme://user:pass@host:port`, по одному на строку), используется для ротации.
- `--areas` — список `area_id` (по умолчанию все страны СНГ: 113, 40, 159, 160, 5, 204, 237, 246, 111, 51, 194, 218). Можно указать, например, `--areas 1 2` для Москвы+СПб.

Пример с настройками и прокси:

```bash
python hh_scraper.py --query "Python разработчик" --limit 12000 \
  --delay 2.0 --proxies proxies.txt --output data/python_moscow.csv
```

## Что собирается

Для каждой вакансии сохраняются ключевые группы признаков:

- Идентификаторы и ссылки: `vacancy_id`, `vacancy_url`, `employer_url`, `vacancy_code`.
- Зарплата: `salary_from`, `salary_to`, `currency`, `salary_gross`, производные `salary_mid`, `salary_range_width`, `salary_is_exact`.
- Локация: `city`, `address`, фичи метро (`has_metro`, `metro_primary`, `metro_count`), `address_has_district`.
- Опыт: `experience`, числовые `exp_min_years`, `exp_max_years`, флаг `exp_is_no_experience`.
- Занятость и формат: `employment_type`, `schedule`, `work_format_raw`, классификация `work_format`, флаги `is_remote`, `is_hybrid`.
- Контент вакансии: `description`, длины и счётчики (`description_len_chars`, `description_len_words`, `description_bullets_count`, `description_paragraphs_count`), `skills`, `published_at_raw`.
- Классификация по грейду и ролям: `grade`, роли `role_backend`, `role_frontend`, `role_fullstack`, `role_mobile`, `role_data`, `role_ml`, `role_devops`, `role_qa`, `role_manager`, `role_product`, `role_analyst`.
- Технологический стек: булевы флаги `has_python`, `has_java`, `has_kotlin`, `has_csharp`, `has_cpp`, `has_go`, `has_php`, `has_javascript`, `has_typescript`, `has_scala`, `has_rust`, `has_ruby`, `has_django`, `has_flask`, `has_fastapi`, `has_dotnet`, `has_spring`, `has_nodejs`, `has_express`, `has_nestjs`, `has_react`, `has_vue`, `has_angular`, `has_nextjs`, `has_nuxt`, `has_svelte`, `has_pandas`, `has_numpy`, `has_sklearn`, `has_pytorch`, `has_tensorflow`, `has_airflow`, `has_spark`, `has_kafka`, `has_docker`, `has_kubernetes`, `has_terraform`, `has_ansible`, `has_jenkins`, `has_gitlab_ci`, `has_cicd`.
- Бенефиты: `benefit_dms`, `benefit_insurance`, `benefit_sick_leave_paid`, `benefit_vacation_paid`, `benefit_relocation`, `benefit_sport`, `benefit_education`, `benefit_remote_compensation`, `benefit_stock`.
- Работодатель: `employer_rating`, `employer_reviews_count`, `employer_has_remote`, `employer_has_flexible_schedule`, `employer_has_med_insurance`, `employer_has_education`, `employer_accredited_it`, `employer_type`.

## Обход ограничений HH

- Ротация User-Agent заголовков и реферера.
- Поддержка прокси-листа с поочередной сменой прокси между страницами.
- HTTP retries с экспоненциальной паузой на типичные коды блокировки (429/5xx).
- Рандомизированные задержки между запросами, чтобы снизить частоту.
- Пагинация ведётся по нескольким «шарам» опыта (noExperience, 1–3, 3–6, 6+), что помогает обойти ограничение HH на ~2000 результатов в пределах одной выдачи.

## Совет по отладке

Для быстрого теста без долгого ожидания используйте `--limit 50 --max-pages 2`, чтобы убедиться, что CSV формируется корректно, а затем запускайте полноценный сбор.

Минимальный smoke-тест на пару страниц выдачи:

```bash
python hh_scraper.py --limit 30 --max-pages 1 --delay 0.5
```

Эвристические признаки (grade, english, work_format) вычисляются по тексту вакансии и могут ошибаться на пограничных случаях. Для важных выгрузок проверяйте качество на маленьком лимите и корректируйте паттерны при необходимости.

## Запуск

1. Создайте **Run Configuration** типа *Python*: в поле **Script path** укажите `hh_scraper.py`, а в **Parameters** добавьте нужные флаги (например, `--query "Python" --limit 12000 --proxies proxies.txt`).
2. Убедитесь, что рабочая директория в конфигурации указывает на корень проекта, чтобы путь вида `data/hh_moscow_it_YYYY_MM_DD_HH_MM_SS.csv` создавался корректно.
3. Запустите конфигурацию (зелёная кнопка Run). По завершении увидите сообщение `Saved N rows to data/hh_moscow_it_YYYY_MM_DD_HH_MM_SS.csv`, а CSV появится в каталоге `data/`.

Совет: на время отладки можете временно поставить `--limit 50 --max-pages 2`, чтобы не ждать полный сбор 10k строк; полноценный дневной запуск оставляйте с `DEFAULT_LIMIT`/`--limit 10000`, чтобы постепенно накопить 500k+ вакансий.
