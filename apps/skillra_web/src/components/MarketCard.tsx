/**
 * MarketCard — displays segment summary metrics with salary chart.
 * Sprint-006 TASK-09 + Sprint-008 TASK-09 (SalaryDistributionChart integration)
 */
import type { SegmentSummary } from '../api/client'
import SalaryDistributionChart from './SalaryDistributionChart'

interface MarketCardProps {
  summary: SegmentSummary
}

export default function MarketCard({ summary }: MarketCardProps) {
  const hasSmallSampleWarning = summary.min_market_n != null && summary.vacancy_count < summary.min_market_n
  const confidenceLabel = formatConfidence(summary.confidence)
  const salaryCoverage =
    summary.salary_coverage_share != null ? `${Math.round(summary.salary_coverage_share * 100)}%` : null
  const salarySample =
    summary.salary_sample_size != null
      ? `${summary.salary_sample_size.toLocaleString('ru-RU')}/${(summary.sample_size ?? summary.vacancy_count).toLocaleString('ru-RU')}`
      : null

  return (
    <div className="bg-white rounded-2xl border border-gray-200 shadow-sm p-6 space-y-4">
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-3">
        <Metric label="Вакансий" value={summary.vacancy_count.toLocaleString('ru-RU')} />
        {summary.salary_median != null && (
          <Metric label="Медиана ЗП" value={`${Math.round(summary.salary_median / 1000)}k ₽`} />
        )}
        {summary.remote_share != null && (
          <Metric label="Удалённо" value={`${Math.round(summary.remote_share * 100)}%`} />
        )}
        {summary.geo_scope && <Metric label="Рынок" value={formatGeoScope(summary.geo_scope)} />}
        {summary.junior_friendly_share != null && (
          <Metric label="Junior friendly" value={`${Math.round(summary.junior_friendly_share * 100)}%`} />
        )}
        {salaryCoverage && <Metric label="Покрытие ЗП" value={salaryCoverage} />}
        {confidenceLabel && <Metric label="Доверие" value={confidenceLabel} />}
      </div>

      {(salarySample || confidenceLabel) && (
        <div className="flex flex-wrap gap-2 text-xs text-gray-600">
          {salarySample && <span>Зарплатная выборка: {salarySample}</span>}
          {confidenceLabel && <span>Уверенность: {confidenceLabel}</span>}
        </div>
      )}

      {hasSmallSampleWarning && (
        <div className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
          Сегмент меньше минимального порога: {summary.vacancy_count.toLocaleString('ru-RU')} из{' '}
          {summary.min_market_n?.toLocaleString('ru-RU')} вакансий. Расширьте фильтры для более стабильной оценки.
        </div>
      )}

      {(summary.salary_q25 != null || summary.salary_median != null || summary.salary_q75 != null) && (
        <SalaryDistributionChart
          salary_q25={summary.salary_q25 ?? null}
          salary_median={summary.salary_median ?? null}
          salary_q75={summary.salary_q75 ?? null}
        />
      )}

      {summary.top_skills && summary.top_skills.length > 0 && (
        <div>
          <p className="text-sm font-medium text-gray-700 mb-2">Топ навыки</p>
          <div className="flex flex-wrap gap-2">
            {summary.top_skills.slice(0, 10).map((skill) => (
              <span
                key={skill}
                className="bg-blue-50 text-blue-700 text-xs rounded-full px-2 py-0.5 border border-blue-100"
              >
                {skill}
              </span>
            ))}
          </div>
        </div>
      )}

      {summary.warnings.length > 0 && (
        <div className="space-y-1">
          {summary.warnings.map((w, i) => (
            <p key={i} className="text-xs text-yellow-700 bg-yellow-50 rounded px-2 py-1">
              ⚠️ {w}
            </p>
          ))}
        </div>
      )}
    </div>
  )
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="bg-gray-50 rounded-xl p-3">
      <p className="text-xs text-gray-500 mb-1">{label}</p>
      <p className="text-lg font-semibold text-gray-900">{value}</p>
    </div>
  )
}

function formatConfidence(confidence?: string | null) {
  if (confidence === 'high') return 'Высокое'
  if (confidence === 'medium') return 'Среднее'
  if (confidence === 'low') return 'Низкое'
  return null
}

function formatGeoScope(scope: string) {
  if (scope === 'remote') return 'Remote'
  if (scope === 'local') return 'Local'
  if (scope === 'mixed') return 'Mixed'
  return scope
}
