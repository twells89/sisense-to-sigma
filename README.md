> [!IMPORTANT]
> **This repository has moved and is no longer maintained here.**
> The `sisense-to-sigma` skill now lives in the consolidated monorepo:
> **https://github.com/twells89/sigma-migration-skills** → `plugins/sisense-to-sigma/`
> This standalone repo is archived (read-only) and kept for reference only.

# sisense-to-sigma

Claude Code plugin for migrating **Sisense** (ElastiCube / Live data models +
dashboards) to **Sigma**, in the same format and phase structure as the
[sigma-migration-skills](https://github.com/twells89/sigma-migration-skills)
converters (Tableau, Power BI, Qlik, ThoughtSpot, QuickSight, Cognos,
MicroStrategy, SSRS).

## Status: scaffold — live auth + discovery wired, converter in progress

Unlike SSRS, **Sisense exposes a full REST API**, so this skill pulls the source
content live rather than relying on a customer-side export.

What works today (validated against a live trial instance,
`signup-jnzavd0c.sisense.com`, 2026-06-17):

- **Auth** — `scripts/sisense-auth.sh` exchanges email+password at
  `POST /api/v1/authentication/login` for a bearer token.
- **Discovery** — `scripts/discover.py` lists ElastiCubes
  (`GET /api/v1/elasticubes/getElasticubes`), exports each data model's full
  schema (`GET /api/v2/datamodels/schema?title=…` — datasets/tables/columns,
  `relations` joins, `modelingTransformations` calc columns), and lists
  dashboards + widgets (`GET /api/v1/dashboards`).

What is **not** done yet:

- `convert.py` (model + dashboard → Sigma DM + workbook specs)
- `jaql_expr.py` (JAQL formula → Sigma formula translation)
- `verify_parity.py` (JAQL-vs-Sigma data parity)
- `scan_gaps.py` / assessment coverage scoring
- A bundled fixture + a live parity run. The trial instance currently has
  **4 sample ElastiCubes** (Healthcare, Retail, ECommerce, Lead Generation) and
  **0 dashboards** — a sample dashboard must be built before an end-to-end
  parity gate can run.

**Don't claim parity until `verify_parity.py` is GREEN** against numbers taken
from Sisense JAQL itself. See `skills/sisense-to-sigma/refs/design-notes.md`.

## Layout

```
skills/
  sisense-to-sigma/      converter skill (discovery → DM + workbook → parity)
  sisense-assessment/    read-only estate inventory + converter-coverage scoring
```

## Credentials

Store Sisense creds in the agent-neutral file `~/.sigma-migration/sisense.env`:

```sh
export SISENSE_BASE_URL=https://<your-instance>.sisense.com
export SISENSE_API_TOKEN=<bearer token from sisense-auth.sh>
```

Sigma side reuses the shared `~/.sigma-migration/env`
(`SIGMA_CLIENT_ID` / `SIGMA_CLIENT_SECRET` / `SIGMA_BASE_URL`) via
`scripts/get-token.sh`, exactly like the sibling converters.
