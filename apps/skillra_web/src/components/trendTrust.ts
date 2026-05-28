interface TrendLike {
  claim_status?: string | null
  warnings?: string[] | null
}

export function trendBlockedMessage(payload: TrendLike | null | undefined): string | null {
  if (payload?.claim_status !== 'blocked') return null
  return (
    payload.warnings?.[0] ||
    'Историческая динамика сейчас заблокирована: нужен trend-ready датасет с подтвержденными датами публикации, достаточным числом периодов, покрытием сегментов и проверенным source capability.'
  )
}
