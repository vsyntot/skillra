/**
 * SkillGapPage — skill gap analysis page.
 * Uses useSkillGap hook + SkillGapChart component.
 * Sprint-009 TASK-12: PDF export button.
 * Sprint-009 TASK-13: Share link button.
 */
import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import DataFreshnessIndicator from '../components/DataFreshnessIndicator'
import LockedFeatureCallout from '../components/LockedFeatureCallout'
import MetaSelect from '../components/MetaSelect'
import SalaryTrendChart from '../components/SalaryTrendChart'
import SkillGapChart from '../components/SkillGapChart'
import { useSkillGap } from '../hooks/useSkillGap'
import { usePersistedFilters } from '../hooks/usePersistedFilters'
import type { PersonaProfile } from '../api/client'
import { createShareLink, exportSkillGapCsv, exportSkillGapPdf, trackProductEvent } from '../api/client'
import { defaultsDifferFromProfile, profileToDefaultFilters } from '../hooks/profileDefaults'
import { useCurrentUserProfile } from '../hooks/useCurrentUserProfile'
import { useGenerateCareerPlanActions } from '../hooks/useCareerPlan'
import { hasEntitlement } from '../components/commercial'
import { useCommercialState } from '../hooks/useCommercialState'

const GENERATE_ACTIONS_ENTITLEMENT = 'career_plan.generate_actions'

const DEFAULT_PROFILE: PersonaProfile = {
  name: 'Demo User',
  description: 'Ищу работу в IT',
  current_skills: ['Python', 'SQL'],
  target_role: 'Data Analyst',
  target_grade: 'Middle',
}

interface SkillGapFilters {
  skills: string
  role: string
  grade: string
  cityTier: string
  country: string
  region: string
  city: string
  geoScope: string
  workMode: string
  domain: string
}

const DEFAULT_FILTERS: SkillGapFilters = {
  skills: (DEFAULT_PROFILE.current_skills ?? []).join(', '),
  role: DEFAULT_PROFILE.target_role,
  grade: DEFAULT_PROFILE.target_grade ?? '',
  cityTier: DEFAULT_PROFILE.target_city_tier ?? '',
  country: DEFAULT_PROFILE.target_country ?? '',
  region: DEFAULT_PROFILE.target_region ?? '',
  city: DEFAULT_PROFILE.target_city ?? '',
  geoScope: DEFAULT_PROFILE.target_geo_scope ?? '',
  workMode: DEFAULT_PROFILE.target_work_mode ?? '',
  domain: '',
}

function buildProfile(filters: SkillGapFilters): PersonaProfile {
  return {
    ...DEFAULT_PROFILE,
    current_skills: filters.skills
      .split(',')
      .map((s) => s.trim())
      .filter(Boolean),
    target_role: filters.role,
    target_grade: filters.grade || undefined,
    target_city_tier: filters.cityTier || undefined,
    target_country: filters.country || undefined,
    target_region: filters.region || undefined,
    target_city: filters.city || undefined,
    target_geo_scope: filters.geoScope || undefined,
    target_work_mode: filters.workMode || undefined,
    constraints: filters.domain ? { domain: filters.domain } : {},
  }
}

export default function SkillGapPage() {
  const [filters, setFilters] = usePersistedFilters<SkillGapFilters>('skillra_skill_gap_filters', DEFAULT_FILTERS)
  const [submitted, setSubmitted] = useState(false)
  const [profile, setProfile] = useState(() => buildProfile(filters))
  const [shareMsg, setShareMsg] = useState<string | null>(null)
  const [shareUrl, setShareUrl] = useState<string | null>(null)
  const [sharing, setSharing] = useState(false)
  const [exporting, setExporting] = useState(false)
  const [profileApplied, setProfileApplied] = useState(false)
  const [planMsg, setPlanMsg] = useState<string | null>(null)
  const { effectiveUserId, profile: currentProfile, isUserMode } = useCurrentUserProfile()
  const generateActions = useGenerateCareerPlanActions(effectiveUserId)
  const commercialState = useCommercialState(isUserMode ? effectiveUserId : 0)
  const trackedViews = useRef<Set<string>>(new Set())

  const { data, isLoading, isError } = useSkillGap(profile, { enabled: submitted })
  const differsFromProfile = isUserMode && defaultsDifferFromProfile(filters, currentProfile)
  const generateActionsLocked = commercialState.data
    ? !hasEntitlement(commercialState.data, GENERATE_ACTIONS_ENTITLEMENT)
    : false

  useEffect(() => {
    if (!isUserMode || !currentProfile || profileApplied) return
    const defaults = profileToDefaultFilters(currentProfile)
    setFilters(defaults)
    setProfile(buildProfile(defaults))
    setSubmitted(true)
    setProfileApplied(true)
  }, [currentProfile, isUserMode, profileApplied, setFilters])

  useEffect(() => {
    if (!isUserMode || effectiveUserId <= 0 || !data) return
    const key = `${effectiveUserId}:${JSON.stringify(profile)}:${data.market_summary?.dataset_run_id ?? ''}`
    if (trackedViews.current.has(key)) return
    trackedViews.current.add(key)
    trackProductEvent(effectiveUserId, {
      event_name: 'skill_gap_viewed',
      surface: 'web',
      entity_type: 'skill_gap',
      metadata: {
        target_role: profile.target_role,
        target_grade: profile.target_grade,
        dataset_run_id: data.market_summary?.dataset_run_id,
        confidence: data.market_summary?.confidence,
        freshness: data.market_summary?.freshness,
        trust_tier:
          data.market_summary?.freshness === 'stale'
            ? 'stale_data'
            : data.market_summary?.confidence === 'high'
              ? 'trusted'
              : 'limited_sample',
        gap_count: data.skill_gap.filter((entry) => entry.gap).length,
        recommended_count: data.recommended_skills.length,
      },
    })
  }, [data, effectiveUserId, isUserMode, profile])

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setProfile(buildProfile(filters))
    setSubmitted(true)
  }

  async function handleCsvExport() {
    try {
      const blob = await exportSkillGapCsv(profile)
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = 'skill_gap.csv'
      a.click()
      URL.revokeObjectURL(url)
    } catch {
      alert('Ошибка экспорта CSV')
    }
  }

  // Sprint-009 TASK-12
  async function handlePdfExport() {
    setExporting(true)
    try {
      const blob = await exportSkillGapPdf(profile)
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `skill_gap_${profile.target_role?.replace(/\s+/g, '_') ?? 'report'}.pdf`
      a.click()
      URL.revokeObjectURL(url)
    } catch {
      alert('Ошибка экспорта PDF. Убедитесь, что установлена библиотека reportlab.')
    } finally {
      setExporting(false)
    }
  }

  // Sprint-009 TASK-13
  async function handleShare() {
    setSharing(true)
    setShareMsg(null)
    try {
      const { token } = await createShareLink(profile)
      const url = `${window.location.origin}/share/${token}`
      setShareUrl(url)
      try {
        await navigator.clipboard.writeText(url)
        setShareMsg('Ссылка скопирована в буфер обмена.')
      } catch {
        setShareMsg('Ссылка создана. Скопируйте её вручную.')
      }
    } catch {
      setShareMsg('Не удалось создать ссылку. Проверьте подключение к Redis.')
    } finally {
      setSharing(false)
    }
  }

  async function handleCopyShareUrl() {
    if (!shareUrl) return
    try {
      await navigator.clipboard.writeText(shareUrl)
      setShareMsg('Ссылка скопирована в буфер обмена.')
    } catch {
      setShareMsg('Не удалось скопировать ссылку автоматически.')
    }
  }

  function handleGeneratePlanActions() {
    if (effectiveUserId <= 0) return
    if (generateActionsLocked) return
    setPlanMsg(null)
    generateActions.mutate(
      { limit: 5, replace_generated: false },
      {
        onSuccess: (plan) => {
          setPlanMsg(`Рекомендации добавлены в план: ${plan.actions.length}`)
          trackProductEvent(effectiveUserId, {
            event_name: 'skill_gap_action_generated',
            surface: 'web',
            entity_type: 'career_plan',
            metadata: {
              action_count: plan.actions.length,
              target_role: profile.target_role,
            },
          })
        },
        onError: () => {
          setPlanMsg('Не удалось добавить рекомендации. Проверьте, что профиль, тариф и карьерный план настроены.')
        },
      },
    )
  }

  return (
    <div className="space-y-8">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <h1 className="text-2xl font-bold text-gray-900">Анализ Skill Gap</h1>
        <DataFreshnessIndicator />
      </div>

      <form onSubmit={handleSubmit} className="bg-white rounded-xl shadow-sm border border-gray-100 p-6 space-y-4">
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">
            Текущие навыки <span className="text-gray-400">(через запятую)</span>
          </label>
          <input
            className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-400"
            value={filters.skills}
            onChange={(e) => setFilters((f) => ({ ...f, skills: e.target.value }))}
            placeholder="Python, SQL, pandas..."
          />
        </div>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <MetaSelect
            kind="roles"
            label="Целевая роль"
            value={filters.role}
            onChange={(value) => setFilters((f) => ({ ...f, role: value }))}
          />
          <MetaSelect
            kind="grades"
            label="Грейд"
            value={filters.grade}
            onChange={(value) => setFilters((f) => ({ ...f, grade: value }))}
          />
          <MetaSelect
            kind="cityTiers"
            label="Уровень города"
            value={filters.cityTier}
            onChange={(value) => setFilters((f) => ({ ...f, cityTier: value }))}
          />
          <MetaSelect
            kind="countries"
            label="Страна"
            value={filters.country ?? ''}
            onChange={(value) => setFilters((f) => ({ ...f, country: value }))}
          />
          <MetaSelect
            kind="regions"
            label="Регион"
            value={filters.region ?? ''}
            onChange={(value) => setFilters((f) => ({ ...f, region: value }))}
          />
          <MetaSelect
            kind="cities"
            label="Город"
            value={filters.city ?? ''}
            onChange={(value) => setFilters((f) => ({ ...f, city: value }))}
          />
          <MetaSelect
            kind="geoScopes"
            label="Рынок"
            value={filters.geoScope ?? ''}
            onChange={(value) => setFilters((f) => ({ ...f, geoScope: value }))}
          />
          <MetaSelect
            kind="workModes"
            label="Режим работы"
            value={filters.workMode}
            onChange={(value) => setFilters((f) => ({ ...f, workMode: value }))}
          />
          <MetaSelect
            kind="domains"
            label="Домен"
            value={filters.domain}
            onChange={(value) => setFilters((f) => ({ ...f, domain: value }))}
          />
        </div>
        {(filters.workMode || filters.domain) && (
          <p className="text-xs text-gray-500">
            Skill gap учитывает формат работы и домен, когда эти признаки есть в данных; при малой выборке появится
            предупреждение о надёжности.
          </p>
        )}
        <button
          type="submit"
          className="bg-indigo-600 text-white px-6 py-2 rounded-lg text-sm font-medium hover:bg-indigo-700 transition-colors"
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
        <div className="text-center text-gray-500 py-8">Загружаем данные...</div>
      )}

      {isError && (
        <div className="bg-red-50 border border-red-200 rounded-lg p-4 text-red-700 text-sm">
          Ошибка загрузки данных. Убедитесь, что API запущен.
        </div>
      )}

      {data && (
        <div className="space-y-6">
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            <StatCard label="Вакансий" value={data.market_summary.vacancy_count} />
            <StatCard
              label="Медиана зп"
              value={data.market_summary.salary_median != null ? `${(data.market_summary.salary_median / 1000).toFixed(0)}k ₽` : '—'}
            />
            <StatCard label="Рекомендовано скиллов" value={data.recommended_skills.length} />
            <StatCard label="Гэпов" value={data.skill_gap.filter((s) => s.gap).length} />
          </div>

          {data.market_summary.min_market_n != null &&
            data.market_summary.vacancy_count < data.market_summary.min_market_n && (
              <div className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
                Сегмент меньше минимального порога: {data.market_summary.vacancy_count.toLocaleString('ru-RU')} из{' '}
                {data.market_summary.min_market_n.toLocaleString('ru-RU')} вакансий. Расширьте фильтры для более
                стабильной оценки.
              </div>
            )}

          <div className="bg-white rounded-xl shadow-sm border border-gray-100 p-6">
            <h2 className="text-lg font-semibold text-gray-900 mb-4">Skill Gap Chart</h2>
            <SkillGapChart data={data.skill_gap} />
          </div>

          <div className="space-y-3">
            <SalaryTrendChart
              role={profile.target_role}
              grade={profile.target_grade ?? ''}
              compact
            />
            <Link
              to="/trends"
              className="inline-flex text-sm font-medium text-indigo-600 hover:text-indigo-700"
            >
              Полная аналитика трендов →
            </Link>
          </div>

          {/* Export / Share actions — Sprint-009 TASK-12, TASK-13 */}
          <div className="flex flex-wrap gap-3">
            {isUserMode && (
              <button
                onClick={handleGeneratePlanActions}
                disabled={generateActions.isPending || generateActionsLocked}
                className="bg-indigo-600 text-white px-4 py-2 rounded-lg text-sm font-medium hover:bg-indigo-700 transition-colors disabled:opacity-50"
              >
                {generateActions.isPending ? 'Добавляем...' : 'Добавить рекомендации в план'}
              </button>
            )}
            {isUserMode && generateActionsLocked && <LockedFeatureCallout feature={GENERATE_ACTIONS_ENTITLEMENT} />}
            <button
              onClick={handleCsvExport}
              className="bg-white border border-gray-300 text-gray-700 px-4 py-2 rounded-lg text-sm font-medium hover:bg-gray-50 transition-colors"
            >
              📥 Скачать CSV
            </button>
            <button
              onClick={handlePdfExport}
              disabled={exporting}
              className="bg-white border border-gray-300 text-gray-700 px-4 py-2 rounded-lg text-sm font-medium hover:bg-gray-50 transition-colors disabled:opacity-50"
            >
              {exporting ? '⏳ Генерация...' : '📄 Скачать PDF'}
            </button>
            <button
              onClick={handleShare}
              disabled={sharing}
              className="bg-white border border-indigo-300 text-indigo-700 px-4 py-2 rounded-lg text-sm font-medium hover:bg-indigo-50 transition-colors"
            >
              {sharing ? 'Создаём ссылку...' : 'Поделиться'}
            </button>
          </div>

          {planMsg && (
            <p className="rounded-lg border border-indigo-100 bg-indigo-50 px-3 py-2 text-sm text-indigo-700">
              {planMsg}
            </p>
          )}

          {(shareMsg || shareUrl) && (
            <div className="bg-green-50 border border-green-200 rounded-lg p-3 text-green-700 text-sm space-y-3">
              {shareMsg && <p>{shareMsg}</p>}
              {shareUrl && (
                <div className="flex flex-col gap-2 md:flex-row md:items-center">
                  <input
                    readOnly
                    value={shareUrl}
                    className="flex-1 border border-green-200 rounded-lg bg-white px-3 py-2 text-sm text-gray-700"
                  />
                  <button
                    onClick={handleCopyShareUrl}
                    className="bg-green-600 text-white px-4 py-2 rounded-lg text-sm font-medium hover:bg-green-700 transition-colors"
                  >
                    Скопировать
                  </button>
                </div>
              )}
            </div>
          )}

          {data.warnings.length > 0 && (
            <div className="bg-amber-50 border border-amber-200 rounded-lg p-4 text-amber-700 text-sm space-y-1">
              {data.warnings.map((w, i) => (
                <p key={i}>⚠️ {w}</p>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

function StatCard({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="bg-white rounded-xl shadow-sm border border-gray-100 p-4">
      <p className="text-xs text-gray-500 mb-1">{label}</p>
      <p className="text-xl font-bold text-gray-900">{value}</p>
    </div>
  )
}
