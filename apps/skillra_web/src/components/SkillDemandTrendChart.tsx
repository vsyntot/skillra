import { Area, AreaChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { useSkillDemandTrend } from '../hooks/useTrends'
import type { TrendDataPoint } from '../api/client'
import TrustLabels from './TrustLabels'
import { trendBlockedMessage } from './trendTrust'

interface SkillDemandTrendChartProps {
  skill: string
  role?: string
  weeks?: number
}

interface DemandPoint {
  week: string
  vacancies: number
}

function formatWeek(value: string): string {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value

  return new Intl.DateTimeFormat('ru-RU', { day: '2-digit', month: 'short' }).format(date)
}

function toDemandPoint(point: TrendDataPoint): DemandPoint | null {
  if (point.value == null || !Number.isFinite(point.value)) return null
  return {
    week: formatWeek(point.week_start),
    vacancies: Math.round(point.value),
  }
}

export default function SkillDemandTrendChart({ skill, role, weeks = 12 }: SkillDemandTrendChartProps) {
  const { data, isLoading, isError, isFetching } = useSkillDemandTrend(skill, role, weeks)
  const chartData = (data?.data ?? []).map(toDemandPoint).filter((point): point is DemandPoint => point !== null)
  const latestTrust = data?.data?.length ? data.data[data.data.length - 1] : null
  const blockedMessage = trendBlockedMessage(data)

  return (
    <section className="bg-white rounded-xl border border-gray-100 shadow-sm p-5">
      <div className="mb-4">
        <h3 className="text-sm font-semibold text-gray-900">{skill || 'Навык не выбран'}</h3>
        <p className="text-xs text-gray-500">Спрос по вакансиям за {weeks} недель</p>
      </div>

      <div className="mb-3">
        <TrustLabels trust={latestTrust} compact />
      </div>

      {!skill ? (
        <EmptyState text="Выберите навык для тренда спроса." />
      ) : isLoading || isFetching ? (
        <div className="h-40 animate-pulse rounded-lg bg-gray-100" />
      ) : isError ? (
        <EmptyState text="Тренд спроса пока недоступен." tone="warning" />
      ) : blockedMessage ? (
        <EmptyState text={blockedMessage} tone="warning" />
      ) : chartData.length === 0 ? (
        <EmptyState text="История спроса по навыку пока пуста." />
      ) : (
        <ResponsiveContainer width="100%" height={180}>
          <AreaChart data={chartData} margin={{ top: 8, right: 8, left: -10, bottom: 0 }}>
            <XAxis dataKey="week" tick={{ fontSize: 11 }} />
            <YAxis tick={{ fontSize: 11 }} />
            <Tooltip formatter={(value: number) => [value.toLocaleString('ru-RU'), 'Вакансий']} />
            <Area
              type="monotone"
              dataKey="vacancies"
              stroke="#0f766e"
              fill="#99f6e4"
              strokeWidth={2}
            />
          </AreaChart>
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
