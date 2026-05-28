import { Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { useSalaryTrend } from '../hooks/useTrends'
import type { TrendDataPoint } from '../api/client'
import TrustLabels from './TrustLabels'
import { trendBlockedMessage } from './trendTrust'

interface SalaryTrendChartProps {
  role: string
  grade: string
  weeks?: number
  compact?: boolean
}

interface SalaryPoint {
  week: string
  salary: number
}

function formatWeek(value: string): string {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value

  return new Intl.DateTimeFormat('ru-RU', { day: '2-digit', month: 'short' }).format(date)
}

function toSalaryPoint(point: TrendDataPoint): SalaryPoint | null {
  if (point.value == null || !Number.isFinite(point.value)) return null
  return {
    week: formatWeek(point.week_start),
    salary: Math.round(point.value / 1000),
  }
}

export default function SalaryTrendChart({ role, grade, weeks = 12, compact = false }: SalaryTrendChartProps) {
  const { data, isLoading, isError, isFetching } = useSalaryTrend(role, grade, weeks)
  const chartData = (data?.data ?? []).map(toSalaryPoint).filter((point): point is SalaryPoint => point !== null)
  const latest = chartData.length > 0 ? chartData[chartData.length - 1] : undefined
  const latestTrust = data?.data?.length ? data.data[data.data.length - 1] : null
  const blockedMessage = trendBlockedMessage(data)
  const height = compact ? 180 : 260

  return (
    <section className="bg-white rounded-xl border border-gray-100 shadow-sm p-5">
      <div className="mb-4 flex flex-col gap-1 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <h2 className="text-base font-semibold text-gray-900">Тренд зарплаты</h2>
          <p className="text-sm text-gray-500">
            {role || 'Роль не выбрана'} · {grade || 'грейд не выбран'}
          </p>
        </div>
        {latest && (
          <div className="text-left sm:text-right">
            <p className="text-xs text-gray-500">Последняя точка</p>
            <p className="text-lg font-semibold text-gray-900">{latest.salary.toLocaleString('ru-RU')}k ₽</p>
          </div>
        )}
      </div>

      <div className="mb-3">
        <TrustLabels trust={latestTrust} compact />
      </div>

      {!role || !grade ? (
        <EmptyState text="Выберите роль и грейд, чтобы увидеть динамику зарплат." />
      ) : isLoading || isFetching ? (
        <ChartSkeleton />
      ) : isError ? (
        <EmptyState text="Тренд зарплат пока недоступен." tone="warning" />
      ) : blockedMessage ? (
        <EmptyState text={blockedMessage} tone="warning" />
      ) : chartData.length === 0 ? (
        <EmptyState text="Для выбранного сегмента пока нет истории зарплат." />
      ) : (
        <ResponsiveContainer width="100%" height={height}>
          <LineChart data={chartData} margin={{ top: 8, right: 8, left: -8, bottom: 0 }}>
            <XAxis dataKey="week" tick={{ fontSize: 11 }} />
            <YAxis tick={{ fontSize: 11 }} unit="k" />
            <Tooltip formatter={(value: number) => [`${value.toLocaleString('ru-RU')}k ₽`, 'P50']} />
            <Line
              type="monotone"
              dataKey="salary"
              stroke="#2563eb"
              strokeWidth={2}
              dot={{ r: 3 }}
              activeDot={{ r: 5 }}
            />
          </LineChart>
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

function ChartSkeleton() {
  return (
    <div className="h-48 animate-pulse rounded-lg bg-gray-100">
      <div className="h-full rounded-lg bg-gradient-to-r from-gray-100 via-gray-50 to-gray-100" />
    </div>
  )
}
