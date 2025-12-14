# Skillra HSE PDA

Учебный проект по курсу «Python для анализа данных» (ВШЭ), который служит продуктовым фундаментом для Skillra Career & Job Market Navigator. Пайплайн строит витрину рынка IT-вакансий, EDA и продуктовые инсайты (персоны, skill-gap) для дальнейшей интеграции в сервис Skillra.

## Структура репозитория
- `data/` — исходные (`raw/`) и обработанные (`processed/`) данные, включая итоговую витрину рынка.
- `docs/` — дополнительная документация (например, словарь признаков HH).
- `notebooks/` — основной ноутбук отчёта `01_hse_project.ipynb` (этапы 0–4, EDA, персоны, выводы).
- `parser/` — компоненты для сбора вакансий с hh.ru.
- `src/skillra_pda/` — пакет с логикой проекта (`cleaning.py`, `features.py`, `eda.py`, `viz.py`, `market.py`, `personas.py`).
- `scripts/` — точки входа пайплайна (`run_pipeline.py`, `validate_pipeline.py`, `validate_notebook.py`).
- `tests/` — юнит-тесты основных модулей.
- `reports/` — артефакты визуализаций (`figures/`).

## Установка окружения
1. Создайте виртуальное окружение: `python -m venv .venv && source .venv/bin/activate`.
2. Установите зависимости: `pip install -r requirements.txt` или `pip install -e . -r requirements.txt` для editable-режима (в них уже есть parquet‑движок `pyarrow`). При необходимости установите `pyarrow` отдельно: `pip install pyarrow`.
3. Убедитесь, что сырые данные лежат по умолчанию в `data/raw/hh_moscow_it_2025_11_30.csv` (путь можно изменить в `src/skillra_pda/config.py`).

## Запуск пайплайна
- Полный аналитический цикл: `python scripts/run_pipeline.py` — очистка, генерация признаков и сборка витрины рынка (`hh_clean.parquet`, `hh_features.parquet`, `market_view.parquet`) в `data/processed/`.
- Быстрый smoke-чек: `python scripts/validate_pipeline.py` — проверка ключевых инвариантов и путей; по ходу считается `grade_final`, чтобы закрыть пропуски по грейду и делать графики/персоны устойчивыми.
- Headless-прогон ноутбука и HTML-отчёта: `python scripts/validate_notebook.py` — подтянет артефакты из `data/processed/` (или соберёт их, если их нет), прогонит ноутбук и соберёт HTML с графиками.

## Парсер hh.ru
- Полный сбор свежих IT-вакансий: `python parser/hh_scraper.py --limit 10000` (по умолчанию широкая булева строка по IT-ролям, регионы СНГ, задержки и ротация user-agent). Такой прогон может занять ~8 часов и сохранит CSV в `data/raw/`.
- Тестовый/быстрый прогон: временно поставьте `DEFAULT_LIMIT = 50` в `parser/hh_scraper.py` или запустите `python parser/hh_scraper.py --limit 50 --output data/raw/hh_test.csv`.
- Скрипт принимает параметры для `--areas`, `--max-pages`, `--proxies`, `--output`; ежедневный запуск собирает дельту активных вакансий и помогает накопить >500k строк. Детали — в `parser/README.md`.

## Проверка и тесты
- Юнит-тесты: `pytest`.
- Повторное выполнение ноутбука и генерация HTML: `python scripts/validate_notebook.py` — выполняет ноутбук end-to-end и собирает HTML с встроенными графиками.

## HTML-отчёт
- Команда: `python scripts/validate_notebook.py` — выполнит пайплайн, прогонит ноутбук и соберёт HTML с графиками (код скрыт и не попадает в итоговый файл).
- HTML содержит все графики, сохранённые в `reports/figures/`, встраивает их внутрь и не требует доступа к файлам.
- Путь сохранения: `reports/notebooks/01_hse_project.html` (папки создаются автоматически).
- Назначение: презентационный отчёт для демонстраций/защиты (инвесторы, руководители, преподаватель) без необходимости открывать ноутбук.

## Работа с анализом/ноутбуком
Откройте `notebooks/01_hse_project.ipynb`. Внутри:
- Вводная и этап 0: описание парсера hh.ru, сырой датасет, ограничения.
- Этап 1: предобработка (очистка, дубликаты, пропуски, обработка зарплат, каппинг выбросов).
- Этап 2: генерация признаков (city_tier, work_mode, primary_role, stack-size, junior_friendly, `grade_from_experience` и `grade_final`).
- Этап 3: EDA — зарплаты, форматы работы, роли, навыки, домены, английский, образование, работодатели, корреляционный анализ.
- Этап 4: визуализации/сводка и продуктовый слой с персонами, итоговые выводы и чек-лист ТЗ.

## Ключевые артефакты
- `data/processed/hh_clean.parquet` — очищенный датасет вакансий.
- `data/processed/hh_features.parquet` — данные с engineered-признаками для дальнейшей аналитики и персон.
- `data/processed/market_view.parquet` — агрегированная витрина (роль × грейд × город/домен) с зарплатами, долями remote/junior-friendly, размерами стеков и топовыми навыками.
- `reports/figures/*.png` — сохранённые графики EDA (подхватываются в HTML-отчёте и не хранят код).

## Personas API
Используйте `src/skillra_pda/personas.analyze_persona` на фичевом датасете. Поля `Persona` должны совпадать с колонками, которые генерирует пайплайн (`primary_role`, `grade_final`, `city_tier`, `work_mode` и бинарные признаки `has_*`/`skill_*` для навыков). `current_skills` — список таких признаков, например `"skill_sql"`, `"has_python"`.
```python
import pandas as pd
from src.skillra_pda.personas import Persona, analyze_persona, plot_persona_skill_gap

# Готовый датасет после пайплайна (python scripts/run_pipeline.py)
features = pd.read_parquet("data/processed/hh_features.parquet")

persona = Persona(
    name="switcher_bi",
    description="Свитчер в BI/продакт-аналитику",
    current_skills=["skill_excel", "skill_powerbi"],
    target_role="product",
    target_grade="junior",
    target_city_tier=None,
    target_work_mode=None,
)

result = analyze_persona(features, persona, top_k=10)
print(result["market_summary"])  # объём и зарплаты целевого сегмента
print(result["recommended_skills"])  # навыки, которых не хватает персоне

gap_plot = plot_persona_skill_gap(result["skill_gap"], persona)
print(f"График скилл-гапа: {gap_plot}")
```
Существуют предопределённые персоны (`DATA_STUDENT`, `SWITCHER_BI`, `MID_DATA_ANALYST`) в `src/skillra_pda/personas.py` — их можно использовать без ручной инициализации.

## Связь с продуктом Skillra
Полученные витрины и визуализации помогают Skillra:
- строить карту рынка по ролям/грейдам/городам с зарплатами и форматами работы;
- выявлять skill-gap для разных сценариев (студент, свитчер, middle) через Personas API;
- генерировать рекомендации и подсказки для пользователя Career & Job Market Navigator.

## Runbook (pipeline → notebook → HTML)
1. Запустить пайплайн: `python scripts/run_pipeline.py` → формируются `hh_clean.parquet`, `hh_features.parquet` (с `grade_final`) и `market_view.parquet` в `data/processed/`.
2. Быстрая регрессионная проверка пайплайна: `python scripts/validate_pipeline.py` — прогоняет очистку и генерацию признаков заново, валидирует инварианты и сохраняет свежие `hh_clean.parquet`/`hh_features.parquet`/`market_view.parquet` в `data/processed/`.
3. Выполнить ноутбук: открыть `notebooks/01_hse_project.ipynb` и прогнать все ячейки или вызвать `python scripts/validate_notebook.py` для headless-выполнения. В процессе сохраняются графики в `reports/figures/` и итоговый HTML.
4. Собрать презентационный отчёт: `python scripts/validate_notebook.py` генерирует `reports/notebooks/01_hse_project.html` с встроенными графиками без кода (папки `reports/notebooks/` и `reports/figures/` создаются автоматически).

## Data Quality & покрытия
- Сырые пропуски и маркеры неопределённости конвертируются в `NaN`, а служебный `unknown` хранится только в ограниченном наборе колонок (грейд, формат работы, английский и др.).
- Зарплаты приводятся к рублям и каппятся (`salary_mid_rub_capped`), чтобы графики и квантильные метрики не «ехали» на экстремумах.
- `salary_range_specified_share` отражает долю вакансий с указанной вилкой (`salary_from`/`salary_to` или `salary_mid`) и может быть близкой к 100% по политике датасета, но для зарплатных выводов критична метрика `salary_rub_available_share` — только она показывает, сколько строк реально пригодны для сравнения в рублях.
- Итоговый грейд `grade_final` снижает долю неопределённости и используется в графиках/персонах вместо исходного `grade`.
- Графики и HTML собираются из подготовленных артефактов (`data/processed/*`, `reports/figures/*`), что делает результаты воспроизводимыми.
- График «ключевые роли» строится по multi-label флагам `role_*`, чтобы не терять фронтенд/фуллстек/продуктовые роли; `primary_role` остаётся упрощённой однослойной сегментацией для других срезов.
