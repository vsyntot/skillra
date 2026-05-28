/**
 * SalaryDistributionChart — box-style Q25/Median/Q75 salary visualization.
 * Sprint-008 TASK-09
 */
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell } from 'recharts'

interface SalaryDistributionChartProps {
  salary_q25: number | null
  salary_median: number | null
  salary_q75: number | null
}

export default function SalaryDistributionChart({
  salary_q25,
  salary_median,
  salary_q75,
}: SalaryDistributionChartProps) {
  const data = [
    { name: 'Q25', value: salary_q25 != null ? Math.round(salary_q25 / 1000) : 0 },
    { name: 'Медиана', value: salary_median != null ? Math.round(salary_median / 1000) : 0 },
    { name: 'Q75', value: salary_q75 != null ? Math.round(salary_q75 / 1000) : 0 },
  ].filter((d) => d.value > 0)

  if (data.length === 0) return null

  const colors = ['#93c5fd', '#3b82f6', '#1d4ed8']

  return (
    <div>
      <p className="text-sm font-medium text-gray-700 mb-2">Распределение зарплат (тыс. ₽)</p>
      <ResponsiveContainer width="100%" height={120}>
        <BarChart data={data} margin={{ top: 0, right: 8, left: -20, bottom: 0 }}>
          <XAxis dataKey="name" tick={{ fontSize: 11 }} />
          <YAxis tick={{ fontSize: 11 }} />
          <Tooltip formatter={(v: number) => [`${v}k ₽`, 'Зарплата']} />
          <Bar dataKey="value" radius={[4, 4, 0, 0]}>
            {data.map((_, index) => (
              <Cell key={index} fill={colors[index % colors.length]} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}
