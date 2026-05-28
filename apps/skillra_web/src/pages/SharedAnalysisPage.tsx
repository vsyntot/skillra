/**
 * SharedAnalysisPage — read-only view of a shared persona analysis.
 * Accessible without authentication via share token.
 * Sprint-009 TASK-13.
 */
import { useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'
import SkillGapChart from '../components/SkillGapChart'
import { getSharedAnalysis, type PersonaAnalysisResponse } from '../api/client'

export default function SharedAnalysisPage() {
  const { token } = useParams<{ token: string }>()
  const [data, setData] = useState<PersonaAnalysisResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!token) {
      setError('Неверная ссылка')
      setLoading(false)
      return
    }
    getSharedAnalysis(token)
      .then((analysis) => {
        setData(analysis)
        setLoading(false)
      })
      .catch((err) => {
        if (err.response?.status === 404) {
          setError('Ссылка устарела или не существует. Срок действия — 7 дней.')
        } else {
          setError('Не удалось загрузить данные. Попробуйте позже.')
        }
        setLoading(false)
      })
  }, [token])

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-screen">
        <p className="text-gray-500">Загружаем анализ...</p>
      </div>
    )
  }

  if (error || !data) {
    return (
      <div className="flex items-center justify-center min-h-screen">
        <div className="bg-red-50 border border-red-200 rounded-lg p-6 text-red-700 max-w-md text-center">
          <p className="font-semibold mb-2">Ошибка</p>
          <p className="text-sm">{error ?? 'Не удалось загрузить данные'}</p>
        </div>
      </div>
    )
  }

  return (
    <div className="max-w-4xl mx-auto px-4 py-8 space-y-8">
      <div className="text-center space-y-2">
        <h1 className="text-2xl font-bold text-gray-900">Shared Skill Gap Analysis</h1>
        <p className="text-sm text-gray-500">Только для просмотра · Авторизация не требуется</p>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <StatCard label="Вакансий" value={data.market_summary.vacancy_count} />
        <StatCard
          label="Медиана зп"
          value={
            data.market_summary.salary_median != null
              ? `${(data.market_summary.salary_median / 1000).toFixed(0)}k ₽`
              : '—'
          }
        />
        <StatCard label="Рекомендовано скиллов" value={data.recommended_skills.length} />
        <StatCard label="Гэпов" value={data.skill_gap.filter((s) => s.gap).length} />
      </div>

      <div className="bg-white rounded-xl shadow-sm border border-gray-100 p-6">
        <h2 className="text-lg font-semibold text-gray-900 mb-4">Skill Gap</h2>
        <SkillGapChart data={data.skill_gap} />
      </div>

      {data.recommended_skills.length > 0 && (
        <div className="bg-white rounded-xl shadow-sm border border-gray-100 p-6">
          <h2 className="text-lg font-semibold text-gray-900 mb-3">Рекомендуем к изучению</h2>
          <div className="flex flex-wrap gap-2">
            {data.recommended_skills.map((skill) => (
              <span
                key={skill}
                className="bg-indigo-50 text-indigo-700 text-sm px-3 py-1 rounded-full"
              >
                {skill}
              </span>
            ))}
          </div>
        </div>
      )}

      {data.warnings.length > 0 && (
        <div className="bg-amber-50 border border-amber-200 rounded-lg p-4 text-amber-700 text-sm space-y-1">
          {data.warnings.map((w, i) => (
            <p key={i}>⚠️ {w}</p>
          ))}
        </div>
      )}
    </div>
  )
}

function StatCard({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="bg-white rounded-xl shadow-sm border border-gray-100 p-4">
      <p className="text-xs text-gray-500 mb-1">{label}</p>
      <p className="text-xl font-bold text-gray-900">{value}</p>
    </div>
  )
}
