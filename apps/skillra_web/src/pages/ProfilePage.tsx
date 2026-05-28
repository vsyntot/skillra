import { useEffect, useState } from 'react'
import { useAuth } from '../auth/AuthContext'
import MetaSelect from '../components/MetaSelect'
import { useProfile, useResumeStatus, useUpdateProfile, useUploadResume } from '../hooks/useProfile'

const MAX_RESUME_BYTES = 10 * 1024 * 1024
const PROFILE_STEPS = ['Цель', 'География', 'Навыки', 'Проверка'] as const

function splitSkills(value: string): string[] {
  return value
    .split(',')
    .map((skill) => skill.trim())
    .filter(Boolean)
}

function mergeSkills(existing: string[], extracted: string[]): string[] {
  const seen = new Set<string>()
  const merged: string[] = []

  for (const skill of [...existing, ...extracted]) {
    const normalized = skill.trim()
    const key = normalized.toLowerCase()
    if (!normalized || seen.has(key)) continue
    seen.add(key)
    merged.push(normalized)
  }

  return merged
}

function isPdfResume(file: File): boolean {
  return file.type === 'application/pdf' || file.name.toLowerCase().endsWith('.pdf')
}

export default function ProfilePage() {
  const { mode, telegramUserId } = useAuth()
  const [serviceUserId, setServiceUserId] = useState<number>(0)
  const [inputId, setInputId] = useState('')
  const [saved, setSaved] = useState(false)
  const [activeStep, setActiveStep] = useState(0)
  const effectiveUserId = mode === 'user' ? telegramUserId ?? 0 : serviceUserId

  const { data: profile, isLoading, isError } = useProfile(effectiveUserId)
  const resumeQuery = useResumeStatus(effectiveUserId)
  const updateMutation = useUpdateProfile(effectiveUserId)
  const uploadResumeMutation = useUploadResume(effectiveUserId)
  const [resumeFile, setResumeFile] = useState<File | null>(null)
  const [resumeMessage, setResumeMessage] = useState('')
  const [resumeError, setResumeError] = useState('')

  const [form, setForm] = useState({
    username: '',
    target_role: '',
    target_grade: '',
    target_city_tier: '',
    target_country: '',
    target_region: '',
    target_city: '',
    target_geo_scope: '',
    target_work_mode: '',
    target_domain: '',
    current_skills: '',
  })
  const stepStatus = [
    Boolean(form.target_role && form.target_grade && form.target_domain),
    Boolean((form.target_city_tier || form.target_country || form.target_region || form.target_city) && form.target_work_mode),
    Boolean(splitSkills(form.current_skills).length > 0 || resumeQuery.data?.uploaded),
    true,
  ]

  useEffect(() => {
    if (!profile) return
    setForm({
      username: profile.username ?? '',
      target_role: profile.target_role ?? '',
      target_grade: profile.target_grade ?? '',
      target_city_tier: profile.target_city_tier ?? '',
      target_country: profile.target_country ?? '',
      target_region: profile.target_region ?? '',
      target_city: profile.target_city ?? '',
      target_geo_scope: profile.target_geo_scope ?? '',
      target_work_mode: profile.target_work_mode ?? '',
      target_domain: profile.target_domain ?? '',
      current_skills: profile.current_skills.join(', '),
    })
  }, [profile])

  const handleLoad = () => {
    const id = parseInt(inputId, 10)
    if (!isNaN(id) && id > 0) {
      setServiceUserId(id)
      setSaved(false)
      setResumeMessage('')
      setResumeError('')
    }
  }

  const buildProfilePayload = (skills?: string[]) => ({
    username: form.username || null,
    target_role: form.target_role || null,
    target_grade: form.target_grade || null,
    target_city_tier: form.target_city_tier || null,
    target_country: form.target_country || null,
    target_region: form.target_region || null,
    target_city: form.target_city || null,
    target_geo_scope: form.target_geo_scope || null,
    target_work_mode: form.target_work_mode || null,
    target_domain: form.target_domain || null,
    current_skills: skills ?? splitSkills(form.current_skills),
  })

  const handleSave = () => {
    if (effectiveUserId <= 0) return

    updateMutation.mutate(
      buildProfilePayload(),
      {
        onSuccess: () => setSaved(true),
      },
    )
  }

  const handleResumeUpload = () => {
    if (effectiveUserId <= 0 || !resumeFile) return

    setResumeMessage('')
    setResumeError('')

    if (!isPdfResume(resumeFile)) {
      setResumeError('Поддерживается только PDF.')
      return
    }
    if (resumeFile.size > MAX_RESUME_BYTES) {
      setResumeError('PDF должен быть до 10 МБ.')
      return
    }

    uploadResumeMutation.mutate(resumeFile, {
      onSuccess: (result) => {
        const extracted = result.extracted_skills ?? []
        if (extracted.length === 0) {
          setResumeMessage('Резюме загружено, но навыки пока не найдены.')
          return
        }

        const mergedSkills = mergeSkills(splitSkills(form.current_skills), extracted)
        setForm((current) => ({ ...current, current_skills: mergedSkills.join(', ') }))
        updateMutation.mutate(buildProfilePayload(mergedSkills), {
          onSuccess: () => {
            setSaved(true)
            setResumeMessage(`Резюме загружено. Навыки добавлены в профиль: ${extracted.slice(0, 5).join(', ')}`)
          },
          onError: () => {
            setResumeError('Резюме загружено, но профиль не обновился. Сохраните навыки вручную.')
          },
        })
      },
      onError: () => {
        setResumeError('Не удалось загрузить резюме. Попробуйте позже.')
      },
    })
  }

  return (
    <div className="max-w-2xl mx-auto p-6">
      <h1 className="text-2xl font-bold text-gray-900 mb-6">Профиль пользователя</h1>

      {mode !== 'user' && (
        <div className="mb-6 rounded-lg border border-amber-200 bg-amber-50 p-4">
          <p className="mb-3 text-sm text-amber-800">
            Командный режим проверки. В публичном сценарии пользователь входит личным ключом и не вводит этот ID вручную.
          </p>
          <div className="flex gap-3">
          <input
            type="number"
            value={inputId}
            onChange={(e) => setInputId(e.target.value)}
            placeholder="ID пользователя"
            className="flex-1 border border-gray-300 rounded-lg px-3 py-2 text-sm"
          />
          <button
            onClick={handleLoad}
            className="bg-blue-600 text-white rounded-lg px-4 py-2 text-sm font-medium hover:bg-blue-700"
          >
            Загрузить
          </button>
          </div>
        </div>
      )}

      {isLoading && <p className="text-gray-500 text-sm">Загрузка...</p>}
      {isError && effectiveUserId > 0 && (
        <p className="text-amber-700 text-sm bg-amber-50 rounded-lg px-3 py-2 mb-4">
          Профиль не найден. Заполните форму и сохраните новый профиль.
        </p>
      )}
      {effectiveUserId <= 0 && (
        <p className="text-gray-500 text-sm bg-white rounded-lg border border-gray-200 px-3 py-2">
          {mode === 'user' ? 'Не удалось определить пользователя по сессии.' : 'Укажите ID пользователя.'}
        </p>
      )}

      {effectiveUserId > 0 && (
        <div className="space-y-4">
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
            {PROFILE_STEPS.map((step, index) => (
              <button
                key={step}
                type="button"
                onClick={() => setActiveStep(index)}
                className={`rounded-lg border px-3 py-2 text-left text-sm ${
                  activeStep === index
                    ? 'border-blue-500 bg-blue-50 text-blue-800'
                    : 'border-gray-200 bg-white text-gray-600 hover:border-blue-200'
                }`}
              >
                <span className="block text-xs font-medium">{index + 1}. {step}</span>
                <span className="text-xs">{stepStatus[index] ? 'Готово' : 'Нужно заполнить'}</span>
              </button>
            ))}
          </div>

          <div className="bg-gray-50 rounded-lg p-4 text-sm text-gray-600 space-y-1">
            <p>
              <strong>ID пользователя:</strong> {profile?.telegram_user_id ?? effectiveUserId}
            </p>
            {profile?.username && (
              <p>
                <strong>Ник:</strong> @{profile.username}
              </p>
            )}
            {profile?.created_at && (
              <p>
                <strong>Создан:</strong> {new Date(profile.created_at).toLocaleString('ru-RU')}
              </p>
            )}
            {profile?.updated_at && (
              <p>
                <strong>Обновлён:</strong> {new Date(profile.updated_at).toLocaleString('ru-RU')}
              </p>
            )}
          </div>

          {activeStep === 0 && (
            <section className="rounded-lg border border-gray-200 bg-white p-4 space-y-4">
              <h2 className="text-base font-semibold text-gray-900">Цель</h2>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Ник</label>
                <input
                  type="text"
                  value={form.username}
                  onChange={(e) => setForm((f) => ({ ...f, username: e.target.value }))}
                  className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm"
                />
              </div>

              <MetaSelect
                kind="roles"
                label="Целевая роль"
                value={form.target_role}
                onChange={(value) => setForm((f) => ({ ...f, target_role: value }))}
              />
              <MetaSelect
                kind="grades"
                label="Грейд"
                value={form.target_grade}
                onChange={(value) => setForm((f) => ({ ...f, target_grade: value }))}
              />
              <MetaSelect
                kind="domains"
                label="Домен"
                value={form.target_domain}
                onChange={(value) => setForm((f) => ({ ...f, target_domain: value }))}
              />
            </section>
          )}

          {activeStep === 1 && (
            <section className="rounded-lg border border-gray-200 bg-white p-4 space-y-4">
              <h2 className="text-base font-semibold text-gray-900">География и формат</h2>
              <MetaSelect
                kind="cityTiers"
                label="Уровень города"
                value={form.target_city_tier}
                onChange={(value) => setForm((f) => ({ ...f, target_city_tier: value }))}
              />
              <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                <MetaSelect
                  kind="countries"
                  label="Страна"
                  value={form.target_country}
                  onChange={(value) => setForm((f) => ({ ...f, target_country: value }))}
                />
                <MetaSelect
                  kind="regions"
                  label="Регион"
                  value={form.target_region}
                  onChange={(value) => setForm((f) => ({ ...f, target_region: value }))}
                />
                <MetaSelect
                  kind="cities"
                  label="Город"
                  value={form.target_city}
                  onChange={(value) => setForm((f) => ({ ...f, target_city: value }))}
                />
                <MetaSelect
                  kind="geoScopes"
                  label="Рынок"
                  value={form.target_geo_scope}
                  onChange={(value) => setForm((f) => ({ ...f, target_geo_scope: value }))}
                />
              </div>
              <MetaSelect
                kind="workModes"
                label="Режим работы"
                value={form.target_work_mode}
                onChange={(value) => setForm((f) => ({ ...f, target_work_mode: value }))}
              />
            </section>
          )}

          {activeStep === 2 && (
            <section className="rounded-lg border border-gray-200 bg-white p-4 space-y-4">
              <div>
                <h2 className="text-base font-semibold text-gray-900">Навыки и резюме</h2>
                <p className="text-sm text-gray-500">
                  PDF до 10 МБ. Извлечённые навыки автоматически добавятся в профиль.
                </p>
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  Навыки через запятую
                </label>
                <input
                  type="text"
                  value={form.current_skills}
                  onChange={(e) => setForm((f) => ({ ...f, current_skills: e.target.value }))}
                  className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm"
                />
              </div>

              {resumeQuery.isLoading ? (
                <p className="text-sm text-gray-500">Проверяем статус резюме...</p>
              ) : resumeQuery.data?.uploaded ? (
                <div className="rounded-lg bg-gray-50 px-3 py-2 text-sm text-gray-600">
                  <p>
                    <strong>Файл:</strong> {resumeQuery.data.original_filename ?? 'resume.pdf'}
                  </p>
                  {resumeQuery.data.extracted_skills.length > 0 && (
                    <p>
                      <strong>Навыки:</strong> {resumeQuery.data.extracted_skills.slice(0, 8).join(', ')}
                    </p>
                  )}
                </div>
              ) : (
                <p className="rounded-lg bg-gray-50 px-3 py-2 text-sm text-gray-600">Резюме ещё не загружено.</p>
              )}

              <label className="block text-sm font-medium text-gray-700">
                PDF резюме
                <input
                  type="file"
                  accept="application/pdf,.pdf"
                  onChange={(event) => {
                    setResumeFile(event.target.files?.[0] ?? null)
                    setResumeMessage('')
                    setResumeError('')
                  }}
                  className="mt-1 block w-full text-sm text-gray-700 file:mr-3 file:rounded-lg file:border-0 file:bg-gray-100 file:px-3 file:py-2 file:text-sm file:font-medium file:text-gray-700 hover:file:bg-gray-200"
                />
              </label>

              {resumeMessage && (
                <p className="rounded-lg bg-green-50 px-3 py-2 text-sm text-green-700">{resumeMessage}</p>
              )}
              {resumeError && (
                <p className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{resumeError}</p>
              )}

              <button
                type="button"
                onClick={handleResumeUpload}
                disabled={!resumeFile || uploadResumeMutation.isPending || effectiveUserId <= 0}
                className="rounded-lg bg-gray-900 px-4 py-2 text-sm font-medium text-white hover:bg-gray-800 disabled:opacity-50"
              >
                {uploadResumeMutation.isPending ? 'Загрузка...' : 'Загрузить резюме'}
              </button>
            </section>
          )}

          {activeStep === 3 && (
            <section className="rounded-lg border border-gray-200 bg-white p-4 space-y-3">
              <h2 className="text-base font-semibold text-gray-900">Проверка</h2>
              <dl className="grid grid-cols-1 gap-3 text-sm sm:grid-cols-2">
                <div>
                  <dt className="text-gray-500">Роль</dt>
                  <dd className="font-medium text-gray-900">{form.target_role || 'Не указана'}</dd>
                </div>
                <div>
                  <dt className="text-gray-500">Грейд</dt>
                  <dd className="font-medium text-gray-900">{form.target_grade || 'Не указан'}</dd>
                </div>
                <div>
                  <dt className="text-gray-500">География</dt>
                  <dd className="font-medium text-gray-900">
                    {[form.target_country, form.target_region, form.target_city, form.target_geo_scope].filter(Boolean).join(' · ') || 'Не указана'}
                  </dd>
                </div>
                <div>
                  <dt className="text-gray-500">Навыки</dt>
                  <dd className="font-medium text-gray-900">{splitSkills(form.current_skills).length}</dd>
                </div>
              </dl>
            </section>
          )}

          {saved && (
            <p className="text-green-600 text-sm bg-green-50 rounded-lg px-3 py-2">
              Профиль успешно сохранён
            </p>
          )}

          <div className="flex items-center justify-between gap-3">
            <button
              type="button"
              onClick={() => setActiveStep((step) => Math.max(0, step - 1))}
              disabled={activeStep === 0}
              className="rounded-lg border border-gray-300 px-4 py-2 text-sm font-medium text-gray-700 hover:border-blue-300 disabled:opacity-50"
            >
              Назад
            </button>
            <button
              type="button"
              onClick={() => setActiveStep((step) => Math.min(PROFILE_STEPS.length - 1, step + 1))}
              disabled={activeStep === PROFILE_STEPS.length - 1}
              className="rounded-lg border border-gray-300 px-4 py-2 text-sm font-medium text-gray-700 hover:border-blue-300 disabled:opacity-50"
            >
              Далее
            </button>
          </div>

          <button
            onClick={handleSave}
            disabled={updateMutation.isPending || effectiveUserId <= 0}
            className="w-full bg-blue-600 text-white rounded-lg px-4 py-2 text-sm font-medium hover:bg-blue-700 disabled:opacity-50"
          >
            {updateMutation.isPending ? 'Сохранение...' : 'Сохранить'}
          </button>
        </div>
      )}
    </div>
  )
}
