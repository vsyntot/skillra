import { useEffect, useMemo, useRef, useState } from 'react'
import { CheckCircle2, Circle, Clock3, ListChecks, Plus, Save, XCircle } from 'lucide-react'
import MetaSelect from '../components/MetaSelect'
import { useAuth } from '../auth/AuthContext'
import { apiErrorCode, apiErrorMessage, trackProductEvent } from '../api/client'
import type {
  CareerActionOut,
  CareerActionStatus,
  CareerActionType,
  CareerPlanStatus,
} from '../api/client'
import {
  useCareerPlan,
  useCreateCareerAction,
  useGenerateCareerPlanActions,
  usePatchCareerAction,
  usePatchCareerPlan,
  useUpsertCareerPlan,
} from '../hooks/useCareerPlan'
import LockedFeatureCallout from '../components/LockedFeatureCallout'
import { hasEntitlement } from '../components/commercial'
import { useCommercialState } from '../hooks/useCommercialState'

const PLAN_STATUSES: Array<{ value: CareerPlanStatus; label: string }> = [
  { value: 'active', label: 'Активен' },
  { value: 'completed', label: 'Завершён' },
  { value: 'archived', label: 'Архив' },
]

const GENERATE_ACTIONS_ENTITLEMENT = 'career_plan.generate_actions'

const ACTION_TYPES: Array<{ value: CareerActionType; label: string }> = [
  { value: 'learning', label: 'Обучение' },
  { value: 'application', label: 'Отклик' },
  { value: 'portfolio', label: 'Портфолио' },
  { value: 'networking', label: 'Нетворкинг' },
  { value: 'saved_vacancy', label: 'Вакансия' },
  { value: 'other', label: 'Другое' },
]

const ACTION_STATUSES: Array<{
  value: CareerActionStatus
  label: string
  icon: typeof Circle
}> = [
  { value: 'planned', label: 'План', icon: Circle },
  { value: 'in_progress', label: 'В работе', icon: Clock3 },
  { value: 'done', label: 'Готово', icon: CheckCircle2 },
  { value: 'skipped', label: 'Пропуск', icon: XCircle },
]

const ACTION_TYPE_LABELS = Object.fromEntries(ACTION_TYPES.map((item) => [item.value, item.label]))
const ACTION_STATUS_LABELS = Object.fromEntries(ACTION_STATUSES.map((item) => [item.value, item.label]))

interface CareerPlanForm {
  target_role: string
  target_grade: string
  target_city_tier: string
  target_country: string
  target_region: string
  target_city: string
  target_geo_scope: string
  target_work_mode: string
  target_domain: string
  status: CareerPlanStatus
  notes: string
}

interface CareerActionForm {
  title: string
  description: string
  action_type: CareerActionType
  status: CareerActionStatus
  priority: string
  skill_name: string
}

const emptyPlanForm: CareerPlanForm = {
  target_role: '',
  target_grade: '',
  target_city_tier: '',
  target_country: '',
  target_region: '',
  target_city: '',
  target_geo_scope: '',
  target_work_mode: '',
  target_domain: '',
  status: 'active',
  notes: '',
}

const emptyActionForm: CareerActionForm = {
  title: '',
  description: '',
  action_type: 'learning',
  status: 'planned',
  priority: '100',
  skill_name: '',
}

function nullable(value: string): string | null {
  const trimmed = value.trim()
  return trimmed.length > 0 ? trimmed : null
}

function normalizePlanStatus(value: string | null | undefined): CareerPlanStatus {
  return PLAN_STATUSES.some((item) => item.value === value) ? (value as CareerPlanStatus) : 'active'
}

function actionTypeLabel(value: string): string {
  return ACTION_TYPE_LABELS[value] ?? value
}

function actionStatusLabel(value: string): string {
  return ACTION_STATUS_LABELS[value] ?? value
}

function formatDate(value: string | null): string {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString('ru-RU')
}

export default function CareerPlanPage() {
  const { mode, telegramUserId } = useAuth()
  const [serviceUserId, setServiceUserId] = useState<number>(0)
  const [inputId, setInputId] = useState('')
  const [planSaved, setPlanSaved] = useState(false)
  const [actionSaved, setActionSaved] = useState(false)
  const [generationMsg, setGenerationMsg] = useState<string | null>(null)
  const effectiveUserId = mode === 'user' ? telegramUserId ?? 0 : serviceUserId

  const { data: plan, isLoading, isError } = useCareerPlan(effectiveUserId)
  const upsertPlan = useUpsertCareerPlan(effectiveUserId)
  const patchPlan = usePatchCareerPlan(effectiveUserId)
  const createAction = useCreateCareerAction(effectiveUserId)
  const patchAction = usePatchCareerAction(effectiveUserId)
  const generateActions = useGenerateCareerPlanActions(effectiveUserId)
  const commercialState = useCommercialState(effectiveUserId)
  const trackedPlanViews = useRef<Set<string>>(new Set())

  const [planForm, setPlanForm] = useState<CareerPlanForm>(emptyPlanForm)
  const [actionForm, setActionForm] = useState<CareerActionForm>(emptyActionForm)

  useEffect(() => {
    if (!plan) return
    setPlanForm({
      target_role: plan.target_role ?? '',
      target_grade: plan.target_grade ?? '',
      target_city_tier: plan.target_city_tier ?? '',
      target_country: plan.target_country ?? '',
      target_region: plan.target_region ?? '',
      target_city: plan.target_city ?? '',
      target_geo_scope: plan.target_geo_scope ?? '',
      target_work_mode: plan.target_work_mode ?? '',
      target_domain: plan.target_domain ?? '',
      status: normalizePlanStatus(plan.status),
      notes: plan.notes ?? '',
    })
  }, [plan])

  useEffect(() => {
    if (mode !== 'user' || effectiveUserId <= 0 || !plan) return
    const key = `${effectiveUserId}:${plan.updated_at}:${plan.actions.length}`
    if (trackedPlanViews.current.has(key)) return
    trackedPlanViews.current.add(key)
    trackProductEvent(effectiveUserId, {
      event_name: 'plan_viewed',
      surface: 'web',
      entity_type: 'career_plan',
      metadata: {
        status: plan.status,
        action_count: plan.actions.length,
      },
    })
  }, [effectiveUserId, mode, plan])

  const progress = useMemo(() => {
    const actions = plan?.actions ?? []
    const total = actions.length
    const done = actions.filter((action) => action.status === 'done').length
    const active = actions.filter((action) => !['done', 'skipped'].includes(action.status)).length
    const applications = actions.filter((action) => action.application_status).length
    const applied = actions.filter((action) => ['applied', 'interview', 'offer'].includes(String(action.application_status))).length
    const percent = total > 0 ? Math.round((done / total) * 100) : 0
    return { total, done, active, applications, applied, percent }
  }, [plan])
  const generateActionsLocked = commercialState.data
    ? !hasEntitlement(commercialState.data, GENERATE_ACTIONS_ENTITLEMENT)
    : false

  const handleLoad = () => {
    const id = parseInt(inputId, 10)
    if (!Number.isNaN(id) && id > 0) {
      setServiceUserId(id)
      setPlanSaved(false)
      setActionSaved(false)
      setPlanForm(emptyPlanForm)
      setActionForm(emptyActionForm)
    }
  }

  const planPayload = () => ({
    target_role: nullable(planForm.target_role),
    target_grade: nullable(planForm.target_grade),
    target_city_tier: nullable(planForm.target_city_tier),
    target_country: nullable(planForm.target_country),
    target_region: nullable(planForm.target_region),
    target_city: nullable(planForm.target_city),
    target_geo_scope: nullable(planForm.target_geo_scope),
    target_work_mode: nullable(planForm.target_work_mode),
    target_domain: nullable(planForm.target_domain),
    status: planForm.status,
    notes: nullable(planForm.notes),
  })

  const handleCreatePlan = () => {
    if (effectiveUserId <= 0) return
    upsertPlan.mutate(planPayload(), {
      onSuccess: () => {
        setPlanSaved(true)
        trackProductEvent(effectiveUserId, {
          event_name: 'plan_created',
          surface: 'web',
          entity_type: 'career_plan',
          metadata: { status: planForm.status },
        })
      },
    })
  }

  const handleSavePlan = () => {
    if (effectiveUserId <= 0 || !plan) return
    patchPlan.mutate(planPayload(), {
      onSuccess: () => {
        setPlanSaved(true)
        trackProductEvent(effectiveUserId, {
          event_name: 'plan_updated',
          surface: 'web',
          entity_type: 'career_plan',
          metadata: { status: planForm.status },
        })
      },
    })
  }

  const handleCreateAction = () => {
    if (effectiveUserId <= 0 || !plan || !actionForm.title.trim()) return

    createAction.mutate(
      {
        title: actionForm.title.trim(),
        description: nullable(actionForm.description),
        action_type: actionForm.action_type,
        status: actionForm.status,
        priority: Math.max(0, Math.min(1000, parseInt(actionForm.priority, 10) || 100)),
        skill_name: nullable(actionForm.skill_name),
      },
      {
        onSuccess: () => {
          setActionSaved(true)
          setActionForm(emptyActionForm)
        },
      },
    )
  }

  const updateActionStatus = (action: CareerActionOut, status: CareerActionStatus) => {
    if (action.status === status) return
    patchAction.mutate({ actionId: action.id, payload: { status } })
  }

  const handleGenerateActions = () => {
    if (effectiveUserId <= 0 || !plan) return
    if (generateActionsLocked) return
    setGenerationMsg(null)
    generateActions.mutate(
      { limit: 5, replace_generated: false },
      {
        onSuccess: (updatedPlan) => {
          setGenerationMsg(`План обновлён: ${updatedPlan.actions.length} действий`)
        },
        onError: (error) => {
          if (apiErrorCode(error) === 'ENTITLEMENT_REQUIRED') {
            setGenerationMsg(apiErrorMessage(error) ?? 'Рекомендации из skill gap доступны в Trial или Pro.')
            return
          }
          setGenerationMsg('Не удалось сгенерировать действия из skill gap.')
        },
      },
    )
  }

  const isPlanSaving = upsertPlan.isPending || patchPlan.isPending

  return (
    <div className="max-w-4xl mx-auto p-6 space-y-6">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Карьерный план</h1>
          <p className="text-sm text-gray-500 mt-1">
            Цель, действия и сохранённые вакансии пользователя в одном рабочем контуре.
          </p>
        </div>
        {plan && (
          <div className="text-sm text-gray-600">
            Обновлён: <span className="font-medium text-gray-900">{formatDate(plan.updated_at)}</span>
          </div>
        )}
      </div>

      {mode !== 'user' && (
        <section className="rounded-lg border border-gray-200 bg-white p-4">
          <div className="flex gap-3">
            <input
              type="number"
              value={inputId}
              onChange={(event) => setInputId(event.target.value)}
              placeholder="Telegram User ID"
              className="min-w-0 flex-1 rounded-lg border border-gray-300 px-3 py-2 text-sm"
            />
            <button
              onClick={handleLoad}
              className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700"
            >
              Загрузить
            </button>
          </div>
        </section>
      )}

      {effectiveUserId <= 0 && (
        <p className="rounded-lg border border-gray-200 bg-white px-4 py-3 text-sm text-gray-500">
          {mode === 'user' ? 'Не удалось определить Telegram User ID по сессии.' : 'Укажите Telegram User ID.'}
        </p>
      )}

      {effectiveUserId > 0 && isLoading && <p className="text-sm text-gray-500">Загрузка...</p>}

      {effectiveUserId > 0 && isError && (
        <p className="rounded-lg bg-red-50 px-4 py-3 text-sm text-red-700">
          Не удалось загрузить карьерный план.
        </p>
      )}

      {effectiveUserId > 0 && !isLoading && !isError && (
        <>
          <section className="rounded-lg border border-gray-200 bg-white p-5 space-y-4">
            <div className="flex items-center gap-2">
              <ListChecks className="h-5 w-5 text-blue-600" aria-hidden="true" />
              <h2 className="text-lg font-semibold text-gray-900">Цель</h2>
            </div>

            <PlanFields form={planForm} onChange={setPlanForm} />

            {planSaved && (
              <p className="rounded-lg bg-green-50 px-3 py-2 text-sm text-green-700">План сохранён</p>
            )}

            <button
              onClick={plan ? handleSavePlan : handleCreatePlan}
              disabled={isPlanSaving}
              className="inline-flex items-center gap-2 rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
            >
              <Save className="h-4 w-4" aria-hidden="true" />
              {isPlanSaving ? 'Сохранение...' : plan ? 'Сохранить план' : 'Создать план'}
            </button>
          </section>

          {plan && (
            <>
              <section className="rounded-lg border border-gray-200 bg-white p-5">
                <div className="mb-3 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                  <div>
                    <h2 className="text-lg font-semibold text-gray-900">Прогресс</h2>
                    <p className="text-sm text-gray-500">
                      {progress.done} из {progress.total} действий завершено, активных: {progress.active}
                      {progress.applications > 0 ? `, откликов: ${progress.applied} из ${progress.applications}` : ''}
                    </p>
                  </div>
                  <span className="text-2xl font-semibold text-gray-900">{progress.percent}%</span>
                </div>
                <div className="h-2 overflow-hidden rounded-full bg-gray-100">
                  <div className="h-full bg-blue-600" style={{ width: `${progress.percent}%` }} />
                </div>
              </section>

              <section className="rounded-lg border border-gray-200 bg-white p-5 space-y-4">
                <div className="flex items-center gap-2">
                  <Plus className="h-5 w-5 text-blue-600" aria-hidden="true" />
                  <h2 className="text-lg font-semibold text-gray-900">Новое действие</h2>
                </div>

                <div className="grid grid-cols-1 gap-3 md:grid-cols-4">
                  <div className="md:col-span-2">
                    <label className="mb-1 block text-sm font-medium text-gray-700">Название</label>
                    <input
                      type="text"
                      value={actionForm.title}
                      onChange={(event) => setActionForm((form) => ({ ...form, title: event.target.value }))}
                      className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm"
                      placeholder="Например: закрыть Airflow gap"
                    />
                  </div>
                  <div>
                    <label className="mb-1 block text-sm font-medium text-gray-700">Тип</label>
                    <select
                      value={actionForm.action_type}
                      onChange={(event) =>
                        setActionForm((form) => ({
                          ...form,
                          action_type: event.target.value as CareerActionType,
                        }))
                      }
                      className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm"
                    >
                      {ACTION_TYPES.map((item) => (
                        <option key={item.value} value={item.value}>
                          {item.label}
                        </option>
                      ))}
                    </select>
                  </div>
                  <div>
                    <label className="mb-1 block text-sm font-medium text-gray-700">Приоритет</label>
                    <input
                      type="number"
                      min={0}
                      max={1000}
                      value={actionForm.priority}
                      onChange={(event) => setActionForm((form) => ({ ...form, priority: event.target.value }))}
                      className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm"
                    />
                  </div>
                  <div>
                    <label className="mb-1 block text-sm font-medium text-gray-700">Навык</label>
                    <input
                      type="text"
                      value={actionForm.skill_name}
                      onChange={(event) => setActionForm((form) => ({ ...form, skill_name: event.target.value }))}
                      className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm"
                      placeholder="SQL, Airflow"
                    />
                  </div>
                  <div className="md:col-span-3">
                    <label className="mb-1 block text-sm font-medium text-gray-700">Описание</label>
                    <input
                      type="text"
                      value={actionForm.description}
                      onChange={(event) => setActionForm((form) => ({ ...form, description: event.target.value }))}
                      className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm"
                    />
                  </div>
                </div>

                {actionSaved && (
                  <p className="rounded-lg bg-green-50 px-3 py-2 text-sm text-green-700">Действие добавлено</p>
                )}

                <button
                  onClick={handleCreateAction}
                  disabled={createAction.isPending || !actionForm.title.trim()}
                  className="inline-flex items-center gap-2 rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
                >
                  <Plus className="h-4 w-4" aria-hidden="true" />
                  {createAction.isPending ? 'Добавление...' : 'Добавить действие'}
                </button>
              </section>

              <section className="space-y-3">
                <div className="flex items-center justify-between">
                  <h2 className="text-lg font-semibold text-gray-900">Действия</h2>
                  <span className="text-sm text-gray-500">{progress.total}</span>
                </div>
                <div className="flex flex-wrap items-center gap-3">
                  <button
                    type="button"
                    onClick={handleGenerateActions}
                    disabled={generateActions.isPending || generateActionsLocked}
                    className="inline-flex items-center gap-2 rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-50"
                  >
                    <Plus className="h-4 w-4" aria-hidden="true" />
                    {generateActions.isPending ? 'Генерация...' : 'Добавить рекомендации из skill gap'}
                  </button>
                  {generationMsg && <p className="text-sm text-indigo-700">{generationMsg}</p>}
                </div>
                {generateActionsLocked && <LockedFeatureCallout feature={GENERATE_ACTIONS_ENTITLEMENT} />}

                {plan.actions.length === 0 ? (
                  <p className="rounded-lg border border-gray-200 bg-white px-4 py-3 text-sm text-gray-500">
                    Действий пока нет.
                  </p>
                ) : (
                  plan.actions.map((action) => (
                    <ActionCard
                      key={action.id}
                      action={action}
                      isUpdating={patchAction.isPending}
                      onStatusChange={(status) => updateActionStatus(action, status)}
                    />
                  ))
                )}
              </section>
            </>
          )}
        </>
      )}
    </div>
  )
}

function PlanFields({
  form,
  onChange,
}: {
  form: CareerPlanForm
  onChange: (form: CareerPlanForm) => void
}) {
  return (
    <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
      <MetaSelect
        kind="roles"
        label="Целевая роль"
        value={form.target_role}
        onChange={(value) => onChange({ ...form, target_role: value })}
      />
      <MetaSelect
        kind="grades"
        label="Грейд"
        value={form.target_grade}
        onChange={(value) => onChange({ ...form, target_grade: value })}
      />
      <MetaSelect
        kind="cityTiers"
        label="Уровень города"
        value={form.target_city_tier}
        onChange={(value) => onChange({ ...form, target_city_tier: value })}
      />
      <MetaSelect
        kind="countries"
        label="Страна"
        value={form.target_country}
        onChange={(value) => onChange({ ...form, target_country: value })}
      />
      <MetaSelect
        kind="regions"
        label="Регион"
        value={form.target_region}
        onChange={(value) => onChange({ ...form, target_region: value })}
      />
      <MetaSelect
        kind="cities"
        label="Город"
        value={form.target_city}
        onChange={(value) => onChange({ ...form, target_city: value })}
      />
      <MetaSelect
        kind="geoScopes"
        label="Рынок"
        value={form.target_geo_scope}
        onChange={(value) => onChange({ ...form, target_geo_scope: value })}
      />
      <MetaSelect
        kind="workModes"
        label="Режим работы"
        value={form.target_work_mode}
        onChange={(value) => onChange({ ...form, target_work_mode: value })}
      />
      <MetaSelect
        kind="domains"
        label="Домен"
        value={form.target_domain}
        onChange={(value) => onChange({ ...form, target_domain: value })}
      />
      <div>
        <label className="mb-1 block text-sm font-medium text-gray-700">Статус плана</label>
        <select
          value={form.status}
          onChange={(event) => onChange({ ...form, status: event.target.value as CareerPlanStatus })}
          className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm"
        >
          {PLAN_STATUSES.map((item) => (
            <option key={item.value} value={item.value}>
              {item.label}
            </option>
          ))}
        </select>
      </div>
      <div className="md:col-span-2">
        <label className="mb-1 block text-sm font-medium text-gray-700">Заметки</label>
        <textarea
          value={form.notes}
          onChange={(event) => onChange({ ...form, notes: event.target.value })}
          className="min-h-24 w-full rounded-lg border border-gray-300 px-3 py-2 text-sm"
        />
      </div>
    </div>
  )
}

function ActionCard({
  action,
  isUpdating,
  onStatusChange,
}: {
  action: CareerActionOut
  isUpdating: boolean
  onStatusChange: (status: CareerActionStatus) => void
}) {
  return (
    <article className="rounded-lg border border-gray-200 bg-white p-4">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="text-sm font-semibold text-gray-900">{action.title}</h3>
            <span className="rounded bg-gray-100 px-2 py-0.5 text-xs text-gray-600">
              {actionTypeLabel(action.action_type)}
            </span>
            <span className="rounded bg-blue-50 px-2 py-0.5 text-xs text-blue-700">
              {actionStatusLabel(action.status)}
            </span>
          </div>
          {action.description && <p className="mt-2 text-sm text-gray-600">{action.description}</p>}
          <p className="mt-2 text-xs text-gray-500">
            Приоритет: {action.priority}
            {action.skill_name ? ` · Навык: ${action.skill_name}` : ''}
            {action.recommendation_source && action.recommendation_source !== 'manual'
              ? ` · Источник: ${action.recommendation_source}`
              : ''}
            {action.due_date ? ` · До: ${formatDate(action.due_date)}` : ''}
            {action.completed_at ? ` · Завершено: ${formatDate(action.completed_at)}` : ''}
          </p>
          {action.reason && <p className="mt-2 text-xs text-gray-600">{action.reason}</p>}
          {action.expected_impact && (
            <p className="mt-1 text-xs text-gray-500">Ожидаемый эффект: {action.expected_impact}</p>
          )}
          {action.effort_estimate && (
            <p className="mt-1 text-xs text-gray-500">Оценка усилий: {action.effort_estimate}</p>
          )}
          {action.review_date && (
            <p className="mt-1 text-xs text-gray-500">Проверить прогресс: {formatDate(action.review_date)}</p>
          )}
          {action.evidence && (
            <div className="mt-2 rounded-lg bg-gray-50 px-3 py-2 text-xs text-gray-600">
              <p className="font-medium text-gray-800">Доказательная база</p>
              <ul className="mt-1 space-y-0.5">
                {evidenceItems(action.evidence).map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ul>
            </div>
          )}
          {action.application_status && (
            <p className="mt-1 text-xs font-medium text-green-700">
              Статус отклика: {action.application_status}
            </p>
          )}
          {action.vacancy_url && (
            <a
              href={action.vacancy_url}
              target="_blank"
              rel="noreferrer"
              className="mt-2 inline-block text-xs text-blue-600 hover:underline"
            >
              Открыть вакансию
            </a>
          )}
        </div>
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
          {ACTION_STATUSES.map((item) => {
            const Icon = item.icon
            const active = action.status === item.value
            return (
              <button
                key={item.value}
                onClick={() => onStatusChange(item.value)}
                disabled={isUpdating}
                className={
                  active
                    ? 'inline-flex items-center justify-center gap-1 rounded-lg bg-blue-600 px-3 py-2 text-xs font-medium text-white disabled:opacity-50'
                    : 'inline-flex items-center justify-center gap-1 rounded-lg border border-gray-200 px-3 py-2 text-xs font-medium text-gray-700 hover:border-blue-300 disabled:opacity-50'
                }
              >
                <Icon className="h-3.5 w-3.5" aria-hidden="true" />
                {item.label}
              </button>
            )
          })}
        </div>
      </div>
    </article>
  )
}

function evidenceItems(evidence: NonNullable<CareerActionOut['evidence']>): string[] {
  return Object.entries(evidence)
    .filter(([, value]) => value !== null && value !== undefined && value !== '')
    .slice(0, 5)
    .map(([key, value]) => {
      if (Array.isArray(value)) {
        return `${key}: ${value.slice(0, 5).join(', ')}`
      }
      if (typeof value === 'object') {
        return `${key}: ${JSON.stringify(value)}`
      }
      return `${key}: ${String(value)}`
    })
}
