import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { apiClient } from '../api/client'
import { useAuth } from '../auth/AuthContext'
import type { SessionMode } from '../auth/TokenStore'

const DEFAULT_TELEGRAM_BOT_USERNAME = 'skillra_bot'

function telegramBotUsername(): string {
  const configured = import.meta.env.VITE_TELEGRAM_BOT_USERNAME as string | undefined
  return (configured || DEFAULT_TELEGRAM_BOT_USERNAME).replace(/^@/, '')
}

export default function LoginPage() {
  const serviceLoginEnabled = import.meta.env.VITE_ENABLE_SERVICE_LOGIN === '1'
  const botUsername = telegramBotUsername()
  const botUrl = `https://t.me/${botUsername}`
  const [mode, setMode] = useState<SessionMode>('user')
  const [token, setTokenValue] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const navigate = useNavigate()
  const { login } = useAuth()

  const handleSubmit = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault()
    const trimmedToken = token.trim()
    if (!trimmedToken) return

    setLoading(true)
    setError(null)
    try {
      if (mode === 'service' && serviceLoginEnabled) {
        await apiClient.get('/v1/auth/check', {
          headers: { 'X-Skillra-Token': trimmedToken },
        })
        login({ mode, token: trimmedToken })
      } else {
        const { data } = await apiClient.get<{ telegram_user_id: number }>('/v1/users/me', {
          headers: { Authorization: `Bearer ${trimmedToken}` },
        })
        login({ mode, token: trimmedToken, telegramUserId: data.telegram_user_id })
      }
      navigate('/', { replace: true })
    } catch {
      setError(
        mode === 'service'
          ? 'Неверный системный токен или сервер недоступен.'
          : 'Неверный пользовательский ключ. Проверьте ключ из Telegram-бота и повторите попытку.',
      )
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-50 p-4">
      <div className="bg-white rounded-2xl shadow-lg p-8 w-full max-w-md">
        <h1 className="text-2xl font-bold text-gray-900 mb-2">Skillra</h1>
        <p className="text-gray-500 mb-5 text-sm">
          Войдите в карьерный навигатор через персональный ключ.
        </p>

        {!serviceLoginEnabled && (
          <div className="mb-5 rounded-lg border border-blue-100 bg-blue-50 px-4 py-3 text-sm text-blue-950">
            <p className="font-medium">Где взять ключ</p>
            <ol className="mt-2 list-decimal space-y-1 pl-4">
              <li>
                Откройте Telegram-бота{' '}
                <a
                  href={botUrl}
                  target="_blank"
                  rel="noreferrer"
                  className="font-medium text-blue-700 underline underline-offset-2 hover:text-blue-900"
                >
                  @{botUsername}
                </a>
                .
              </li>
              <li>
                Отправьте команду <code className="font-mono text-xs">/api_key</code>.
              </li>
              <li>
                Вставьте сюда полученный ключ вида <code className="font-mono text-xs">sk_...</code>.
              </li>
            </ol>
          </div>
        )}

        {serviceLoginEnabled && (
          <div className="mb-5 grid grid-cols-2 gap-2" role="tablist" aria-label="Режим входа">
            <button
              type="button"
              onClick={() => {
                setMode('service')
                setError(null)
              }}
              className={`rounded-lg border px-3 py-2 text-sm font-medium ${
                mode === 'service'
                  ? 'border-blue-600 bg-blue-50 text-blue-700'
                  : 'border-gray-200 bg-white text-gray-600 hover:bg-gray-50'
              }`}
            >
              Системный
            </button>
            <button
              type="button"
              onClick={() => {
                setMode('user')
                setError(null)
              }}
              className={`rounded-lg border px-3 py-2 text-sm font-medium ${
                mode === 'user'
                  ? 'border-blue-600 bg-blue-50 text-blue-700'
                  : 'border-gray-200 bg-white text-gray-600 hover:bg-gray-50'
              }`}
            >
              Пользователь
            </button>
          </div>
        )}

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label htmlFor="token" className="block text-sm font-medium text-gray-700 mb-1">
              {mode === 'service' ? 'Системный токен' : 'Пользовательский ключ'}
            </label>
            <input
              id="token"
              type="password"
              value={token}
              onChange={(e) => setTokenValue(e.target.value)}
              placeholder={mode === 'service' ? 'Системный токен...' : 'sk_...'}
              autoComplete="current-password"
              className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              disabled={loading}
            />
            {mode === 'service' && (
              <p className="mt-2 text-xs text-amber-700">
                Системный режим предназначен только для закрытых контуров и локальной разработки.
              </p>
            )}
          </div>

          {error && (
            <p className="text-red-600 text-sm bg-red-50 rounded-lg px-3 py-2">{error}</p>
          )}

          <button
            type="submit"
            disabled={!token.trim() || loading}
            className="w-full bg-blue-600 text-white rounded-lg px-4 py-2 text-sm font-medium hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            {loading ? 'Проверка...' : 'Войти в Skillra'}
          </button>
        </form>
      </div>
    </div>
  )
}
