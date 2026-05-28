/**
 * MarketPage — market analysis with filters.
 * Sprint-006 TASK-09
 */
import { useEffect, useRef, useState } from 'react'
import { trackProductEvent } from '../api/client'
import type { SegmentFilters } from '../api/client'
import { useMarket } from '../hooks/useMarket'
import MarketCard from '../components/MarketCard'
import MetaSelect from '../components/MetaSelect'
import DataFreshnessIndicator from '../components/DataFreshnessIndicator'
import { usePersistedFilters } from '../hooks/usePersistedFilters'
import { profileToSegmentFilters, segmentDiffersFromProfile } from '../hooks/profileDefaults'
import { useCurrentUserProfile } from '../hooks/useCurrentUserProfile'

export default function MarketPage() {
  const [filters, setFilters] = usePersistedFilters<SegmentFilters>('skillra_market_filters', {})
  const [submitted, setSubmitted] = useState<SegmentFilters | null>(filters)
  const [profileApplied, setProfileApplied] = useState(false)
  const { effectiveUserId, profile, isUserMode } = useCurrentUserProfile()
  const trackedViews = useRef<Set<string>>(new Set())

  const { data, isLoading, isError } = useMarket(submitted ?? {})
  const differsFromProfile = isUserMode && segmentDiffersFromProfile(filters, profile)

  useEffect(() => {
    if (!isUserMode || !profile || profileApplied) return
    const profileFilters = profileToSegmentFilters(profile)
    setFilters(profileFilters)
    setSubmitted(profileFilters)
    setProfileApplied(true)
  }, [isUserMode, profile, profileApplied, setFilters])

  useEffect(() => {
    if (!isUserMode || effectiveUserId <= 0 || !data) return
    const key = `${effectiveUserId}:${JSON.stringify(submitted ?? {})}:${data.dataset_run_id ?? ''}:${data.vacancy_count}`
    if (trackedViews.current.has(key)) return
    trackedViews.current.add(key)
    trackProductEvent(effectiveUserId, {
      event_name: 'market_fit_viewed',
      surface: 'web',
      entity_type: 'market_segment',
      metadata: {
        filters: Object.entries(submitted ?? {}).filter(([, value]) => Boolean(value)).map(([field]) => field),
        dataset_run_id: data.dataset_run_id,
        trust_tier: data.freshness === 'stale' ? 'stale_data' : data.confidence === 'high' ? 'trusted' : 'limited_sample',
        confidence: data.confidence,
        freshness: data.freshness,
        vacancy_count: data.vacancy_count,
      },
    })
  }, [data, effectiveUserId, isUserMode, submitted])

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    setSubmitted({ ...filters })
  }

  return (
    <div className="max-w-3xl mx-auto p-6">
      <div className="mb-6 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <h1 className="text-2xl font-bold text-gray-900">Анализ рынка</h1>
        <DataFreshnessIndicator />
      </div>

      <form onSubmit={handleSubmit} className="bg-white rounded-2xl border border-gray-200 p-6 mb-6 space-y-4">
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <MetaSelect
            kind="roles"
            label="Роль"
            value={filters.role ?? ''}
            onChange={(v) => setFilters((f) => ({ ...f, role: v || null }))}
          />
          <MetaSelect
            kind="grades"
            label="Грейд"
            value={filters.grade ?? ''}
            onChange={(v) => setFilters((f) => ({ ...f, grade: v || null }))}
          />
          <MetaSelect
            kind="cityTiers"
            label="Уровень города"
            value={filters.city_tier ?? ''}
            onChange={(v) => setFilters((f) => ({ ...f, city_tier: v || null }))}
          />
          <MetaSelect
            kind="countries"
            label="Страна"
            value={filters.country ?? ''}
            onChange={(v) => setFilters((f) => ({ ...f, country: v || null }))}
          />
          <MetaSelect
            kind="regions"
            label="Регион"
            value={filters.region ?? ''}
            onChange={(v) => setFilters((f) => ({ ...f, region: v || null }))}
          />
          <MetaSelect
            kind="cities"
            label="Город"
            value={filters.city ?? ''}
            onChange={(v) => setFilters((f) => ({ ...f, city: v || null }))}
          />
          <MetaSelect
            kind="geoScopes"
            label="Рынок"
            value={filters.geo_scope ?? ''}
            onChange={(v) => setFilters((f) => ({ ...f, geo_scope: v || null }))}
          />
          <MetaSelect
            kind="workModes"
            label="Режим работы"
            value={filters.work_mode ?? ''}
            onChange={(v) => setFilters((f) => ({ ...f, work_mode: v || null }))}
          />
          <MetaSelect
            kind="domains"
            label="Домен"
            value={filters.domain ?? ''}
            onChange={(v) => setFilters((f) => ({ ...f, domain: v || null }))}
          />
        </div>
        <button
          type="submit"
          className="bg-blue-600 text-white rounded-lg px-6 py-2 text-sm font-medium hover:bg-blue-700"
        >
          Анализировать
        </button>
        {differsFromProfile && (
          <p className="text-xs text-amber-700">
            Фильтры отличаются от сохранённого профиля.
          </p>
        )}
      </form>

      {isLoading && (
        <div className="bg-white rounded-2xl border border-gray-200 p-6 animate-pulse">
          <div className="h-4 bg-gray-200 rounded w-1/3 mb-3" />
          <div className="h-4 bg-gray-200 rounded w-1/2" />
        </div>
      )}

      {isError && (
        <p className="text-red-600 text-sm bg-red-50 rounded-lg px-4 py-3">
          Ошибка загрузки данных рынка
        </p>
      )}

      {data && !isLoading && <MarketCard summary={data} />}
    </div>
  )
}
