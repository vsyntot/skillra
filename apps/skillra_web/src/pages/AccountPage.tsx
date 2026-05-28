import { useMutation, useQuery } from '@tanstack/react-query'
import { deleteProfile, fetchCurrentApiKeyStatus, revokeCurrentApiKey } from '../api/client'
import { useAuth } from '../auth/AuthContext'
import {
  PLAN_LABELS,
  SUBSCRIPTION_STATE_LABELS,
  lockedFeatureText,
} from '../components/commercial'
import { useCommercialState } from '../hooks/useCommercialState'

export default function AccountPage() {
  const { mode, telegramUserId, logout } = useAuth()
  const isUserMode = mode === 'user' && Boolean(telegramUserId)
  const runtimeEnv = String(import.meta.env.VITE_SKILLRA_RUNTIME_ENV ?? 'local')
  const isProtectedRuntime = ['staging', 'prod'].includes(runtimeEnv)
  const commercialState = useCommercialState(isUserMode ? telegramUserId ?? 0 : 0)
  const keyStatus = useQuery({
    queryKey: ['account', 'api-key'],
    queryFn: fetchCurrentApiKeyStatus,
    enabled: isUserMode,
    retry: false,
  })
  const revokeKey = useMutation({
    mutationFn: () => revokeCurrentApiKey('web'),
    onSuccess: () => {
      logout()
      window.location.href = '/login'
    },
  })
  const deleteProfileMutation = useMutation({
    mutationFn: () => deleteProfile(telegramUserId ?? 0),
    onSuccess: () => {
      logout()
      window.location.href = '/login'
    },
  })

  return (
    <div className="mx-auto max-w-3xl space-y-6 p-6">
      <div>
        <h1 className="text-2xl font-bold text-gray-900">Аккаунт</h1>
        <p className="mt-1 text-sm text-gray-500">Доступ, приватность и удаление данных пользователя.</p>
      </div>

      <section className="rounded-lg border border-gray-200 bg-white p-5">
        <h2 className="text-lg font-semibold text-gray-900">Доступ</h2>
        <div className="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-2">
          <Info label="Режим" value={mode === 'user' ? 'Личный вход' : 'Командный режим'} />
          <Info label="Telegram ID" value={telegramUserId ? String(telegramUserId) : 'не определён'} />
          <Info
            label="API-ключ"
            value={
              !isUserMode
                ? 'доступен в личном входе'
                : keyStatus.isLoading
                  ? 'загрузка'
                  : keyStatus.data?.is_active
                    ? `активен, префикс ${keyStatus.data.key_prefix}`
                    : 'не найден'
            }
          />
          <Info
            label="Последнее использование"
            value={keyStatus.data?.last_used_at ? new Date(keyStatus.data.last_used_at).toLocaleString('ru-RU') : '—'}
          />
        </div>
        {isUserMode && (
          <button
            type="button"
            onClick={() => revokeKey.mutate()}
            disabled={revokeKey.isPending || !keyStatus.data?.is_active}
            className="mt-4 rounded-lg border border-red-200 px-4 py-2 text-sm font-medium text-red-700 hover:bg-red-50 disabled:opacity-50"
          >
            {revokeKey.isPending ? 'Отзываем...' : 'Отозвать текущий ключ'}
          </button>
        )}
      </section>

      <section className="rounded-lg border border-gray-200 bg-white p-5">
        <h2 className="text-lg font-semibold text-gray-900">Тариф</h2>
        {!isUserMode ? (
          <p className="mt-3 text-sm text-gray-600">Коммерческий статус доступен только в личном входе.</p>
        ) : commercialState.isLoading ? (
          <p className="mt-3 text-sm text-gray-500">Загрузка тарифа</p>
        ) : commercialState.isError || !commercialState.data ? (
          <p className="mt-3 rounded-lg bg-amber-50 px-3 py-2 text-sm text-amber-800">
            Тариф временно недоступен. Базовые функции продолжают работать.
          </p>
        ) : (
          <>
            <div className="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-2">
              <Info label="План" value={PLAN_LABELS[commercialState.data.plan] ?? commercialState.data.plan} />
              <Info
                label="Статус"
                value={
                  SUBSCRIPTION_STATE_LABELS[commercialState.data.subscription_state] ??
                  commercialState.data.subscription_state
                }
              />
              <Info
                label="Пробный период"
                value={
                  commercialState.data.trial_ends_at
                    ? new Date(commercialState.data.trial_ends_at).toLocaleDateString('ru-RU')
                    : '—'
                }
              />
              <Info
                label="Период оплаты"
                value={
                  commercialState.data.current_period_ends_at
                    ? new Date(commercialState.data.current_period_ends_at).toLocaleDateString('ru-RU')
                    : '—'
                }
              />
            </div>
            {commercialState.data.locked_features.length > 0 ? (
              <div className="mt-4 rounded-lg bg-amber-50 px-3 py-2 text-sm text-amber-900">
                Закрыто: {commercialState.data.locked_features.map(lockedFeatureText).join(', ')}.
              </div>
            ) : (
              <p className="mt-4 rounded-lg bg-emerald-50 px-3 py-2 text-sm text-emerald-800">
                Pro-возможности доступны.
              </p>
            )}
            {runtimeEnv === 'staging' ? (
              <p className="mt-3 rounded-lg bg-sky-50 px-3 py-2 text-sm text-sky-900">
                Это staging-песочница: платежные операции нужны только для проверки поддержки и учета.
              </p>
            ) : isProtectedRuntime ? (
              <p className="mt-3 rounded-lg bg-gray-50 px-3 py-2 text-sm text-gray-700">
                Публичный запуск оплат требует отдельного подтверждения. При проблемах с оплатой обратитесь в поддержку.
              </p>
            ) : null}
            {['payment_failed', 'provider_unavailable', 'past_due'].includes(
              commercialState.data.subscription_state,
            ) ? (
              <p className="mt-3 rounded-lg bg-rose-50 px-3 py-2 text-sm text-rose-900">
                При проблемах с оплатой обратитесь в поддержку. Технические данные провайдера не показываются в
                аккаунте.
              </p>
            ) : null}
          </>
        )}
      </section>

      <section className="rounded-lg border border-gray-200 bg-white p-5">
        <h2 className="text-lg font-semibold text-gray-900">Приватность</h2>
        <div className="mt-3 space-y-2 text-sm text-gray-600">
          <p>Skillra хранит профиль, карьерный план, подписку, статусы откликов и технические события продукта.</p>
          <p>PM-аналитика строится агрегированно: без имён, Telegram handles, резюме и сырого текста пользователя.</p>
          <p>Резюме и файлы можно удалить отдельно в соответствующем сценарии; профиль можно удалить ниже.</p>
        </div>
      </section>

      <section className="rounded-lg border border-red-100 bg-white p-5">
        <h2 className="text-lg font-semibold text-gray-900">Удаление профиля</h2>
        <p className="mt-2 text-sm text-gray-600">
          Удаление профиля отключит персональные рекомендации до повторного заполнения профиля.
        </p>
        <button
          type="button"
          onClick={() => deleteProfileMutation.mutate()}
          disabled={!isUserMode || deleteProfileMutation.isPending}
          className="mt-4 rounded-lg bg-red-600 px-4 py-2 text-sm font-medium text-white hover:bg-red-700 disabled:opacity-50"
        >
          {deleteProfileMutation.isPending ? 'Удаляем...' : 'Удалить профиль'}
        </button>
        {!isUserMode && (
          <p className="mt-2 text-xs text-amber-700">Удаление доступно только в личном входе пользователя.</p>
        )}
      </section>
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
