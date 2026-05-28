/**
 * DigestHistoryPage — shows user's weekly digest send history.
 * Sprint-007 TASK-10
 */
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'
import { useDigestHistory, useDigestPreview } from '../hooks/useDigestHistory'

export default function DigestHistoryPage() {
  const { mode, telegramUserId: currentTelegramUserId } = useAuth()
  const [inputId, setInputId] = useState('')
  const [telegramUserId, setTelegramUserId] = useState(0)
  const [offset, setOffset] = useState(0)
  const limit = 10
  const effectiveUserId = mode === 'user' ? currentTelegramUserId ?? 0 : telegramUserId

  const { data, isLoading, isError } = useDigestHistory(effectiveUserId, limit, offset)
  const digestPreview = useDigestPreview(effectiveUserId)

  const handleLoad = () => {
    const id = parseInt(inputId, 10)
    if (!isNaN(id) && id > 0) {
      setTelegramUserId(id)
      setOffset(0)
    }
  }

  return (
    <div className="max-w-2xl mx-auto p-6">
      <h1 className="text-2xl font-bold text-gray-900 mb-6">История дайджестов</h1>

      {mode !== 'user' && (
        <div className="flex gap-3 mb-6">
          <input
            type="number"
            value={inputId}
            onChange={(e) => setInputId(e.target.value)}
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

      {effectiveUserId <= 0 && (
        <p className="text-gray-500 text-sm bg-white rounded-lg border border-gray-200 px-3 py-2">
          {mode === 'user' ? 'Не удалось определить Telegram User ID по сессии.' : 'Укажите Telegram User ID.'}
        </p>
      )}

      {isLoading && <p className="text-gray-500 text-sm">Загрузка...</p>}
      {isError && <p className="text-red-600 text-sm">Ошибка загрузки данных</p>}

      {data && (
        <>
          <section className="mb-6 rounded-lg border border-gray-200 bg-white p-4">
            <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
              <div>
                <h2 className="text-sm font-semibold text-gray-900">Текущий дайджест</h2>
                <p className="mt-1 text-sm text-gray-500">Проверьте, что получит пользователь в ближайшем выпуске.</p>
              </div>
              <div className="flex flex-wrap gap-2">
                <button
                  type="button"
                  onClick={() => digestPreview.refetch()}
                  disabled={effectiveUserId <= 0 || digestPreview.isFetching}
                  className="rounded-lg bg-blue-600 px-3 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
                >
                  {digestPreview.isFetching ? 'Загрузка...' : 'Показать preview'}
                </button>
                <Link
                  to="/subscription"
                  className="rounded-lg border border-gray-200 px-3 py-2 text-sm font-medium text-gray-700 hover:border-blue-300"
                >
                  Настроить подписку
                </Link>
              </div>
            </div>
            {digestPreview.isError && (
              <p className="mt-3 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">
                Не удалось собрать preview дайджеста.
              </p>
            )}
            {digestPreview.data && (
              <div className="mt-3 rounded-lg bg-gray-50 px-3 py-2 text-sm text-gray-700">
                <p className="mb-2 text-xs text-gray-500">
                  Доверие: {digestPreview.data.confidence ?? '—'} · свежесть: {digestPreview.data.freshness ?? '—'}
                </p>
                <pre className="whitespace-pre-wrap font-sans">{stripHtml(digestPreview.data.text)}</pre>
              </div>
            )}
          </section>

          <p className="text-sm text-gray-500 mb-4">Всего записей: {data.total}</p>

          {data.items.length === 0 && (
            <p className="text-gray-400 text-sm">Дайджесты пока не отправлялись</p>
          )}

          <div className="space-y-3">
            {data.items.map((item) => (
              <div key={item.id} className="bg-white rounded-xl border border-gray-200 p-4">
                <div className="flex items-center justify-between mb-2">
                  <span className="text-sm font-medium text-gray-900">
                    {new Date(item.sent_at).toLocaleString('ru-RU')}
                  </span>
                  <span className="text-xs text-gray-500 bg-gray-100 rounded px-2 py-0.5">
                    {item.format}
                  </span>
                </div>
                {item.text_preview && (
                  <p className="text-sm text-gray-600 line-clamp-2">{item.text_preview}</p>
                )}
              </div>
            ))}
          </div>

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
        </>
      )}
    </div>
  )
}

function stripHtml(value: string): string {
  return value.replace(/<[^>]*>/g, '')
}
