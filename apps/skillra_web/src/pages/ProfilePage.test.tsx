import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import ProfilePage from './ProfilePage'

const mocks = vi.hoisted(() => ({
  useAuth: vi.fn(),
  useProfile: vi.fn(),
  useResumeStatus: vi.fn(),
  useUpdateProfile: vi.fn(),
  useUploadResume: vi.fn(),
  updateMutate: vi.fn(),
  uploadMutate: vi.fn(),
}))

vi.mock('../auth/AuthContext', () => ({
  useAuth: mocks.useAuth,
}))

vi.mock('../components/MetaSelect', () => ({
  default: ({ label, value, onChange }: { label: string; value: string; onChange: (value: string) => void }) => (
    <label>
      {label}
      <input value={value} onChange={(event) => onChange(event.target.value)} />
    </label>
  ),
}))

vi.mock('../hooks/useProfile', () => ({
  useProfile: mocks.useProfile,
  useResumeStatus: mocks.useResumeStatus,
  useUpdateProfile: mocks.useUpdateProfile,
  useUploadResume: mocks.useUploadResume,
}))

describe('ProfilePage', () => {
  beforeEach(() => {
    mocks.useAuth.mockReturnValue({ mode: 'user', telegramUserId: 42 })
    mocks.useProfile.mockReturnValue({
      data: {
        telegram_user_id: 42,
        username: 'alice',
        target_role: 'Data Analyst',
        target_grade: 'Middle',
        target_city_tier: 'Moscow',
        target_country: '',
        target_region: '',
        target_city: '',
        target_geo_scope: '',
        target_work_mode: 'Remote',
        target_domain: '',
        current_skills: ['Python'],
      },
      isLoading: false,
      isError: false,
    })
    mocks.useResumeStatus.mockReturnValue({
      data: { uploaded: false, extracted_skills: [] },
      isLoading: false,
    })
    mocks.useUpdateProfile.mockReturnValue({ mutate: mocks.updateMutate, isPending: false })
    mocks.useUploadResume.mockReturnValue({ mutate: mocks.uploadMutate, isPending: false })
    mocks.updateMutate.mockReset()
    mocks.uploadMutate.mockReset()
    mocks.updateMutate.mockImplementation((_payload, options) => options?.onSuccess?.())
    mocks.uploadMutate.mockImplementation((_file, options) =>
      options?.onSuccess?.({
        uploaded: true,
        s3_key: 'resumes/42.pdf',
        original_filename: 'resume.pdf',
        file_size_bytes: 1024,
        extracted_skills: ['SQL', 'Airflow'],
      }),
    )
  })

  it('uploads resume and merges extracted skills into the profile', async () => {
    render(<ProfilePage />)

    fireEvent.click(screen.getByRole('button', { name: /Навыки/ }))
    await screen.findByDisplayValue('Python')

    const file = new File(['%PDF'], 'resume.pdf', { type: 'application/pdf' })
    fireEvent.change(screen.getByLabelText(/PDF резюме/), { target: { files: [file] } })
    fireEvent.click(screen.getByRole('button', { name: /Загрузить резюме/ }))

    expect(mocks.uploadMutate).toHaveBeenCalledWith(file, expect.any(Object))
    await waitFor(() => {
      expect(mocks.updateMutate).toHaveBeenCalledWith(
        expect.objectContaining({ current_skills: ['Python', 'SQL', 'Airflow'] }),
        expect.any(Object),
      )
    })
    expect(screen.getByText(/Навыки добавлены в профиль/)).toBeInTheDocument()
  })
})
