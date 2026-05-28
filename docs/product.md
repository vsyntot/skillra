# Skillra Product Overview

Skillra is a career and job market navigator for IT and data specialists. It
combines vacancy-market analytics with a user profile, skill-gap analysis,
vacancy evidence, career planning and weekly reminders.

## Target Users

- Junior and early-middle IT/data specialists who need a practical route to the
  next role.
- Career switchers who need to understand market expectations before choosing
  courses or applying to vacancies.
- Career centers, bootcamps and teams that need aggregate cohort analytics
  without exposing individual user details.

## Core User Journey

1. User enters through Telegram or the web app.
2. User creates a profile: target role, grade, geography, work mode, domain and
   current skills.
3. Skillra shows market context for the selected segment: demand, salary ranges,
   top skills and data confidence.
4. Skillra calculates the user's skill gap and recommends a short list of skills
   to prioritize.
5. User searches vacancies and saves relevant ones into a career plan.
6. User turns recommendations into actions and tracks progress.
7. Weekly Telegram digest brings the user back with market updates, actions and
   vacancy evidence.

## Product Modules

### Profile

The profile is the personalization anchor. It stores target role, grade,
geography, work mode, domain and current skills. Web and bot both read and write
the same API model.

### Market View

Market view is generated from processed HH vacancy features. It includes:

- total vacancy count and salary-disclosed vacancy count;
- salary median, p25 and p75;
- remote and junior-friendly shares;
- top demanded skills;
- sample-size and salary-coverage based confidence;
- freshness and lineage metadata from the active dataset.

### Skill Gap

Skill-gap analysis compares the user's current skills with skills demanded in
the selected target market. The API returns demanded skills, gap flags,
recommendations, market summary and warnings. Web supports CSV/PDF export and
public share links.

### Vacancy Search

Vacancy search uses MeiliSearch as the primary engine and Postgres as fallback.
Results include vacancy metadata, skills, matched/missing skills and fit signals
for the user's profile.

### Career Plan

Career plan stores the user's target state and action list. Actions can be
manual or generated from skill-gap evidence. Saved vacancies and application
outcomes connect market evidence with actual progress.

### Trends

Trend endpoints use weekly market snapshots and return salary, vacancy count,
skill-demand and career-transition series. Trend claims are gated by data
quality and history depth so the product can avoid overclaiming on thin data.

### Digest

Weekly digest subscriptions store weekday, local time and timezone. The digest
worker claims due subscriptions from the API, sends text and chart attachments
through Telegram, then acknowledges delivery and writes history.

### Organizations

Organizations support B2B workflows: organizations, members, cohorts, invites
and aggregate cohort analytics. Minimum cohort and cell sizes protect against
overexposing individual users.

## Trust And Privacy Characteristics

- User-facing analytics include sample size, freshness, confidence and warnings.
- Service tokens and admin tokens are separate.
- Web users can authenticate with per-user API keys.
- Resume uploads are stored in MinIO/S3 buckets configured for private access.
- Account deletion removes profile-owned data through API-controlled cascades.
- B2B cohort analytics use minimum-N controls.

## Current Product Boundaries

- Runtime API and pipeline read local mounted parquet/CSV files. MinIO/S3 is
  used for archive, sync and restore, not as the live serving source.
- Public trend claims depend on sufficient complete weekly snapshots.
- Payment provider integration is controlled by feature flags and launch gates.
- Evidence explainer functionality is feature-flagged and disabled by default.
