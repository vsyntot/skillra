import type { SkillGapEntry } from '../api/client'
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'

interface SkillGapChartProps {
  data: SkillGapEntry[]
  /** Max number of skills to display (default 10) */
  topK?: number
}

/**
 * Horizontal bar chart showing market demand share for each skill.
 * Skills that have a gap (persona is missing them) are highlighted.
 */
export default function SkillGapChart({ data, topK = 10 }: SkillGapChartProps) {
  const chartData = data
    .slice(0, topK)
    .map((entry) => ({
      name: entry.skill_name,
      market_share: Math.round(entry.market_share * 100),
      fill: entry.gap ? '#EF4444' : '#10B981', // red = missing, green = has
    }))
    .reverse() // highest share at top

  if (chartData.length === 0) {
    return (
      <div className="flex items-center justify-center h-48 text-gray-400">
        Нет данных для отображения
      </div>
    )
  }

  return (
    <ResponsiveContainer width="100%" height={Math.max(200, chartData.length * 36)}>
      <BarChart data={chartData} layout="vertical" margin={{ left: 80, right: 20 }}>
        <CartesianGrid strokeDasharray="3 3" horizontal={false} />
        <XAxis type="number" unit="%" domain={[0, 100]} />
        <YAxis type="category" dataKey="name" width={80} tick={{ fontSize: 12 }} />
        <Tooltip
          formatter={(value: number) => [`${value}%`, 'Доля вакансий']}
          labelFormatter={(label: string) => label}
        />
        <Bar dataKey="market_share" fill="#3B82F6" radius={[0, 4, 4, 0]}>
          {chartData.map((entry, index) => (
            <rect key={`bar-${index}`} fill={entry.fill} />
          ))}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  )
}
