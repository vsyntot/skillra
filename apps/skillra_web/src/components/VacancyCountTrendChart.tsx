import { Bar, BarChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { useVacancyCountTrend } from '../hooks/useTrends'
import type { TrendDataPoint } from '../api/client'
import TrustLabels from './TrustLabels'
import { trendBlockedMessage } from './trendTrust'

interface VacancyCountTrendChartProps {
  role: string
  grade?: string
  weeks?: number
}

interface VacancyPoint {
  week: string
  vacancies: number
}

function formatWeek(value: string): string {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value

  return new Intl.DateTimeFormat('ru-RU', { day: '2-digit', month: 'short' }).format(date)
}

function toVacancyPoint(point: TrendDataPoint): VacancyPoint | null {
  if (point.value == null || !Number.isFinite(point.value)) return null
  return {
    week: formatWeek(point.week_start),
    vacancies: Math.round(point.value),
  }
}

export default function VacancyCountTrendChart({ role, grade, weeks = 12 }: VacancyCountTrendChartProps) {
  const { data, isLoading, isError, isFetching } = useVacancyCountTrend(role, grade, weeks)
  const chartData = (data?.data ?? []).map(toVacancyPoint).filter((point): point is VacancyPoint => point !== null)
  const total = chartData.reduce((sum, point) => sum + point.vacancies, 0)
  const latestTrust = data?.data?.length ? data.data[data.data.length - 1] : null
  const blockedMessage = trendBlockedMessage(data)

  return (
    <section className="bg-white rounded-xl border border-gray-100 shadow-sm p-5">
      <div className="mb-4 flex flex-col gap-1 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <h2 className="text-base font-semibold text-gray-900">Динамика вакансий</h2>
          <p className="text-sm text-gray-500">
            {role || 'Роль не выбрана'}{grade ? ` · ${grade}` : ''}
          </p>
        </div>
        {chartData.length > 0 && (
          <div className="text-left sm:text-right">
            <p className="text-xs text-gray-500">Всего за период</p>
            <p className="text-lg font-semibold text-gray-900">{total.toLocaleString('ru-RU')}</p>
          </div>
        )}
      </div>

      <div className="mb-3">
        <TrustLabels trust={latestTrust} compact />
      </div>

      {!role ? (
        <EmptyState text="Выберите роль, чтобы увидеть динамику вакансий." />
      ) : isLoading || isFetching ? (
        <div className="h-56 animate-pulse rounded-lg bg-gray-100" />
      ) : isError ? (
        <EmptyState text="Тренд вакансий пока недоступен." tone="warning" />
      ) : blockedMessage ? (
        <EmptyState text={blockedMessage} tone="warning" />
      ) : chartData.length === 0 ? (
        <EmptyState text="Для выбранного сегмента пока нет истории вакансий." />
      ) : (
        <ResponsiveContainer width="100%" height={260}>
          <BarChart data={chartData} margin={{ top: 8, right: 8, left: -10, bottom: 0 }}>
            <XAxis dataKey="week" tick={{ fontSize: 11 }} />
            <YAxis tick={{ fontSize: 11 }} />
            <Tooltip formatter={(value: number) => [value.toLocaleString('ru-RU'), 'Вакансий']} />
            <Bar dataKey="vacancies" fill="#7c3aed" radius={[4, 4, 0, 0]} />
          </BarChart>
        </ResponsiveContainer>
      )}
    </section>
  )
}

function EmptyState({ text, tone = 'muted' }: { text: string; tone?: 'muted' | 'warning' }) {
  const className =
    tone === 'warning'
      ? 'rounded-lg border border-amber-200 bg-amber-50 px-4 py-5 text-sm text-amber-800'
      : 'rounded-lg border border-gray-200 bg-gray-50 px-4 py-5 text-sm text-gray-600'

  return <div className={className}>{text}</div>
}
