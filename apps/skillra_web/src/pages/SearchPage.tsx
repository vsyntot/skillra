/**
 * SearchPage — full-text vacancy search via MeiliSearch.
 * Sprint-008 TASK-05
 */
import { useEffect, useState } from 'react'
import DataFreshnessIndicator from '../components/DataFreshnessIndicator'
import MetaSelect from '../components/MetaSelect'
import TrustLabels from '../components/TrustLabels'
import { useVacancySearch } from '../hooks/useVacancySearch'
import { ApplicationOutcomeStatus, VacancySearchResult } from '../api/client'
import { useCareerPlan, useSaveCareerPlanVacancy, useUpdateApplicationOutcome } from '../hooks/useCareerPlan'
import { useCurrentUserProfile } from '../hooks/useCurrentUserProfile'

export default function SearchPage() {
  const [query, setQuery] = useState(() => readSearchParam('q'))
  const [debouncedQuery, setDebouncedQuery] = useState(() => readSearchParam('q'))
  const [filters, setFilters] = useState(() => initialSearchFilters())
  const [offset, setOffset] = useState(() => Number(readSearchParam('offset')) || 0)
  const [profileApplied, setProfileApplied] = useState(false)
  const [savedActions, setSavedActions] = useState<Record<string, { actionId: number; status: string | null }>>({})
  const [saveError, setSaveError] = useState<string | null>(null)
  const limit = 20
  const { effectiveUserId, profile, isUserMode } = useCurrentUserProfile()
  const { data: careerPlan, isLoading: isCareerPlanLoading } = useCareerPlan(effectiveUserId)
  const saveVacancy = useSaveCareerPlanVacancy(effectiveUserId)
  const updateOutcome = useUpdateApplicationOutcome(effectiveUserId)

  // Debounce search query
  useEffect(() => {
    const timer = setTimeout(() => setDebouncedQuery(query), 300)
    return () => clearTimeout(timer)
  }, [query])

  useEffect(() => {
    if (typeof window === 'undefined') return
    const params = new URLSearchParams()
    if (query.trim()) params.set('q', query.trim())
    Object.entries(filters).forEach(([key, value]) => {
      if (value) params.set(key, value)
    })
    if (offset > 0) params.set('offset', String(offset))
    const nextUrl = `${window.location.pathname}${params.toString() ? `?${params.toString()}` : ''}`
    if (`${window.location.pathname}${window.location.search}` !== nextUrl) {
      window.history.replaceState(null, '', nextUrl)
    }
  }, [filters, offset, query])

  useEffect(() => {
    if (!isUserMode || !profile || profileApplied) return
    setFilters((current) => ({
      ...current,
      role: profile.target_role ?? '',
      grade: profile.target_grade ?? '',
      country: profile.target_country ?? '',
      region: profile.target_region ?? '',
      city: profile.target_city ?? '',
      geo_scope: profile.target_geo_scope ?? '',
    }))
    setProfileApplied(true)
  }, [isUserMode, profile, profileApplied])

  useEffect(() => {
    if (!careerPlan) {
      setSavedActions({})
      return
    }
    const hydrated = careerPlan.actions.reduce<Record<string, { actionId: number; status: string | null }>>(
      (current, action) => {
        if (!action.hh_vacancy_id) return current
        current[action.hh_vacancy_id] = {
          actionId: action.id,
          status: action.application_status ?? (action.action_type === 'saved_vacancy' ? 'saved' : null),
        }
        return current
      },
      {},
    )
    setSavedActions(hydrated)
  }, [careerPlan])

  const { data, isLoading, isError } = useVacancySearch(
    debouncedQuery,
    {
      role: filters.role || undefined,
      grade: filters.grade || undefined,
      country: filters.country || undefined,
      region: filters.region || undefined,
      city: filters.city || undefined,
      geo_scope: filters.geo_scope || undefined,
      skill: filters.skill || undefined,
      telegram_user_id: isUserMode && effectiveUserId > 0 ? effectiveUserId : undefined,
      source: isUserMode ? 'web' : 'api',
    },
    { limit, offset },
  )
  const hasSearched = debouncedQuery.trim().length >= 1
  const vacancies = data?.results ?? []
  const hasCareerPlan = careerPlan != null
  const canSaveVacancy = isUserMode && effectiveUserId > 0 && hasCareerPlan && !isCareerPlanLoading
  const differsFromProfile =
    isUserMode &&
    profile != null &&
    ((profile.target_role ?? '') !== filters.role ||
      (profile.target_grade ?? '') !== filters.grade ||
      (profile.target_country ?? '') !== filters.country ||
      (profile.target_region ?? '') !== filters.region ||
      (profile.target_city ?? '') !== filters.city ||
      (profile.target_geo_scope ?? '') !== filters.geo_scope)

  const handleSaveVacancy = (vacancy: VacancySearchResult) => {
    if (effectiveUserId <= 0) return
    setSaveError(null)
    saveVacancy.mutate(
      {
        hh_vacancy_id: vacancy.hh_vacancy_id,
        title: vacancy.title,
        url: vacancy.hh_url ?? vacancy.url,
      },
      {
        onSuccess: (action) => {
          setSavedActions((current) => ({
            ...current,
            [vacancy.hh_vacancy_id]: {
              actionId: action.id,
              status: action.application_status ?? 'saved',
            },
          }))
        },
        onError: () => {
          setSaveError('Не удалось сохранить вакансию. Проверьте, что карьерный план создан.')
        },
      },
    )
  }

  const handleOutcome = (vacancyId: string, status: ApplicationOutcomeStatus) => {
    const saved = savedActions[vacancyId]
    if (!saved || effectiveUserId <= 0) return
    setSaveError(null)
    updateOutcome.mutate(
      { actionId: saved.actionId, payload: { status } },
      {
        onSuccess: (action) => {
          setSavedActions((current) => ({
            ...current,
            [vacancyId]: {
              actionId: action.id,
              status: action.application_status ?? null,
            },
          }))
        },
        onError: () => {
          setSaveError('Не удалось обновить статус отклика.')
        },
      },
    )
  }

  return (
    <div className="max-w-3xl mx-auto p-6">
      <div className="mb-6 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <h1 className="text-2xl font-bold text-gray-900">Поиск вакансий</h1>
        <DataFreshnessIndicator />
      </div>

      <div className="bg-white rounded-2xl border border-gray-200 p-4 mb-6 space-y-3">
        <input
          type="text"
          value={query}
          onChange={(e) => {
            setQuery(e.target.value)
            setOffset(0)
          }}
          placeholder="Поиск по вакансиям..."
          className="w-full border border-gray-300 rounded-lg px-4 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
        />

        <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
          <MetaSelect
            kind="roles"
            label="Роль"
            value={filters.role}
            onChange={(value) => {
              setFilters((f) => ({ ...f, role: value }))
              setOffset(0)
            }}
          />
          <MetaSelect
            kind="grades"
            label="Грейд"
            value={filters.grade}
            onChange={(value) => {
              setFilters((f) => ({ ...f, grade: value }))
              setOffset(0)
            }}
          />
          <MetaSelect
            kind="countries"
            label="Страна"
            value={filters.country}
            onChange={(value) => {
              setFilters((f) => ({ ...f, country: value }))
              setOffset(0)
            }}
          />
          <MetaSelect
            kind="regions"
            label="Регион"
            value={filters.region}
            onChange={(value) => {
              setFilters((f) => ({ ...f, region: value }))
              setOffset(0)
            }}
          />
          <MetaSelect
            kind="cities"
            label="Город"
            value={filters.city}
            onChange={(value) => {
              setFilters((f) => ({ ...f, city: value }))
              setOffset(0)
            }}
          />
          <MetaSelect
            kind="geoScopes"
            label="Рынок"
            value={filters.geo_scope}
            onChange={(value) => {
              setFilters((f) => ({ ...f, geo_scope: value }))
              setOffset(0)
            }}
          />
          <MetaSelect
            kind="skills"
            label="Навык"
            value={filters.skill}
            onChange={(value) => {
              setFilters((f) => ({ ...f, skill: value }))
              setOffset(0)
            }}
          />
        </div>

        {differsFromProfile && (
          <p className="text-xs text-amber-700">
            Фильтры отличаются от сохранённого профиля.
          </p>
        )}

        {isUserMode && !isCareerPlanLoading && !hasCareerPlan && (
          <div className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-800">
            Создайте карьерный план, чтобы сохранять вакансии и вести статусы откликов.
            <a href="/career-plan" className="ml-2 font-medium text-amber-900 underline">
              Создать план
            </a>
          </div>
        )}
      </div>

      {isLoading && (
        <div className="space-y-3">
          {Array.from({ length: 3 }).map((_, i) => (
            <div key={i} className="bg-white rounded-xl border border-gray-200 p-4 animate-pulse">
              <div className="h-4 bg-gray-200 rounded w-2/3 mb-2" />
              <div className="h-3 bg-gray-200 rounded w-1/3" />
            </div>
          ))}
        </div>
      )}

      {isError && (
        <p className="text-red-600 text-sm bg-red-50 rounded-lg px-4 py-3">
          Ошибка поиска. Возможно, MeiliSearch не настроен.
        </p>
      )}

      {data && !isLoading && (
        <>
          <p className="text-sm text-gray-500 mb-4">Найдено: {data.total}</p>
          <div className="mb-4">
            <TrustLabels
              trust={{
                dataset_run_id: data.dataset_run_id,
                generated_at: data.generated_at,
                generated_at_utc: data.generated_at_utc,
                freshness: data.freshness,
                sample_size: data.sample_size,
                confidence: data.confidence,
                warnings: data.warnings,
              }}
            />
            {data.index_status && (
              <p className="mt-2 text-xs text-gray-500">
                Индекс: {data.index_status}
                {data.index_dataset_run_id && ` · run ${data.index_dataset_run_id}`}
              </p>
            )}
            {data.search_state && data.search_state !== 'ready' && (
              <p className="mt-2 rounded-lg border border-amber-100 bg-amber-50 px-3 py-2 text-xs text-amber-800">
                Поиск работает в ограниченном режиме: {data.degraded_reason ?? searchStateLabel(data.search_state)}
              </p>
            )}
          </div>

          {saveError && (
            <p className="mb-4 rounded-lg border border-red-100 bg-red-50 px-4 py-3 text-sm text-red-700">
              {saveError}
            </p>
          )}

          {vacancies.length === 0 && hasSearched && (
            <div className="rounded-lg border border-amber-200 bg-amber-50 p-4">
              <h3 className="font-semibold text-amber-800">Вакансии не найдены</h3>
              {data.index_status && data.index_status !== 'success' ? (
                <p className="text-amber-700 mt-1">
                  Индекс поиска сейчас обновляется или ещё не готов. Попробуйте изменить запрос или вернуться позже.
                </p>
              ) : (
                <p className="text-amber-700 mt-1">
                  По вашему запросу ничего не найдено. Попробуйте изменить критерии поиска.
                </p>
              )}
            </div>
          )}

          <div className="space-y-3">
            {vacancies.map((vacancy) => (
              <VacancyCard
                key={vacancy.hh_vacancy_id}
                vacancy={vacancy}
                savedStatus={savedActions[vacancy.hh_vacancy_id]?.status ?? null}
                canSave={canSaveVacancy}
                isSaving={saveVacancy.isPending || updateOutcome.isPending}
                onSave={() => handleSaveVacancy(vacancy)}
                onOutcome={(status) => handleOutcome(vacancy.hh_vacancy_id, status)}
              />
            ))}
          </div>

          {data.total > limit && (
            <div className="flex gap-3 mt-6">
              <button
                onClick={() => setOffset((o) => Math.max(0, o - limit))}
                disabled={offset === 0}
                className="bg-gray-100 text-gray-700 rounded-lg px-4 py-2 text-sm disabled:opacity-50"
              >
                ← Назад
              </button>
              <button
                onClick={() => setOffset((o) => o + limit)}
                disabled={offset + limit >= data.total}
                className="bg-gray-100 text-gray-700 rounded-lg px-4 py-2 text-sm disabled:opacity-50"
              >
                Вперёд →
              </button>
            </div>
          )}
        </>
      )}
    </div>
  )
}

function VacancyCard({
  vacancy,
  savedStatus,
  canSave,
  isSaving,
  onSave,
  onOutcome,
}: {
  vacancy: VacancySearchResult
  savedStatus: string | null
  canSave: boolean
  isSaving: boolean
  onSave: () => void
  onOutcome: (status: ApplicationOutcomeStatus) => void
}) {
  const salaryText =
    vacancy.salary_from || vacancy.salary_to
      ? [vacancy.salary_from && `от ${(vacancy.salary_from / 1000).toFixed(0)}k`, vacancy.salary_to && `до ${(vacancy.salary_to / 1000).toFixed(0)}k`]
          .filter(Boolean)
          .join(' ') + ' ₽'
      : null
  const matchedSkills = vacancy.matched_skills ?? []
  const missingSkills = vacancy.missing_skills ?? []

  return (
    <div className="bg-white rounded-xl border border-gray-200 p-4 hover:border-blue-300 transition-colors">
      <div className="flex items-start justify-between gap-4 mb-2">
        <div>
          <h3 className="text-sm font-semibold text-gray-900">{vacancy.title}</h3>
          <p className="text-xs text-gray-500 mt-0.5">
            {[vacancy.primary_role, vacancy.grade, vacancy.city_normalized ?? vacancy.city, vacancy.geo_scope]
              .filter(Boolean)
              .join(' · ')}
          </p>
        </div>
        <div className="flex shrink-0 flex-col items-end gap-1">
          {salaryText && <span className="text-sm font-medium text-green-700 whitespace-nowrap">{salaryText}</span>}
          {vacancy.match_score != null && (
            <span className="rounded bg-blue-50 px-2 py-1 text-xs font-medium text-blue-700">
              Матч {vacancy.match_score}% · {matchLevelLabel(vacancy.match_level)}
            </span>
          )}
        </div>
      </div>

      {vacancy.skills.length > 0 && (
        <div className="flex flex-wrap gap-1 mt-2">
          {vacancy.skills.slice(0, 8).map((skill) => (
            <span key={skill} className="text-xs bg-gray-100 text-gray-600 rounded px-1.5 py-0.5">
              {skill}
            </span>
          ))}
        </div>
      )}

      {(vacancy.fit_reason || vacancy.gap_reason || vacancy.plan_relevance) && (
        <div className="mt-3 space-y-1.5 rounded-lg bg-gray-50 px-3 py-2 text-xs text-gray-700">
          {vacancy.fit_reason && (
            <p>
              <span className="font-medium text-gray-900">Почему подходит:</span> {vacancy.fit_reason}
            </p>
          )}
          {vacancy.gap_reason && (
            <p>
              <span className="font-medium text-gray-900">Что подтянуть:</span> {vacancy.gap_reason}
            </p>
          )}
          {vacancy.plan_relevance && (
            <p>
              <span className="font-medium text-gray-900">Связь с планом:</span> {vacancy.plan_relevance}
            </p>
          )}
        </div>
      )}

      {(matchedSkills.length > 0 || missingSkills.length > 0) && (
        <div className="mt-2 flex flex-wrap gap-1.5">
          {matchedSkills.slice(0, 5).map((skill) => (
            <span key={`matched-${skill}`} className="rounded bg-emerald-50 px-1.5 py-0.5 text-xs text-emerald-700">
              Уже есть: {skill}
            </span>
          ))}
          {missingSkills.slice(0, 5).map((skill) => (
            <span key={`missing-${skill}`} className="rounded bg-amber-50 px-1.5 py-0.5 text-xs text-amber-700">
              Gap: {skill}
            </span>
          ))}
        </div>
      )}

      <div className="mt-3 flex flex-wrap items-center gap-2">
        {vacancy.url && (
          <a
            href={vacancy.url}
            target="_blank"
            rel="noreferrer"
            className="text-xs text-blue-600 hover:underline"
          >
            Открыть на hh.ru →
          </a>
        )}
        {canSave && !savedStatus && (
          <button
            type="button"
            onClick={onSave}
            disabled={isSaving}
            className="rounded-lg border border-blue-200 px-3 py-1.5 text-xs font-medium text-blue-700 hover:bg-blue-50 disabled:opacity-50"
          >
            Сохранить в план
          </button>
        )}
        {savedStatus && (
          <>
            <span className="rounded bg-green-50 px-2 py-1 text-xs font-medium text-green-700">
              {outcomeLabel(savedStatus)}
            </span>
            {(['applied', 'interview', 'offer', 'rejected'] as ApplicationOutcomeStatus[]).map((status) => (
              <button
                key={status}
                type="button"
                onClick={() => onOutcome(status)}
                disabled={isSaving || savedStatus === status}
                className="rounded-lg border border-gray-200 px-2.5 py-1.5 text-xs font-medium text-gray-700 hover:border-blue-300 disabled:opacity-50"
              >
                {outcomeLabel(status)}
              </button>
            ))}
          </>
        )}
      </div>
    </div>
  )
}

function outcomeLabel(status: string): string {
  switch (status) {
    case 'saved':
      return 'Сохранено'
    case 'applied':
      return 'Отклик'
    case 'interview':
      return 'Интервью'
    case 'offer':
      return 'Оффер'
    case 'rejected':
      return 'Отказ'
    case 'withdrawn':
      return 'Снято'
    default:
      return status
  }
}

function readSearchParam(name: string): string {
  if (typeof window === 'undefined') return ''
  return new URLSearchParams(window.location.search).get(name) ?? ''
}

function initialSearchFilters() {
  return {
    role: readSearchParam('role'),
    grade: readSearchParam('grade'),
    country: readSearchParam('country'),
    region: readSearchParam('region'),
    city: readSearchParam('city'),
    geo_scope: readSearchParam('geo_scope'),
    skill: readSearchParam('skill'),
  }
}

function matchLevelLabel(level: VacancySearchResult['match_level']): string {
  switch (level) {
    case 'high':
      return 'сильный'
    case 'medium':
      return 'средний'
    case 'low':
      return 'низкий'
    default:
      return 'неточно'
  }
}

function searchStateLabel(state: string): string {
  switch (state) {
    case 'fallback':
      return 'результаты получены из резервного источника'
    case 'degraded':
      return 'индекс поиска обновляется или неполный'
    case 'unavailable':
      return 'статус индекса недоступен'
    default:
      return state
  }
}
