import { FormEvent, useEffect, useMemo, useState } from 'react'
import type { CohortMemberOut, CohortOut, OrganizationMemberOut, OrganizationOut } from '../api/client'
import { useAuth } from '../auth/AuthContext'
import {
  useCohortAnalytics,
  useCohortMembers,
  useCohorts,
  useCreateCohort,
  useCreateOrganization,
  useCreateOrganizationInvite,
  useExportCohortAnalyticsCsv,
  useOrganizationMembers,
  useOrganizations,
  useUpdateCohortMember,
  useUpdateOrganizationMember,
} from '../hooks/useOrganizations'

const metricLabels: Record<string, string> = {
  profile_completion_rate: 'Профиль заполнен',
  market_view_rate: 'Рынок открыт',
  skill_gap_view_rate: 'Skill gap открыт',
  plan_created_rate: 'План создан',
  plan_action_started_rate: 'Есть действия',
  plan_action_done_rate: 'Есть завершение',
  vacancy_search_rate: 'Поиск вакансий',
  saved_vacancy_rate: 'Сохранены вакансии',
  application_outcome_rate: 'Есть статус отклика',
  digest_subscription_rate: 'Дайджест включён',
  digest_engagement_rate: 'Есть digest engagement',
  weekly_return_rate: 'Недельный возврат',
}

export default function OrganizationsPage() {
  const { mode } = useAuth()
  const isUserMode = mode === 'user'
  const organizations = useOrganizations(isUserMode)
  const createOrganization = useCreateOrganization()
  const [selectedOrgId, setSelectedOrgId] = useState<number>(0)
  const selectedOrg = organizations.data?.find((organization) => organization.id === selectedOrgId) ?? null
  const isOrgAdmin = selectedOrg ? selectedOrg.role === 'owner' || selectedOrg.role === 'admin' : false
  const cohorts = useCohorts(selectedOrgId, Boolean(selectedOrg))
  const selectedCohort = cohorts.data?.[0] ?? null
  const members = useOrganizationMembers(selectedOrgId, isOrgAdmin)
  const cohortMembers = useCohortMembers(selectedOrgId, selectedCohort?.id ?? 0, isOrgAdmin)
  const analytics = useCohortAnalytics(selectedOrgId, selectedCohort?.id ?? 0, 30, isOrgAdmin)
  const createCohort = useCreateCohort(selectedOrgId)
  const createInvite = useCreateOrganizationInvite(selectedOrgId)
  const exportCsv = useExportCohortAnalyticsCsv(selectedOrgId, selectedCohort?.id ?? 0, 30)
  const updateOrgMember = useUpdateOrganizationMember(selectedOrgId)
  const updateCohortMember = useUpdateCohortMember(selectedOrgId, selectedCohort?.id ?? 0)
  const [orgName, setOrgName] = useState('')
  const [cohortName, setCohortName] = useState('')
  const [inviteToken, setInviteToken] = useState<string | null>(null)

  useEffect(() => {
    if (selectedOrgId || !organizations.data?.length) return
    setSelectedOrgId(organizations.data[0].id)
  }, [organizations.data, selectedOrgId])

  const visibleMetrics = useMemo(() => analytics.data?.metrics ?? [], [analytics.data])
  const moveTargetCohort = useMemo(
    () => (selectedCohort ? (cohorts.data ?? []).find((cohort) => cohort.id !== selectedCohort.id) : undefined),
    [cohorts.data, selectedCohort],
  )

  if (!isUserMode) {
    return (
      <div className="mx-auto max-w-4xl space-y-6 p-6">
        <header>
          <h1 className="text-2xl font-bold text-gray-900">Организации</h1>
          <p className="mt-1 text-sm text-gray-500">B2B workspace доступен только в личном входе.</p>
        </header>
        <section className="rounded-lg border border-amber-200 bg-amber-50 p-5 text-sm text-amber-900">
          Войдите через личный API-ключ пользователя, чтобы увидеть организации, когорты и инвайты.
        </section>
      </div>
    )
  }

  function handleCreateOrganization(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const name = orgName.trim()
    if (!name) return
    createOrganization.mutate(
      { name, organization_type: 'other' },
      {
        onSuccess: (organization) => {
          setOrgName('')
          setSelectedOrgId(organization.id)
        },
      },
    )
  }

  function handleCreateCohort(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const name = cohortName.trim()
    if (!name || !selectedOrg) return
    createCohort.mutate(
      { name },
      {
        onSuccess: () => {
          setCohortName('')
        },
      },
    )
  }

  function handleCreateInvite() {
    if (!selectedCohort) return
    createInvite.mutate(
      { cohort_id: selectedCohort.id, role: 'member', max_uses: 25 },
      {
        onSuccess: (invite) => {
          setInviteToken(invite.token ?? null)
        },
      },
    )
  }

  function handleExport() {
    if (!selectedCohort) return
    exportCsv.mutate(undefined, {
      onSuccess: (blob) => {
        const url = URL.createObjectURL(blob)
        const link = document.createElement('a')
        link.href = url
        link.download = `cohort-${selectedCohort.id}-analytics.csv`
        link.click()
        URL.revokeObjectURL(url)
      },
    })
  }

  function handleRevokeOrgMember(userId: number) {
    updateOrgMember.mutate({ userId, payload: { status: 'revoked' } })
  }

  function handleTransferOwner(userId: number) {
    updateOrgMember.mutate({ userId, payload: { role: 'owner' } })
  }

  function handleRevokeCohortMember(userId: number) {
    updateCohortMember.mutate({ userId, payload: { status: 'revoked' } })
  }

  function handleMoveCohortMember(userId: number) {
    if (!moveTargetCohort) return
    updateCohortMember.mutate({ userId, payload: { target_cohort_id: moveTargetCohort.id } })
  }

  return (
    <div className="mx-auto max-w-5xl space-y-6 p-6">
      <header className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Организации</h1>
          <p className="mt-1 text-sm text-gray-500">Когорты, инвайты и privacy-safe B2B аналитика.</p>
        </div>
        <form onSubmit={handleCreateOrganization} className="flex flex-col gap-2 sm:w-80 sm:flex-row">
          <input
            value={orgName}
            onChange={(event) => setOrgName(event.target.value)}
            placeholder="Новая организация"
            className="rounded-lg border border-gray-300 px-3 py-2 text-sm"
          />
          <button
            type="submit"
            disabled={createOrganization.isPending || !orgName.trim()}
            className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
          >
            Создать
          </button>
        </form>
      </header>

      <section className="rounded-lg border border-gray-200 bg-white p-5">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <h2 className="text-lg font-semibold text-gray-900">Workspace</h2>
          <select
            value={selectedOrgId}
            onChange={(event) => setSelectedOrgId(Number(event.target.value))}
            className="rounded-lg border border-gray-300 px-3 py-2 text-sm"
          >
            <option value={0}>Выберите организацию</option>
            {(organizations.data ?? []).map((organization) => (
              <option key={organization.id} value={organization.id}>
                {organization.name}
              </option>
            ))}
          </select>
        </div>
        {organizations.isLoading ? (
          <p className="mt-3 text-sm text-gray-500">Загружаем организации</p>
        ) : organizations.isError ? (
          <p className="mt-3 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">
            Не удалось загрузить организации.
          </p>
        ) : selectedOrg ? (
          <OrganizationSummary organization={selectedOrg} />
        ) : (
          <p className="mt-3 text-sm text-gray-600">Организаций пока нет.</p>
        )}
      </section>

      {selectedOrg && (
        <section className="rounded-lg border border-gray-200 bg-white p-5">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <h2 className="text-lg font-semibold text-gray-900">Когорты</h2>
              <p className="mt-1 text-sm text-gray-500">Группы для пилотов, потоков и карьерных центров.</p>
            </div>
            {isOrgAdmin && (
              <form onSubmit={handleCreateCohort} className="flex flex-col gap-2 sm:w-80 sm:flex-row">
                <input
                  value={cohortName}
                  onChange={(event) => setCohortName(event.target.value)}
                  placeholder="Новая когорта"
                  className="rounded-lg border border-gray-300 px-3 py-2 text-sm"
                />
                <button
                  type="submit"
                  disabled={createCohort.isPending || !cohortName.trim()}
                  className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
                >
                  Создать
                </button>
              </form>
            )}
          </div>
          <div className="mt-4 grid grid-cols-1 gap-3 md:grid-cols-3">
            {(cohorts.data ?? []).map((cohort) => (
              <CohortSummary key={cohort.id} cohort={cohort} selected={cohort.id === selectedCohort?.id} />
            ))}
          </div>
          {!cohorts.isLoading && !cohorts.data?.length && (
            <p className="mt-3 text-sm text-gray-600">Когорты пока не созданы.</p>
          )}
        </section>
      )}

      {selectedOrg && isOrgAdmin && selectedCohort && (
        <section className="rounded-lg border border-gray-200 bg-white p-5">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <h2 className="text-lg font-semibold text-gray-900">Инвайты и участники</h2>
              <p className="mt-1 text-sm text-gray-500">Токен показывается один раз и хранится на сервере только как hash.</p>
            </div>
            <button
              type="button"
              onClick={handleCreateInvite}
              disabled={createInvite.isPending}
              className="rounded-lg bg-emerald-600 px-4 py-2 text-sm font-medium text-white hover:bg-emerald-700 disabled:opacity-50"
            >
              Создать инвайт
            </button>
          </div>
          {inviteToken && (
            <p className="mt-3 break-all rounded-lg bg-emerald-50 px-3 py-2 text-sm text-emerald-800">
              Токен инвайта: {inviteToken}
            </p>
          )}
          <div className="mt-4 grid grid-cols-1 gap-4 md:grid-cols-2">
            <OrganizationMemberList
              title="Участники организации"
              rows={members.data ?? []}
              loading={members.isLoading}
              canTransferOwner={selectedOrg.role === 'owner'}
              disabled={updateOrgMember.isPending}
              onRevoke={handleRevokeOrgMember}
              onTransferOwner={handleTransferOwner}
            />
            <CohortMemberList
              title="Участники когорты"
              rows={cohortMembers.data ?? []}
              loading={cohortMembers.isLoading}
              moveTargetName={moveTargetCohort?.name}
              disabled={updateCohortMember.isPending}
              onRevoke={handleRevokeCohortMember}
              onMove={handleMoveCohortMember}
            />
          </div>
        </section>
      )}

      {selectedOrg && isOrgAdmin && selectedCohort && (
        <section className="rounded-lg border border-gray-200 bg-white p-5">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <h2 className="text-lg font-semibold text-gray-900">Аналитика когорты</h2>
              <p className="mt-1 text-sm text-gray-500">Агрегаты скрываются при малой выборке.</p>
            </div>
            <button
              type="button"
              onClick={handleExport}
              disabled={exportCsv.isPending || analytics.data?.suppressed}
              className="rounded-lg border border-gray-300 px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-50"
            >
              CSV
            </button>
          </div>
          {analytics.isLoading ? (
            <p className="mt-3 text-sm text-gray-500">Считаем агрегаты</p>
          ) : analytics.data?.suppressed ? (
            <p className="mt-3 rounded-lg bg-amber-50 px-3 py-2 text-sm text-amber-900">
              Когорта малая: {analytics.data.member_count_bucket}. Метрики и heatmap скрыты.
            </p>
          ) : analytics.isError ? (
            <p className="mt-3 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">
              Не удалось загрузить аналитику.
            </p>
          ) : (
            <>
              <div className="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
                {visibleMetrics.map((metric) => (
                  <Metric key={metric.metric} label={metricLabels[metric.metric] ?? metric.metric} value={metric.rate ?? 0} />
                ))}
              </div>
              <div className="mt-5">
                <h3 className="text-sm font-semibold text-gray-900">Skill gap heatmap</h3>
                <div className="mt-2 overflow-x-auto">
                  <table className="min-w-full text-left text-sm">
                    <thead className="text-xs text-gray-500">
                      <tr>
                        <th className="py-2 pr-4">Навык</th>
                        <th className="py-2 pr-4">Пользователей</th>
                        <th className="py-2 pr-4">Доля</th>
                      </tr>
                    </thead>
                    <tbody>
                      {(analytics.data?.skill_heatmap ?? []).map((row) => (
                        <tr key={row.skill_name} className="border-t border-gray-100">
                          <td className="py-2 pr-4">{row.skill_name}</td>
                          <td className="py-2 pr-4">{row.suppressed ? 'скрыто' : row.users_missing_count}</td>
                          <td className="py-2 pr-4">
                            {row.suppressed ? 'скрыто' : `${Math.round((row.users_missing_share ?? 0) * 100)}%`}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            </>
          )}
        </section>
      )}
    </div>
  )
}

function OrganizationSummary({ organization }: { organization: OrganizationOut }) {
  return (
    <div className="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-4">
      <Info label="Название" value={organization.name} />
      <Info label="Роль" value={organization.role} />
      <Info label="Участники" value={String(organization.members_count)} />
      <Info label="Когорты" value={String(organization.cohorts_count)} />
    </div>
  )
}

function CohortSummary({ cohort }: { cohort: CohortOut; selected: boolean }) {
  return (
    <div className="rounded-lg border border-gray-200 bg-gray-50 px-3 py-2">
      <p className="text-sm font-medium text-gray-900">{cohort.name}</p>
      <p className="mt-1 text-xs text-gray-500">{cohort.members_count} участников</p>
    </div>
  )
}

function OrganizationMemberList({
  title,
  rows,
  loading,
  canTransferOwner,
  disabled,
  onRevoke,
  onTransferOwner,
}: {
  title: string
  rows: OrganizationMemberOut[]
  loading: boolean
  canTransferOwner: boolean
  disabled: boolean
  onRevoke: (userId: number) => void
  onTransferOwner: (userId: number) => void
}) {
  return (
    <div>
      <h3 className="text-sm font-semibold text-gray-900">{title}</h3>
      {loading ? (
        <p className="mt-2 text-sm text-gray-500">Загрузка</p>
      ) : rows.length === 0 ? (
        <p className="mt-2 text-sm text-gray-500">Нет участников</p>
      ) : (
        <div className="mt-2 divide-y divide-gray-100 rounded-lg border border-gray-100">
          {rows.map((row) => (
            <div key={row.user_id} className="flex items-center justify-between gap-3 px-3 py-2 text-sm">
              <div>
                <span className="font-medium text-gray-900">User #{row.user_id}</span>
                <span className="ml-2 text-gray-500">
                  {row.role}, {row.status}, {row.has_profile ? 'профиль есть' : 'без профиля'}
                </span>
              </div>
              {row.status === 'active' && row.role !== 'owner' && (
                <div className="flex shrink-0 gap-2">
                  {canTransferOwner && (
                    <button
                      type="button"
                      disabled={disabled}
                      onClick={() => onTransferOwner(row.user_id)}
                      className="rounded border border-gray-300 px-2 py-1 text-xs font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-50"
                    >
                      Owner
                    </button>
                  )}
                  <button
                    type="button"
                    disabled={disabled}
                    onClick={() => onRevoke(row.user_id)}
                    className="rounded border border-red-200 px-2 py-1 text-xs font-medium text-red-700 hover:bg-red-50 disabled:opacity-50"
                  >
                    Revoke
                  </button>
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

function CohortMemberList({
  title,
  rows,
  loading,
  moveTargetName,
  disabled,
  onRevoke,
  onMove,
}: {
  title: string
  rows: CohortMemberOut[]
  loading: boolean
  moveTargetName?: string
  disabled: boolean
  onRevoke: (userId: number) => void
  onMove: (userId: number) => void
}) {
  return (
    <div>
      <h3 className="text-sm font-semibold text-gray-900">{title}</h3>
      {loading ? (
        <p className="mt-2 text-sm text-gray-500">Загрузка</p>
      ) : rows.length === 0 ? (
        <p className="mt-2 text-sm text-gray-500">Нет участников</p>
      ) : (
        <div className="mt-2 divide-y divide-gray-100 rounded-lg border border-gray-100">
          {rows.map((row) => (
            <div key={row.user_id} className="flex items-center justify-between gap-3 px-3 py-2 text-sm">
              <div>
                <span className="font-medium text-gray-900">User #{row.user_id}</span>
                <span className="ml-2 text-gray-500">
                  {row.status}, {row.has_profile ? 'профиль есть' : 'без профиля'}
                </span>
              </div>
              {row.status === 'active' && (
                <div className="flex shrink-0 gap-2">
                  {moveTargetName && (
                    <button
                      type="button"
                      disabled={disabled}
                      onClick={() => onMove(row.user_id)}
                      className="rounded border border-gray-300 px-2 py-1 text-xs font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-50"
                    >
                      Move
                    </button>
                  )}
                  <button
                    type="button"
                    disabled={disabled}
                    onClick={() => onRevoke(row.user_id)}
                    className="rounded border border-red-200 px-2 py-1 text-xs font-medium text-red-700 hover:bg-red-50 disabled:opacity-50"
                  >
                    Revoke
                  </button>
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

function Metric({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-lg bg-gray-50 px-3 py-2">
      <p className="text-xs text-gray-500">{label}</p>
      <p className="mt-1 text-lg font-semibold text-gray-900">{Math.round(value * 100)}%</p>
    </div>
  )
}

function Info({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg bg-gray-50 px-3 py-2">
      <p className="text-xs text-gray-500">{label}</p>
      <p className="mt-1 text-sm font-medium text-gray-900">{value}</p>
    </div>
  )
}
