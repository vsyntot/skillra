import { useEffect, useMemo, useState, type FormEvent } from 'react'
import DataFreshnessIndicator from '../components/DataFreshnessIndicator'
import MetaSelect from '../components/MetaSelect'
import SalaryTrendChart from '../components/SalaryTrendChart'
import SkillDemandTrendChart from '../components/SkillDemandTrendChart'
import VacancyCountTrendChart from '../components/VacancyCountTrendChart'
import { useMarket } from '../hooks/useMarket'
import { usePersistedFilters } from '../hooks/usePersistedFilters'
import { useCareerGraph, useCareerTrajectory } from '../hooks/useTrends'
import type { CareerTrajectoryOut, CareerTransitionOut } from '../api/client'
import { defaultsDifferFromProfile, profileToDefaultFilters } from '../hooks/profileDefaults'
import { useCurrentUserProfile } from '../hooks/useCurrentUserProfile'

interface TrendFilters {
  role: string
  grade: string
}

const DEFAULT_FILTERS: TrendFilters = {
  role: 'Data Analyst',
  grade: 'Middle',
}

function formatPercent(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return '—'
  return `${value > 1 ? value.toFixed(0) : (value * 100).toFixed(0)}%`
}

function formatSalary(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return '—'
  return `${Math.round(value / 1000).toLocaleString('ru-RU')}k ₽`
}

export default function TrendsPage() {
  const [filters, setFilters] = usePersistedFilters<TrendFilters>('skillra_trend_filters', DEFAULT_FILTERS)
  const [profileApplied, setProfileApplied] = useState(false)
  const { profile, isUserMode } = useCurrentUserProfile()
  const marketQuery = useMarket({ role: filters.role || null, grade: filters.grade || null })
  const trajectoryQuery = useCareerTrajectory(filters.role, filters.grade)
  const graphQuery = useCareerGraph(filters.role)
  const topSkills = useMemo(() => marketQuery.data?.top_skills?.slice(0, 3) ?? [], [marketQuery.data?.top_skills])
  const differsFromProfile = isUserMode && defaultsDifferFromProfile({ ...profileToDefaultFilters(profile), ...filters }, profile)
  const ignoredTrendDimensions = profile
    ? [
        profile.target_country || profile.target_region || profile.target_city || profile.target_geo_scope
          ? 'география'
          : '',
        profile.target_work_mode ? 'формат работы' : '',
        profile.target_domain ? 'домен' : '',
      ].filter(Boolean)
    : []

  useEffect(() => {
    if (!isUserMode || !profile || profileApplied) return
    const defaults = profileToDefaultFilters(profile)
    setFilters({
      role: defaults.role || DEFAULT_FILTERS.role,
      grade: defaults.grade || DEFAULT_FILTERS.grade,
    })
    setProfileApplied(true)
  }, [isUserMode, profile, profileApplied, setFilters])

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
  }

  return (
    <div className="space-y-8">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Тренды рынка</h1>
          <p className="mt-1 text-sm text-gray-500">Зарплаты, спрос и карьерный переход по выбранному сегменту.</p>
        </div>
        <DataFreshnessIndicator />
      </div>

      <form onSubmit={handleSubmit} className="bg-white rounded-xl border border-gray-100 shadow-sm p-6">
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <MetaSelect
            kind="roles"
            label="Роль"
            value={filters.role}
            onChange={(value) => setFilters((current) => ({ ...current, role: value }))}
            allowEmpty={false}
          />
          <MetaSelect
            kind="grades"
            label="Грейд"
            value={filters.grade}
            onChange={(value) => setFilters((current) => ({ ...current, grade: value }))}
            allowEmpty={false}
          />
        </div>
        {differsFromProfile && (
          <p className="mt-3 text-xs text-amber-700">
            Фильтры отличаются от сохранённого профиля.
          </p>
        )}
        {isUserMode && ignoredTrendDimensions.length > 0 && (
          <p className="mt-3 rounded-lg border border-amber-100 bg-amber-50 px-3 py-2 text-xs text-amber-800">
            Тренды на этой странице считаются по роли и грейду. Из профиля пока не применяются:{' '}
            {ignoredTrendDimensions.join(', ')}.
          </p>
        )}
      </form>

      <div className="grid grid-cols-1 gap-6 xl:grid-cols-2">
        <SalaryTrendChart role={filters.role} grade={filters.grade} />
        <VacancyCountTrendChart role={filters.role} grade={filters.grade} />
      </div>

      <section className="space-y-4">
        <div>
          <h2 className="text-lg font-semibold text-gray-900">Спрос на ключевые навыки</h2>
          <p className="text-sm text-gray-500">Топ-3 навыка берутся из текущего сегмента рынка.</p>
        </div>

        {marketQuery.isLoading ? (
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
            {[0, 1, 2].map((item) => (
              <div key={item} className="h-56 animate-pulse rounded-xl border border-gray-100 bg-white" />
            ))}
          </div>
        ) : marketQuery.isError ? (
          <div className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-5 text-sm text-amber-800">
            Список топ-навыков пока недоступен.
          </div>
        ) : topSkills.length === 0 ? (
          <div className="rounded-lg border border-gray-200 bg-gray-50 px-4 py-5 text-sm text-gray-600">
            Для выбранного сегмента пока нет топ-навыков.
          </div>
        ) : (
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
            {topSkills.map((skill) => (
              <SkillDemandTrendChart key={skill} skill={skill} role={filters.role} />
            ))}
          </div>
        )}
      </section>

      <CareerPathSection
        role={filters.role}
        grade={filters.grade}
        trajectory={trajectoryQuery.data}
        graphTransitions={graphQuery.data?.transitions ?? []}
        isLoading={trajectoryQuery.isLoading || graphQuery.isLoading}
        isError={trajectoryQuery.isError && graphQuery.isError}
      />
    </div>
  )
}

interface CareerPathSectionProps {
  role: string
  grade: string
  trajectory: CareerTrajectoryOut | undefined
  graphTransitions: CareerTransitionOut[]
  isLoading: boolean
  isError: boolean
}

function CareerPathSection({
  role,
  grade,
  trajectory,
  graphTransitions,
  isLoading,
  isError,
}: CareerPathSectionProps) {
  return (
    <section className="bg-white rounded-xl border border-gray-100 shadow-sm p-6">
      <div className="mb-5">
        <h2 className="text-lg font-semibold text-gray-900">Карьерный трек</h2>
        <p className="text-sm text-gray-500">{role || 'Роль не выбрана'} · {grade || 'грейд не выбран'}</p>
      </div>

      {!role || !grade ? (
        <EmptyCareerState text="Выберите роль и грейд, чтобы увидеть карьерный переход." />
      ) : isLoading ? (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
          {[0, 1, 2].map((item) => (
            <div key={item} className="h-28 animate-pulse rounded-lg bg-gray-100" />
          ))}
        </div>
      ) : isError ? (
        <EmptyCareerState text="Карьерный трек пока недоступен." tone="warning" />
      ) : graphTransitions.length > 0 ? (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
          {graphTransitions.map((transition) => (
            <div
              key={`${transition.from_grade}-${transition.to_grade}`}
              className="rounded-lg border border-gray-200 bg-gray-50 p-4"
            >
              <p className="text-sm font-semibold text-gray-900">
                {transition.from_grade} → {transition.to_grade}
              </p>
              <p className="mt-1 text-xs text-gray-500">∆ зарплаты: {formatPercent(transition.salary_delta_pct)}</p>
              <p className="mt-1 text-xs text-gray-500">Спрос: {translateDemandTrend(transition.demand_trend)}</p>
              <SkillList skills={transition.skills_to_add} />
            </div>
          ))}
        </div>
      ) : trajectory?.next_grade ? (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-[1fr_auto_1fr] md:items-stretch">
          <CareerGradeCard
            label="Текущий уровень"
            grade={trajectory.current_grade}
            salary={formatSalary(trajectory.salary_current_p50)}
          />
          <div className="flex items-center justify-center text-2xl font-semibold text-indigo-500">→</div>
          <CareerGradeCard
            label="Следующий уровень"
            grade={trajectory.next_grade}
            salary={formatSalary(trajectory.salary_next_p50)}
            delta={formatPercent(trajectory.salary_delta_pct)}
          />
          <div className="md:col-span-3">
            <SkillList skills={trajectory.skills_to_add.slice(0, 5)} />
          </div>
        </div>
      ) : (
        <EmptyCareerState text="Для выбранного сегмента карьерный переход пока не рассчитан." />
      )}
    </section>
  )
}

function CareerGradeCard({
  label,
  grade,
  salary,
  delta,
}: {
  label: string
  grade: string
  salary: string
  delta?: string
}) {
  return (
    <div className="rounded-lg border border-gray-200 bg-gray-50 p-4">
      <p className="text-xs text-gray-500">{label}</p>
      <p className="mt-1 text-xl font-semibold text-gray-900">{grade}</p>
      <p className="mt-2 text-sm text-gray-600">P50: {salary}</p>
      {delta && <p className="mt-1 text-sm font-medium text-emerald-700">∆ {delta}</p>}
    </div>
  )
}

function SkillList({ skills }: { skills: string[] }) {
  if (skills.length === 0) return null

  return (
    <div className="mt-3 flex flex-wrap gap-2">
      {skills.slice(0, 5).map((skill) => (
        <span key={skill} className="rounded-full border border-indigo-100 bg-indigo-50 px-2 py-0.5 text-xs text-indigo-700">
          {skill}
        </span>
      ))}
    </div>
  )
}

function EmptyCareerState({ text, tone = 'muted' }: { text: string; tone?: 'muted' | 'warning' }) {
  const className =
    tone === 'warning'
      ? 'rounded-lg border border-amber-200 bg-amber-50 px-4 py-5 text-sm text-amber-800'
      : 'rounded-lg border border-gray-200 bg-gray-50 px-4 py-5 text-sm text-gray-600'

  return <div className={className}>{text}</div>
}

function translateDemandTrend(value: string): string {
  switch (value) {
    case 'growing':
      return 'растёт'
    case 'declining':
      return 'снижается'
    case 'stable':
      return 'стабилен'
    default:
      return value || '—'
  }
}
