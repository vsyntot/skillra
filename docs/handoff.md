# Repository Handoff

This repository is prepared as a source handoff. It should contain application
code, infrastructure, tests, env examples and neutral product/technical docs.

## Included

- Product and architecture overview in `README.md` and `docs/`.
- Generated env examples from `infra/env/schema.yml`.
- Docker Compose definitions for local, production and staging.
- Python, API, bot, web and infrastructure tests.
- Small committed sample datasets for local pipeline checks.

## Excluded

- Real `.env*` files.
- Real encrypted or decrypted secret payloads.
- Generated reports and acceptance artifacts.
- Processed runtime data and raw HH run artifacts.
- `node_modules/`, `.venv/`, build outputs and IDE files.
- Internal planning, sprint, backlog and agent workflow notes.

## Pre-Transfer Validation

Run the commands that match the intended handoff depth:

```bash
make env-render-check
make compose-validate
make lint
make all-tests
cd apps/skillra_web && npm ci && npm run typecheck && npm run test && npm run lint && npm run build
```

If any command is not run or fails because of missing local dependencies, record
that explicitly in the transfer note.
