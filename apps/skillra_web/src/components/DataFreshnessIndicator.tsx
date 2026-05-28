import { useDatasetMeta } from '../hooks/useDataset'

interface DataFreshnessIndicatorProps {
  className?: string
}

function formatDatasetDate(value: string): string {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value

  return date
    .toLocaleDateString('ru-RU', {
      day: 'numeric',
      month: 'long',
      year: 'numeric',
    })
    .replace(/\sг\.$/, '')
}

function pluralDays(days: number): string {
  const mod10 = days % 10
  const mod100 = days % 100

  if (mod10 === 1 && mod100 !== 11) return 'день'
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)) return 'дня'
  return 'дней'
}

function getFreshnessState(lastUpdated: string) {
  const updatedAt = new Date(lastUpdated)
  if (Number.isNaN(updatedAt.getTime())) {
    return {
      label: `Данные актуальны по ${lastUpdated}`,
      toneClass: 'border-gray-200 bg-gray-50 text-gray-600',
    }
  }

  const daysOld = Math.max(0, Math.floor((Date.now() - updatedAt.getTime()) / 86_400_000))
  const toneClass =
    daysOld < 7
      ? 'border-green-200 bg-green-50 text-green-700'
      : daysOld <= 30
        ? 'border-amber-200 bg-amber-50 text-amber-700'
        : 'border-red-200 bg-red-50 text-red-700'

  return {
    label:
      daysOld < 7
        ? `Данные актуальны по ${formatDatasetDate(lastUpdated)}`
        : `Обновлено ${daysOld} ${pluralDays(daysOld)} назад`,
    toneClass,
  }
}

export default function DataFreshnessIndicator({ className = '' }: DataFreshnessIndicatorProps): JSX.Element {
  const { data, isError, isLoading } = useDatasetMeta()

  if (isLoading) {
    return (
      <span className={`inline-flex rounded-full border border-gray-200 bg-gray-50 px-3 py-1 text-xs text-gray-500 ${className}`}>
        Проверяем свежесть данных...
      </span>
    )
  }

  if (isError || !data?.last_updated) {
    return (
      <span className={`inline-flex rounded-full border border-gray-200 bg-gray-50 px-3 py-1 text-xs text-gray-500 ${className}`}>
        Свежесть данных недоступна
      </span>
    )
  }

  const freshness = getFreshnessState(data.last_updated)
  const recordsLabel = data.records_count > 0 ? ` · ${data.records_count.toLocaleString('ru-RU')} записей` : ''

  return (
    <span className={`inline-flex rounded-full border px-3 py-1 text-xs font-medium ${freshness.toneClass} ${className}`}>
      {freshness.label}
      {recordsLabel}
    </span>
  )
}
