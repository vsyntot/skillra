import type { SegmentFilters, UserProfileOut } from '../api/client'

export interface ProfileDefaultFilters {
  role: string
  grade: string
  cityTier: string
  country: string
  region: string
  city: string
  geoScope: string
  workMode: string
  domain: string
  skills: string
}

export function profileToSegmentFilters(profile?: UserProfileOut | null): SegmentFilters {
  return {
    role: profile?.target_role || null,
    grade: profile?.target_grade || null,
    city_tier: profile?.target_city_tier || null,
    country: profile?.target_country || null,
    region: profile?.target_region || null,
    city: profile?.target_city || null,
    geo_scope: profile?.target_geo_scope || null,
    work_mode: profile?.target_work_mode || null,
    domain: profile?.target_domain || null,
  }
}

export function profileToDefaultFilters(profile?: UserProfileOut | null): ProfileDefaultFilters {
  return {
    role: profile?.target_role ?? '',
    grade: profile?.target_grade ?? '',
    cityTier: profile?.target_city_tier ?? '',
    country: profile?.target_country ?? '',
    region: profile?.target_region ?? '',
    city: profile?.target_city ?? '',
    geoScope: profile?.target_geo_scope ?? '',
    workMode: profile?.target_work_mode ?? '',
    domain: profile?.target_domain ?? '',
    skills: profile?.current_skills?.join(', ') ?? '',
  }
}

export function segmentDiffersFromProfile(filters: SegmentFilters, profile?: UserProfileOut | null): boolean {
  if (!profile) return false
  const profileFilters = profileToSegmentFilters(profile)

  return (
    normalize(filters.role) !== normalize(profileFilters.role) ||
    normalize(filters.grade) !== normalize(profileFilters.grade) ||
    normalize(filters.city_tier) !== normalize(profileFilters.city_tier) ||
    normalize(filters.country) !== normalize(profileFilters.country) ||
    normalize(filters.region) !== normalize(profileFilters.region) ||
    normalize(filters.city) !== normalize(profileFilters.city) ||
    normalize(filters.geo_scope) !== normalize(profileFilters.geo_scope) ||
    normalize(filters.work_mode) !== normalize(profileFilters.work_mode) ||
    normalize(filters.domain) !== normalize(profileFilters.domain)
  )
}

export function defaultsDifferFromProfile(filters: ProfileDefaultFilters, profile?: UserProfileOut | null): boolean {
  if (!profile) return false
  const profileFilters = profileToDefaultFilters(profile)

  return (
    normalize(filters.role) !== normalize(profileFilters.role) ||
    normalize(filters.grade) !== normalize(profileFilters.grade) ||
    normalize(filters.cityTier) !== normalize(profileFilters.cityTier) ||
    normalize(filters.country) !== normalize(profileFilters.country) ||
    normalize(filters.region) !== normalize(profileFilters.region) ||
    normalize(filters.city) !== normalize(profileFilters.city) ||
    normalize(filters.geoScope) !== normalize(profileFilters.geoScope) ||
    normalize(filters.workMode) !== normalize(profileFilters.workMode) ||
    normalize(filters.domain) !== normalize(profileFilters.domain) ||
    normalizeSkillList(filters.skills) !== normalizeSkillList(profileFilters.skills)
  )
}

function normalize(value: string | null | undefined): string {
  return (value ?? '').trim().toLowerCase()
}

function normalizeSkillList(value: string): string {
  return value
    .split(',')
    .map((skill) => normalize(skill))
    .filter(Boolean)
    .sort()
    .join(',')
}
