interface TrustLabelsProps {
  trust?: {
    dataset_run_id?: string | null
    generated_at?: string | null
    generated_at_utc?: string | null
    freshness?: string | null
    sample_size?: number | null
    source_row_count?: number | null
    confidence?: string | null
    salary_coverage_share?: number | null
    completeness?: string | number | boolean | null
    warnings?: string[] | null
  } | null
  compact?: boolean
}

export default function TrustLabels({ trust, compact = false }: TrustLabelsProps) {
  if (!trust) return null

  const labels = buildTrustLabels(trust)
  const warnings = Array.isArray(trust.warnings) ? trust.warnings.filter(Boolean) : []

  if (labels.length === 0 && warnings.length === 0) return null

  return (
    <div className="space-y-2">
      {labels.length > 0 && (
        <div className="flex flex-wrap gap-2">
          {labels.map((label) => (
            <span
              key={`${label.label}-${label.value}`}
              className={`inline-flex rounded-full border px-2.5 py-1 text-xs font-medium ${label.className}`}
            >
              {compact ? label.value : `${label.label}: ${label.value}`}
            </span>
          ))}
        </div>
      )}
      {warnings.length > 0 && (
        <div className="space-y-1">
          {warnings.slice(0, 3).map((warning) => (
            <p key={warning} className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
              {warning}
            </p>
          ))}
        </div>
      )}
    </div>
  )
}

function buildTrustLabels(trust: NonNullable<TrustLabelsProps['trust']>) {
  const generatedAt = trust.generated_at_utc ?? trust.generated_at ?? null
  const sampleSize = trust.sample_size ?? trust.source_row_count ?? null
  const confidence = formatConfidence(trust.confidence)
  const salaryCoverage =
    trust.salary_coverage_share != null && Number.isFinite(trust.salary_coverage_share)
      ? `${Math.round(trust.salary_coverage_share * 100)}%`
      : null
  const completeness = formatCompleteness(trust.completeness)

  return [
    trust.dataset_run_id
      ? {
          label: 'Run',
          value: shortenRunId(trust.dataset_run_id),
          className: 'border-slate-200 bg-slate-50 text-slate-700',
        }
      : null,
    generatedAt
      ? {
          label: 'Сгенерировано',
          value: formatDateTime(generatedAt),
          className: 'border-slate-200 bg-slate-50 text-slate-700',
        }
      : null,
    trust.freshness
      ? {
          label: 'Свежесть',
          value: trust.freshness,
          className: 'border-green-200 bg-green-50 text-green-700',
        }
      : null,
    sampleSize != null
      ? {
          label: 'Выборка',
          value: sampleSize.toLocaleString('ru-RU'),
          className: 'border-slate-200 bg-slate-50 text-slate-700',
        }
      : null,
    salaryCoverage
      ? {
          label: 'Покрытие ЗП',
          value: salaryCoverage,
          className: 'border-slate-200 bg-slate-50 text-slate-700',
        }
      : null,
    confidence
      ? {
          label: 'Доверие',
          value: confidence.label,
          className: confidence.className,
        }
      : null,
    completeness
      ? {
          label: 'Полнота',
          value: completeness,
          className: completeness === 'частично' ? 'border-amber-200 bg-amber-50 text-amber-800' : 'border-green-200 bg-green-50 text-green-700',
        }
      : null,
  ].filter((item): item is { label: string; value: string; className: string } => item !== null)
}

function formatConfidence(value?: string | null) {
  switch (value) {
    case 'high':
      return { label: 'высокое', className: 'border-green-200 bg-green-50 text-green-700' }
    case 'medium':
      return { label: 'среднее', className: 'border-amber-200 bg-amber-50 text-amber-800' }
    case 'low':
      return { label: 'низкое', className: 'border-red-200 bg-red-50 text-red-700' }
    default:
      return value ? { label: value, className: 'border-slate-200 bg-slate-50 text-slate-700' } : null
  }
}

function formatCompleteness(value: string | number | boolean | null | undefined): string | null {
  if (value == null) return null
  if (typeof value === 'boolean') return value ? 'полная' : 'частично'
  if (typeof value === 'number') return `${Math.round(value * 100)}%`
  if (value === 'complete') return 'полная'
  if (value === 'partial') return 'частично'
  return value
}

function formatDateTime(value: string): string {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value

  return date.toLocaleDateString('ru-RU', {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
  })
}

function shortenRunId(value: string): string {
  return value.length > 12 ? `${value.slice(0, 8)}...` : value
}
