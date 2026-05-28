import { describe, expect, it } from 'vitest'
import { resolveEvidenceExplainerEnabled } from './featureFlags'

describe('resolveEvidenceExplainerEnabled', () => {
  it('enables the evidence explainer only for explicit local opt-in', () => {
    expect(
      resolveEvidenceExplainerEnabled({
        MODE: 'development',
        PROD: false,
        VITE_SKILLRA_RUNTIME_ENV: 'local',
        VITE_ENABLE_EVIDENCE_EXPLAINER: '1',
      }),
    ).toBe(true)
  })

  it('requires allowlisted user ids for staging enablement', () => {
    expect(
      resolveEvidenceExplainerEnabled({
        MODE: 'development',
        PROD: false,
        VITE_SKILLRA_RUNTIME_ENV: 'staging',
        VITE_ENABLE_EVIDENCE_EXPLAINER: '1',
      }),
    ).toBe(false)
    expect(
      resolveEvidenceExplainerEnabled(
        {
          MODE: 'development',
          PROD: false,
          VITE_SKILLRA_RUNTIME_ENV: 'staging',
          VITE_ENABLE_EVIDENCE_EXPLAINER: '1',
          VITE_EVIDENCE_EXPLAINER_ALLOWED_TELEGRAM_USER_IDS: '42, 43',
        },
        42,
      ),
    ).toBe(true)
    expect(
      resolveEvidenceExplainerEnabled(
        {
          MODE: 'development',
          PROD: false,
          VITE_SKILLRA_RUNTIME_ENV: 'staging',
          VITE_ENABLE_EVIDENCE_EXPLAINER: '1',
          VITE_EVIDENCE_EXPLAINER_ALLOWED_TELEGRAM_USER_IDS: '42, 43',
        },
        44,
      ),
    ).toBe(false)
  })

  it('stays disabled by default and in production builds', () => {
    expect(resolveEvidenceExplainerEnabled({ MODE: 'development', PROD: false })).toBe(false)
    expect(
      resolveEvidenceExplainerEnabled({
        MODE: 'production',
        PROD: true,
        VITE_SKILLRA_RUNTIME_ENV: 'prod',
        VITE_ENABLE_EVIDENCE_EXPLAINER: '1',
      }),
    ).toBe(false)
  })
})
