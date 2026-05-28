const PROTECTED_RUNTIME_ENVS = new Set(['prod', 'production'])
const ALLOWLIST_REQUIRED_RUNTIME_ENVS = new Set(['staging'])

interface FeatureFlagEnv {
  MODE?: string
  PROD?: boolean
  VITE_SKILLRA_RUNTIME_ENV?: string
  VITE_ENABLE_EVIDENCE_EXPLAINER?: string
  VITE_EVIDENCE_EXPLAINER_ALLOWED_TELEGRAM_USER_IDS?: string
}

function parseAllowedIds(value?: string): Set<number> {
  return new Set(
    String(value ?? '')
      .split(',')
      .map((item) => Number(item.trim()))
      .filter((item) => Number.isInteger(item) && item > 0),
  )
}

export function resolveEvidenceExplainerEnabled(env: FeatureFlagEnv, telegramUserId?: number): boolean {
  const runtimeEnv = String(env.VITE_SKILLRA_RUNTIME_ENV ?? env.MODE ?? '').toLowerCase()
  if (env.PROD || PROTECTED_RUNTIME_ENVS.has(runtimeEnv)) {
    return false
  }
  if (env.VITE_ENABLE_EVIDENCE_EXPLAINER !== '1') {
    return false
  }
  const allowedIds = parseAllowedIds(env.VITE_EVIDENCE_EXPLAINER_ALLOWED_TELEGRAM_USER_IDS)
  if (ALLOWLIST_REQUIRED_RUNTIME_ENVS.has(runtimeEnv) && allowedIds.size === 0) {
    return false
  }
  if (allowedIds.size > 0 && !allowedIds.has(Number(telegramUserId))) {
    return false
  }
  return true
}
