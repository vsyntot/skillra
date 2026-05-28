import { useEffect, useMemo, useState } from 'react'
import { useAuth } from '../auth/AuthContext'
import { useDeleteSubscription, useSubscription, useUpsertSubscription } from '../hooks/useSubscription'

const WEEKDAYS = ['Понедельник', 'Вторник', 'Среда', 'Четверг', 'Пятница', 'Суббота', 'Воскресенье']

function defaultTimezone() {
  return Intl.DateTimeFormat().resolvedOptions().timeZone || 'Europe/Moscow'
}

export default function SubscriptionPage() {
  const { mode, telegramUserId } = useAuth()
  const [manualId, setManualId] = useState('')
  const [serviceUserId, setServiceUserId] = useState(0)
  const effectiveUserId = mode === 'user' ? telegramUserId ?? 0 : serviceUserId
  const [saved, setSaved] = useState(false)

  const [form, setForm] = useState({
    active: true,
    weekday: 0,
    time_local: '09:00',
    timezone: defaultTimezone(),
  })

  const { data, isLoading, isError } = useSubscription(effectiveUserId)
  const upsertMutation = useUpsertSubscription(effectiveUserId)
  const deleteMutation = useDeleteSubscription(effectiveUserId)

  useEffect(() => {
    if (!data) return
    setForm({
      active: data.active,
      weekday: data.weekday,
      time_local: data.time_local,
      timezone: data.timezone,
    })
  }, [data])

  const isUserSelected = effectiveUserId > 0
  const statusText = useMemo(() => {
    if (!isUserSelected) return 'Выберите пользователя'
    if (isLoading) return 'Загрузка...'
    if (data?.active) return 'Активна'
    if (data && !data.active) return 'На паузе'
    if (isError) return 'Подписка не настроена'
    return 'Готово'
  }, [data, isError, isLoading, isUserSelected])

  function handleLoad() {
    const parsed = Number.parseInt(manualId, 10)
    if (Number.isFinite(parsed) && parsed > 0) {
      setServiceUserId(parsed)
      setSaved(false)
    }
  }

  function handleSave() {
    setSaved(false)
    upsertMutation.mutate(form, {
      onSuccess: () => setSaved(true),
    })
  }

  function handleDelete() {
    setSaved(false)
    deleteMutation.mutate(undefined, {
      onSuccess: () => {
        setForm((current) => ({ ...current, active: false }))
      },
    })
  }

  return (
    <div className="max-w-2xl mx-auto p-6 space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-gray-900">Подписка на дайджест</h1>
        <p className="mt-1 text-sm text-gray-500">Настройка еженедельного Telegram-дайджеста.</p>
      </div>

      {mode !== 'user' && (
        <div className="flex gap-3">
          <input
            type="number"
            value={manualId}
            onChange={(e) => setManualId(e.target.value)}
            placeholder="Telegram User ID"
            className="flex-1 border border-gray-300 rounded-lg px-3 py-2 text-sm"
          />
          <button
            onClick={handleLoad}
            className="bg-blue-600 text-white rounded-lg px-4 py-2 text-sm font-medium hover:bg-blue-700"
          >
            Загрузить
          </button>
        </div>
      )}

      <div className="bg-white rounded-xl border border-gray-200 p-5 space-y-4">
        <div className="flex items-center justify-between gap-3">
          <div>
            <p className="text-sm font-medium text-gray-900">Telegram ID</p>
            <p className="text-sm text-gray-500">{isUserSelected ? effectiveUserId : 'Не выбран'}</p>
          </div>
          <span className="rounded-full bg-gray-100 px-3 py-1 text-xs text-gray-600">{statusText}</span>
        </div>

        <label className="flex items-center gap-2 text-sm text-gray-700">
          <input
            type="checkbox"
            checked={form.active}
            onChange={(e) => setForm((current) => ({ ...current, active: e.target.checked }))}
            className="h-4 w-4 rounded border-gray-300"
          />
          Активная подписка
        </label>

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">День недели</label>
            <select
              value={form.weekday}
              onChange={(e) => setForm((current) => ({ ...current, weekday: Number(e.target.value) }))}
              className="w-full border border-gray-300 rounded-lg bg-white px-3 py-2 text-sm"
            >
              {WEEKDAYS.map((day, index) => (
                <option key={day} value={index}>
                  {day}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Время</label>
            <input
              type="time"
              value={form.time_local}
              onChange={(e) => setForm((current) => ({ ...current, time_local: e.target.value }))}
              className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm"
            />
          </div>
        </div>

        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">Часовой пояс</label>
          <input
            type="text"
            value={form.timezone}
            onChange={(e) => setForm((current) => ({ ...current, timezone: e.target.value }))}
            placeholder="Europe/Moscow"
            className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm"
          />
        </div>

        {saved && <p className="text-sm text-green-700 bg-green-50 rounded-lg px-3 py-2">Подписка сохранена</p>}
        {upsertMutation.isError && (
          <p className="text-sm text-red-700 bg-red-50 rounded-lg px-3 py-2">Не удалось сохранить подписку</p>
        )}
        {deleteMutation.isError && (
          <p className="text-sm text-red-700 bg-red-50 rounded-lg px-3 py-2">Не удалось удалить подписку</p>
        )}

        <div className="flex flex-wrap gap-3">
          <button
            onClick={handleSave}
            disabled={!isUserSelected || upsertMutation.isPending}
            className="bg-blue-600 text-white rounded-lg px-4 py-2 text-sm font-medium hover:bg-blue-700 disabled:opacity-50"
          >
            {upsertMutation.isPending ? 'Сохранение...' : 'Сохранить'}
          </button>
          <button
            onClick={handleDelete}
            disabled={!isUserSelected || !data || deleteMutation.isPending}
            className="bg-white border border-gray-300 text-gray-700 rounded-lg px-4 py-2 text-sm font-medium hover:bg-gray-50 disabled:opacity-50"
          >
            {deleteMutation.isPending ? 'Удаление...' : 'Отключить'}
          </button>
        </div>
      </div>
    </div>
  )
}
