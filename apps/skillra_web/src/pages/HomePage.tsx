import { useEffect, useRef } from 'react'
import { Link } from 'react-router-dom'
import type {
  CareerActionOut,
  CareerPlanOut,
  EvidenceExplainerOut,
  NextBestActionOut,
  UserProfileOut,
  WeeklySubscriptionOut,
} from '../api/client'
import { trackProductEvent } from '../api/client'
import { useCareerPlan } from '../hooks/useCareerPlan'
import { useCurrentUserProfile } from '../hooks/useCurrentUserProfile'
import { useEvidenceExplainer } from '../hooks/useEvidenceExplainer'
import { useNextBestAction } from '../hooks/useNextBestAction'
import { useSubscription } from '../hooks/useSubscription'
import { resolveEvidenceExplainerEnabled } from '../lib/featureFlags'

export default function HomePage() {
  const { effectiveUserId, profile, isLoading: isProfileLoading, isUserMode } = useCurrentUserProfile()
  const { data: plan, isLoading: isPlanLoading } = useCareerPlan(effectiveUserId)
  const { data: subscription, isLoading: isSubscriptionLoading } = useSubscription(effectiveUserId)
  const { data: sharedNextAction, isLoading: isNextActionLoading } = useNextBestAction(isUserMode ? effectiveUserId : 0)
  const evidenceExplainerEnabled = resolveEvidenceExplainerEnabled(import.meta.env, effectiveUserId)
  const { data: evidenceExplainer } = useEvidenceExplainer(
    effectiveUserId,
    evidenceExplainerEnabled && isUserMode,
  )

  const completeness = sharedNextAction?.profile_quality.score ?? profileCompleteness(profile)
  const nextAction = nextCareerAction(plan)
  const savedVacancies = plan?.actions.filter((action) => action.action_type === 'saved_vacancy') ?? []
  const activeSavedVacancies = savedVacancies.filter((action) => action.application_status !== 'rejected')
  const subscriptionState = subscriptionLabel(subscription, isSubscriptionLoading)
  const firstSessionSteps = buildFirstSessionSteps({
    isUserMode,
    profile,
    completeness,
    plan,
    savedVacancies,
    subscription,
    sharedNextAction,
  })
  const nextStep = resolveNextStep({
    isUserMode,
    isProfileLoading,
    profile,
    plan,
    isPlanLoading,
    nextAction,
    savedVacancies,
    subscription,
    sharedNextAction,
    isNextActionLoading,
  })
  const trackedViews = useRef<Set<string>>(new Set())

  useEffect(() => {
    if (!isUserMode || effectiveUserId <= 0 || firstSessionSteps.length === 0) return
    const key = `${effectiveUserId}:${firstSessionSteps.map((step) => `${step.id}:${step.status}`).join('|')}`
    if (trackedViews.current.has(key)) return
    trackedViews.current.add(key)
    trackProductEvent(effectiveUserId, {
      event_name: 'first_session_viewed',
      surface: 'web',
      entity_type: 'first_session',
      metadata: {
        next_action_state: sharedNextAction?.state ?? null,
        step_count: firstSessionSteps.length,
      },
    })
    firstSessionSteps.forEach((step, index) => {
      trackProductEvent(effectiveUserId, {
        event_name: 'first_session_step_viewed',
        surface: 'web',
        entity_type: 'first_session_step',
        entity_id: step.id,
        metadata: stepTrackingMetadata(step, index + 1, sharedNextAction),
      })
    })
  }, [effectiveUserId, firstSessionSteps, isUserMode, sharedNextAction])

  return (
    <div className="space-y-6">
      <section className="flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Карьерный контур</h1>
          <p className="text-sm text-gray-500">
            {profile?.target_role ? `${profile.target_role}${profile.target_grade ? ` · ${profile.target_grade}` : ''}` : 'Профиль не заполнен'}
          </p>
        </div>
        <span className="w-fit rounded border border-gray-200 bg-white px-3 py-1.5 text-xs font-medium text-gray-600">
          {subscriptionState}
        </span>
      </section>

      <section className="rounded-lg border border-blue-100 bg-blue-50 p-4">
        <p className="text-xs font-semibold uppercase text-blue-700">Следующий шаг</p>
        <div className="mt-2 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <h2 className="text-lg font-semibold text-gray-900">{nextStep.title}</h2>
            <p className="text-sm text-gray-600">{nextStep.detail}</p>
            {evidenceExplainer && <EvidenceExplainerPanel explainer={evidenceExplainer} />}
            {nextStep.trustWarning && (
              <p className="mt-2 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-800">
                {nextStep.trustWarning}
              </p>
            )}
          </div>
          <Link
            to={nextStep.href}
            className="w-fit rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700"
          >
            {nextStep.cta}
          </Link>
        </div>
      </section>

      <section className="space-y-3" aria-labelledby="first-session-title">
        <div className="flex flex-col gap-1 sm:flex-row sm:items-end sm:justify-between">
          <div>
            <p className="text-xs font-semibold uppercase text-gray-500">Первый сеанс</p>
            <h2 id="first-session-title" className="text-lg font-semibold text-gray-900">
              От профиля к рынку, плану и вакансиям
            </h2>
          </div>
          <p className="text-sm text-gray-500">Единый маршрут web и Telegram</p>
        </div>
        <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
          {firstSessionSteps.map((step, index) => (
            <FirstSessionStepCard key={step.id} step={step} index={index + 1} telegramUserId={effectiveUserId} />
          ))}
        </div>
      </section>

      <section className="grid grid-cols-1 gap-4 md:grid-cols-4">
        <LoopMetric
          label="Профиль"
          value={isProfileLoading ? '...' : `${completeness}%`}
          detail={profile ? profileLocation(profile) : 'Нет целевого сегмента'}
          href="/profile"
        />
        <LoopMetric
          label="План"
          value={isPlanLoading ? '...' : planStatus(plan)}
          detail={plan ? `${plan.actions.length} действий` : 'План не создан'}
          href="/career-plan"
        />
        <LoopMetric
          label="Следующее действие"
          value={nextAction ? actionStatusLabel(nextAction.status) : 'Нет'}
          detail={nextAction?.title ?? 'Нужна генерация плана'}
          href="/career-plan"
        />
        <LoopMetric
          label="Вакансии"
          value={`Сохранено: ${savedVacancies.length}`}
          detail={activeSavedVacancies.length > 0 ? `В работе: ${activeSavedVacancies.length}` : 'Нет активных откликов'}
          href="/search"
        />
      </section>

      <section className="grid grid-cols-1 gap-4 md:grid-cols-3">
        <WorkflowLink title="Анализ рынка" detail="Сверить сегмент и доверие данных" href="/market" />
        <WorkflowLink title="Skill gap" detail="Обновить разрыв навыков" href="/skill-gap" />
        <WorkflowLink title="История дайджестов" detail="Проверить еженедельные возвраты" href="/digest-history" />
      </section>
    </div>
  )
}

type FirstSessionStepStatus = 'done' | 'current' | 'ready' | 'later'

interface FirstSessionStep {
  id: string
  title: string
  detail: string
  href: string
  status: FirstSessionStepStatus
}

interface LoopMetricProps {
  label: string
  value: string
  detail: string
  href: string
}

function FirstSessionStepCard({
  step,
  index,
  telegramUserId,
}: {
  step: FirstSessionStep
  index: number
  telegramUserId: number
}) {
  return (
    <Link
      to={step.href}
      data-testid={`first-session-step-${step.id}`}
      className={`min-h-32 rounded-lg border bg-white p-4 transition hover:border-blue-300 ${stepStatusClass(step.status)}`}
      onClick={() => {
        trackProductEvent(telegramUserId, {
          event_name: 'first_session_step_clicked',
          surface: 'web',
          entity_type: 'first_session_step',
          entity_id: step.id,
          metadata: stepTrackingMetadata(step, index),
        })
      }}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-center gap-3">
          <span className="flex h-7 w-7 items-center justify-center rounded-full border border-gray-200 bg-gray-50 text-sm font-semibold text-gray-700">
            {index}
          </span>
          <h3 className="text-sm font-semibold text-gray-900">{step.title}</h3>
        </div>
        <span className={`rounded border px-2 py-1 text-xs font-medium ${stepStatusBadgeClass(step.status)}`}>
          {stepStatusLabel(step.status)}
        </span>
      </div>
      <p className="mt-3 text-sm text-gray-600">{step.detail}</p>
    </Link>
  )
}

function EvidenceExplainerPanel({ explainer }: { explainer: EvidenceExplainerOut }) {
  if (explainer.status === 'disabled') return null
  return (
    <div data-testid="evidence-explainer" className="mt-3 rounded-md border border-blue-200 bg-white px-3 py-2">
      <p className="text-sm font-medium text-gray-900">{explainer.answer}</p>
      {explainer.bullets.length > 0 && (
        <ul className="mt-2 space-y-1 text-sm text-gray-700">
          {explainer.bullets.map((bullet) => (
            <li key={bullet}>{bullet}</li>
          ))}
        </ul>
      )}
      {explainer.evidence_refs.length > 0 && (
        <p className="mt-2 text-xs text-gray-500">
          Основание: {explainer.evidence_refs.map((ref) => ref.evidence_id).join(', ')}
        </p>
      )}
      {(explainer.uncertainties.length > 0 || explainer.blocked_claims.length > 0) && (
        <p className="mt-1 text-xs text-amber-700">
          Ограничения: {[...explainer.uncertainties, ...explainer.blocked_claims].join(', ')}
        </p>
      )}
    </div>
  )
}

function stepTrackingMetadata(
  step: FirstSessionStep,
  position: number,
  sharedNextAction?: NextBestActionOut | null,
): Record<string, unknown> {
  return {
    step_id: step.id,
    position,
    status: step.status,
    href: step.href,
    next_action_state: sharedNextAction?.state ?? null,
  }
}

function LoopMetric({ label, value, detail, href }: LoopMetricProps) {
  return (
    <Link to={href} className="rounded-lg border border-gray-200 bg-white p-4 hover:border-blue-300">
      <p className="text-xs font-medium text-gray-500">{label}</p>
      <p className="mt-2 text-xl font-semibold text-gray-900">{value}</p>
      <p className="mt-1 line-clamp-2 text-sm text-gray-600">{detail}</p>
    </Link>
  )
}

function WorkflowLink({ title, detail, href }: { title: string; detail: string; href: string }) {
  return (
    <Link to={href} className="rounded-lg border border-gray-200 bg-white p-4 hover:border-blue-300">
      <h2 className="text-sm font-semibold text-gray-900">{title}</h2>
      <p className="mt-1 text-sm text-gray-600">{detail}</p>
    </Link>
  )
}

function buildFirstSessionSteps({
  isUserMode,
  profile,
  completeness,
  plan,
  savedVacancies,
  subscription,
  sharedNextAction,
}: {
  isUserMode: boolean
  profile?: UserProfileOut | null
  completeness: number
  plan?: CareerPlanOut | null
  savedVacancies: CareerActionOut[]
  subscription?: WeeklySubscriptionOut | null
  sharedNextAction?: NextBestActionOut | null
}): FirstSessionStep[] {
  const state = sharedNextAction?.state
  const hasCompleteProfile = Boolean(profile) && completeness >= 100 && !['create_profile', 'complete_profile'].includes(state ?? '')
  const hasPlan = Boolean(plan)
  const hasGeneratedActions = Boolean(plan?.actions.some((action) => action.action_type !== 'saved_vacancy'))
  const hasSavedVacancy = savedVacancies.length > 0
  const hasDigest = Boolean(subscription?.active)

  const profileStatus = (() => {
    if (!isUserMode || !profile || state === 'create_profile' || state === 'complete_profile') return 'current'
    return hasCompleteProfile ? 'done' : 'current'
  })()
  const marketStatus = (() => {
    if (!isUserMode || !profile) return 'later'
    if (state === 'data_unavailable') return 'current'
    return hasCompleteProfile ? 'ready' : 'later'
  })()
  const planStatus = (() => {
    if (state === 'create_plan' || state === 'update_application_outcome' || state === 'continue_plan') return 'current'
    if (hasPlan) return 'done'
    return hasCompleteProfile ? 'ready' : 'later'
  })()
  const skillGapStatus = (() => {
    if (state === 'generate_plan_actions') return 'current'
    if (hasGeneratedActions) return 'done'
    return hasPlan ? 'ready' : 'later'
  })()
  const vacancyStatus = (() => {
    if (state === 'find_vacancy') return 'current'
    if (hasSavedVacancy) return 'done'
    return hasGeneratedActions ? 'ready' : 'later'
  })()
  const digestStatus = (() => {
    if (state === 'enable_digest') return 'current'
    if (hasDigest) return 'done'
    return hasSavedVacancy ? 'ready' : 'later'
  })()

  return [
    {
      id: 'profile',
      title: 'Профиль',
      detail: 'Цель, грейд, гео, формат работы и навыки.',
      href: isUserMode ? '/profile' : '/login',
      status: profileStatus,
    },
    {
      id: 'market',
      title: 'Рынок',
      detail: 'Сегмент, зарплаты, спрос и доверие данных.',
      href: '/market',
      status: marketStatus,
    },
    {
      id: 'plan',
      title: 'План',
      detail: 'Карьерные действия, приоритеты и статусы.',
      href: '/career-plan',
      status: planStatus,
    },
    {
      id: 'skill-gap',
      title: 'Skill gap',
      detail: 'Разрыв навыков и рекомендации в план.',
      href: '/skill-gap',
      status: skillGapStatus,
    },
    {
      id: 'vacancies',
      title: 'Вакансии',
      detail: 'Поиск, сохранение и статусы откликов.',
      href: '/search',
      status: vacancyStatus,
    },
    {
      id: 'digest',
      title: 'Дайджест',
      detail: 'Еженедельный возврат к рынку и плану.',
      href: '/subscription',
      status: digestStatus,
    },
  ]
}

function stepStatusLabel(status: FirstSessionStepStatus): string {
  switch (status) {
    case 'done':
      return 'Готово'
    case 'current':
      return 'Сейчас'
    case 'ready':
      return 'Доступно'
    case 'later':
      return 'Позже'
  }
}

function stepStatusClass(status: FirstSessionStepStatus): string {
  switch (status) {
    case 'done':
      return 'border-emerald-200'
    case 'current':
      return 'border-blue-300 shadow-sm'
    case 'ready':
      return 'border-gray-200'
    case 'later':
      return 'border-gray-200 opacity-75'
  }
}

function stepStatusBadgeClass(status: FirstSessionStepStatus): string {
  switch (status) {
    case 'done':
      return 'border-emerald-200 bg-emerald-50 text-emerald-700'
    case 'current':
      return 'border-blue-200 bg-blue-50 text-blue-700'
    case 'ready':
      return 'border-gray-200 bg-gray-50 text-gray-700'
    case 'later':
      return 'border-gray-200 bg-gray-50 text-gray-500'
  }
}

function profileCompleteness(profile?: UserProfileOut | null): number {
  if (!profile) return 0
  const checks = [
    profile.target_role,
    profile.target_grade,
    profile.target_city_tier || profile.target_city || profile.target_country,
    profile.target_work_mode,
    profile.target_domain,
    profile.current_skills.length > 0 ? 'skills' : '',
  ]
  const completed = checks.filter(Boolean).length
  return Math.round((completed / checks.length) * 100)
}

function profileLocation(profile: UserProfileOut): string {
  const parts = [profile.target_country, profile.target_region, profile.target_city, profile.target_geo_scope].filter(Boolean)
  return parts.length > 0 ? parts.join(' · ') : 'Гео не задано'
}

function planStatus(plan?: CareerPlanOut | null): string {
  if (!plan) return 'Нет'
  switch (plan.status) {
    case 'active':
      return 'Активен'
    case 'completed':
      return 'Завершен'
    case 'archived':
      return 'Архив'
    default:
      return plan.status
  }
}

function nextCareerAction(plan?: CareerPlanOut | null): CareerActionOut | null {
  const actions = plan?.actions.filter((action) => action.status !== 'done' && action.status !== 'skipped') ?? []
  return [...actions].sort((left, right) => left.priority - right.priority || left.id - right.id)[0] ?? null
}

function actionStatusLabel(status: string): string {
  switch (status) {
    case 'planned':
      return 'Запланировано'
    case 'in_progress':
      return 'В работе'
    case 'done':
      return 'Готово'
    case 'skipped':
      return 'Пропущено'
    default:
      return status
  }
}

function subscriptionLabel(subscription?: WeeklySubscriptionOut | null, isLoading = false): string {
  if (isLoading) return 'Дайджест: ...'
  return subscription?.active ? 'Дайджест активен' : 'Дайджест выключен'
}

function resolveNextStep({
  isUserMode,
  isProfileLoading,
  profile,
  plan,
  isPlanLoading,
  nextAction,
  savedVacancies,
  subscription,
  sharedNextAction,
  isNextActionLoading,
}: {
  isUserMode: boolean
  isProfileLoading: boolean
  profile?: UserProfileOut | null
  plan?: CareerPlanOut | null
  isPlanLoading: boolean
  nextAction: CareerActionOut | null
  savedVacancies: CareerActionOut[]
  subscription?: WeeklySubscriptionOut | null
  sharedNextAction?: NextBestActionOut | null
  isNextActionLoading: boolean
}): { title: string; detail: string; href: string; cta: string; trustWarning?: string | null } {
  if (!isUserMode) {
    return {
      title: 'Нужен пользовательский доступ',
      detail: 'Career loop собирается вокруг вашего профиля и личного плана.',
      href: '/login',
      cta: 'Войти',
    }
  }
  if (isNextActionLoading) {
    return {
      title: 'Подбираем следующий шаг',
      detail: 'Сверяем профиль, план и сохраненные вакансии.',
      href: '/profile',
      cta: 'Открыть профиль',
    }
  }
  if (sharedNextAction) {
    return {
      title: sharedNextAction.title,
      detail: sharedNextAction.reason,
      href: sharedNextAction.route ?? '/career-plan',
      cta: sharedNextAction.cta,
      trustWarning: sharedNextAction.trust_warning,
    }
  }
  if (isProfileLoading) {
    return {
      title: 'Загружаем профиль',
      detail: 'Проверяем текущий карьерный сегмент.',
      href: '/profile',
      cta: 'Профиль',
    }
  }
  if (!profile) {
    return {
      title: 'Создать профиль',
      detail: 'Целевая роль, грейд, гео и навыки нужны для персонального анализа.',
      href: '/profile',
      cta: 'К профилю',
    }
  }
  if (isPlanLoading) {
    return {
      title: 'Загружаем план',
      detail: 'Сверяем сохраненные действия и вакансии.',
      href: '/career-plan',
      cta: 'План',
    }
  }
  if (!plan) {
    return {
      title: 'Собрать план',
      detail: 'План связывает skill gap, вакансии и статусы откликов.',
      href: '/career-plan',
      cta: 'К плану',
    }
  }
  if (!nextAction) {
    return {
      title: 'Сгенерировать действия',
      detail: 'Обновите skill gap и добавьте следующий шаг в план.',
      href: '/skill-gap',
      cta: 'Skill gap',
    }
  }
  if (savedVacancies.length === 0) {
    return {
      title: 'Подобрать вакансии',
      detail: 'Сохраненные вакансии превращают план в измеримый outcome loop.',
      href: '/search',
      cta: 'Поиск',
    }
  }
  if (!subscription?.active) {
    return {
      title: 'Включить еженедельный обзор',
      detail: 'Дайджест возвращает к плану и обновлениям рынка.',
      href: '/subscription',
      cta: 'Подписка',
    }
  }
  return {
    title: nextAction.title,
    detail: 'Следующее действие в активном карьерном плане.',
    href: '/career-plan',
    cta: 'Открыть план',
  }
}
