import type { CommercialStateOut } from '../api/client'

export const PREMIUM_FEATURE_LABELS: Record<string, string> = {
  'career_plan.generate_actions': 'Рекомендации из skill gap',
  'skill_gap.export': 'Экспорт skill gap',
  'trends.advanced': 'Расширенные тренды',
}

export const PLAN_LABELS: Record<string, string> = {
  free: 'Free',
  trial: 'Trial',
  pro: 'Pro',
  admin: 'Admin',
}

export const SUBSCRIPTION_STATE_LABELS: Record<string, string> = {
  none: 'нет платной подписки',
  trialing: 'пробный период',
  active: 'активен',
  cancel_at_period_end: 'отменится в конце периода',
  expired: 'истёк',
  refunded: 'возврат оформлен',
  payment_failed: 'платёж не прошёл',
  provider_unavailable: 'платёжный провайдер недоступен',
  past_due: 'платёж не прошёл',
  cancelled: 'отменён',
}

export function hasEntitlement(state: CommercialStateOut | undefined, entitlement: string): boolean {
  if (!state) return false
  return state.entitlements.includes('*') || state.entitlements.includes(entitlement)
}

export function lockedFeatureText(feature: string): string {
  return PREMIUM_FEATURE_LABELS[feature] ?? feature
}

export function commercialLockedMessage(feature: string): string {
  return `${lockedFeatureText(feature)} доступно в Trial или Pro. Проверьте тариф в Аккаунте.`
}
