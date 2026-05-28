import { spawnSync } from 'node:child_process'
import fs from 'node:fs'

const GENERATED_FILES = ['openapi.json', 'src/api/generated.d.ts']

function readGeneratedFiles() {
  return Object.fromEntries(
    GENERATED_FILES.map((filePath) => [
      filePath,
      fs.existsSync(filePath) ? fs.readFileSync(filePath, 'utf8') : null,
    ]),
  )
}

const before = readGeneratedFiles()
const result = spawnSync('npm', ['run', 'generate:api'], {
  stdio: 'inherit',
  shell: process.platform === 'win32',
})

if (result.status !== 0) {
  process.exit(result.status ?? 1)
}

const after = readGeneratedFiles()
const staleFiles = GENERATED_FILES.filter((filePath) => before[filePath] !== after[filePath])

if (staleFiles.length > 0) {
  console.error('Generated API contract files were stale. Regenerated files:')
  for (const filePath of staleFiles) {
    console.error(`- ${filePath}`)
  }
  console.error('Run `npm run generate:api` in apps/skillra_web and commit the result.')
  process.exit(1)
}

console.log('Generated API contract files are up to date.')
