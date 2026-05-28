import { useId } from 'react'
import { useMeta, type MetaKind } from '../hooks/useMeta'

interface MetaSelectProps {
  kind: MetaKind
  label: string
  value: string
  onChange: (value: string) => void
  placeholder?: string
  className?: string
  allowEmpty?: boolean
}

export default function MetaSelect({
  kind,
  label,
  value,
  onChange,
  placeholder = 'Не выбрано',
  className = '',
  allowEmpty = true,
}: MetaSelectProps) {
  const id = useId()
  const { data: options = [], isLoading, isError } = useMeta(kind)

  return (
    <div className={className}>
      <label htmlFor={id} className="block text-sm font-medium text-gray-700 mb-1">
        {label}
      </label>
      <select
        id={id}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        disabled={isLoading}
        className="w-full border border-gray-300 rounded-lg bg-white px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:bg-gray-50 disabled:text-gray-400"
      >
        {allowEmpty && <option value="">{isLoading ? 'Загрузка...' : placeholder}</option>}
        {!allowEmpty && isLoading && <option value="">Загрузка...</option>}
        {options.map((option) => (
          <option key={option} value={option}>
            {option}
          </option>
        ))}
        {value && !options.includes(value) && (
          <option value={value}>
            {value}
          </option>
        )}
      </select>
      {isError && <p className="mt-1 text-xs text-amber-600">Справочник недоступен</p>}
    </div>
  )
}
