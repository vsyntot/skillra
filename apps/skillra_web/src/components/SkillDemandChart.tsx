/**
 * SkillDemandChart — horizontal bar chart of top skills by market share.
 * Sprint-008 TASK-09
 */
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer } from 'recharts'

interface SkillDemandEntry {
  skill_name: string
  market_share: number
}

interface SkillDemandChartProps {
  data: SkillDemandEntry[]
  topN?: number
}

export default function SkillDemandChart({ data, topN = 10 }: SkillDemandChartProps) {
  const chartData = data
    .slice(0, topN)
    .map((d) => ({ name: d.skill_name, share: Math.round(d.market_share * 100) }))
    .reverse() // largest at top for horizontal bar

  if (chartData.length === 0) return null

  return (
    <div>
      <p className="text-sm font-medium text-gray-700 mb-2">Спрос на навыки (%)</p>
      <ResponsiveContainer width="100%" height={chartData.length * 28 + 20}>
        <BarChart
          data={chartData}
          layout="vertical"
          margin={{ top: 0, right: 8, left: 60, bottom: 0 }}
        >
          <XAxis type="number" domain={[0, 100]} tick={{ fontSize: 11 }} unit="%" />
          <YAxis type="category" dataKey="name" tick={{ fontSize: 11 }} width={60} />
          <Tooltip formatter={(v: number) => [`${v}%`, 'Спрос']} />
          <Bar dataKey="share" fill="#3b82f6" radius={[0, 4, 4, 0]} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}
