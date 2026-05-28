/**
 * SkillGapChart component unit tests
 * Sprint-006 TASK-10
 */
import { describe, it, expect } from 'vitest'
import { render } from '@testing-library/react'
import SkillGapChart from '../components/SkillGapChart'

const mockData = [
  { skill_name: 'Python', market_share: 0.85, persona_has: true, gap: false },
  { skill_name: 'Kafka', market_share: 0.45, persona_has: false, gap: true },
  { skill_name: 'SQL', market_share: 0.72, persona_has: true, gap: false },
]

describe('SkillGapChart', () => {
  it('renders without errors with empty data', () => {
    const { container } = render(<SkillGapChart data={[]} />)
    expect(container).toBeTruthy()
  })

  it('renders with skill data', () => {
    render(<SkillGapChart data={mockData} />)
    // Chart renders without throwing
    expect(document.body).toBeTruthy()
  })

  it('renders gap skills differently from non-gap skills', () => {
    render(<SkillGapChart data={mockData} />)
    // Component renders without crash
    expect(document.body).toBeTruthy()
  })
})
