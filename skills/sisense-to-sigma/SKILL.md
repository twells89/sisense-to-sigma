---
name: sisense-to-sigma
description: >-
  Migrate Sisense to Sigma. Use when the user has a Sisense instance —
  ElastiCube or Live data models and dashboards — and wants to recreate them in
  Sigma. Pulls the source live over the Sisense REST API (data model schema
  export + dashboards/widgets), converts the model to a Sigma data model and the
  dashboards to a Sigma workbook (pivot2→pivot-table, indicator→KPI,
  chart/*→chart, filters→controls), translates JAQL formulas to Sigma formulas,
  and verifies data parity by running JAQL against Sisense and comparing to the
  Sigma query. For a full migration it lands the source data in Snowflake so
  both tools read the same warehouse. Translates what maps cleanly and flags
  what doesn't (custom JAQL, BloX/plugin widgets, scripted dashboards) instead
  of emitting wrong logic.
user-invocable: true
---

# Sisense → Sigma migration

Convert a **Sisense** data model + dashboards into a Sigma **data model** +
**workbook**. Pull the model schema export and the widget definitions over REST,
translate JAQL / widget types / filters, emit the specs, then **verify parity**
against numbers from Sisense's own JAQL engine. Translate what maps cleanly;
**flag what doesn't** (custom JAQL functions, BloX/plugin widgets, scripted
widgets) — never emit confidently-wrong logic.

> **Status — LIVE-VALIDATED (2026-06-17).** A full end-to-end migration of the
> Sisense *Sample ECommerce* model + dashboard was run and **verified at exact
> data parity**: Sisense ElastiCube → Sisense Live-on-Snowflake → Snowflake
> (`CSA.SISENSE_ECOMMERCE`) → Sigma data model (`de8a93d3`/`fee42fdc`) → Sigma
> workbook (`d9312472`). Total Revenue **$39,759,625.515**, Total Quantity
> **91,206**, and the joined Revenue-by-Category breakdown all match Sisense
> JAQL exactly. The converter (`jaql_expr.py` + `convert.py`) was exercised
> against an 18-widget coverage corpus (every chart type + JAQL formula/level/
> top-N/break-by). Known refinements: pie-chart `color` spec + bar `topN`
> display-limit (values correct; display cap not yet enforced). Still flag —
> never fake — treemap/sunburst (no native Sigma equivalent) and unsupported
> JAQL functions. See `refs/design-notes.md`.

> Read `refs/` before relying on shapes: `sisense-rest-api.md` (validated
> endpoint map + auth + the access-key-vs-token gotcha), `jaql-mapping.md`
> (JAQL → Sigma formula + what's flagged), `widget-type-mapping.md` (widget →
> Sigma element coverage), `design-notes.md` (architecture, the Snowflake-parity
> requirement, hard problems). For canonical Sigma spec shapes, defer to the
> `sigma-data-models` / `sigma-workbooks` skills.

---

## Prerequisites

- **Sisense access.** Email + password or a bearer API token. Run
  `eval "$(scripts/sisense-auth.sh)"` — reads `SISENSE_BASE_URL` +
  `SISENSE_EMAIL`/`SISENSE_PASSWORD` (or a stored `SISENSE_API_TOKEN`) from the
  env or `~/.sigma-migration/sisense.env`. **Use a bearer token, not an
  access-key public key** (that's for SSO/embed — see `refs/sisense-rest-api.md`).
- **Sigma API token** — `eval "$(scripts/get-token.sh)"` (uses
  `SIGMA_CLIENT_ID`/`SIGMA_CLIENT_SECRET`/`SIGMA_BASE_URL` or
  `~/.sigma-migration/env`).
- **A Sigma connection to the warehouse holding the source data.** Parity only
  means something when Sigma reads the same data Sisense did. For ElastiCube
  (ECCloud) sources this means **landing the data in Snowflake first** and
  pointing both tools at it — see `refs/design-notes.md` ("Snowflake-parity").
- **Python 3** (stdlib only).

## Phase 0 — Assess (optional)
Run the `sisense-assessment` skill for an estate inventory + converter-coverage
scoring before committing to conversions.

## Phase 1 — Discover  ✅ working
```sh
eval "$(scripts/sisense-auth.sh)"
python3 scripts/discover.py --out ~/sisense-migration        # all cubes + dashboards
python3 scripts/discover.py --out ~/sisense-migration --cube "Sample ECommerce"
```
Writes `~/sisense-migration/discovery/`: `elasticubes.json`,
`model_<title>.json` (full schema export), `dashboards.json` (widgets inlined).

## Phase 2 — Convert the model  ⏳ scaffold
`convert.py model` → Sigma DM spec from `model_<title>.json`: each
`schema.tables[]` → DM element (plain table → warehouse source; table with
`expression` → Custom-SQL element, SQL verbatim + flagged), `relations[]` → DM
relationships, column `type` codes → Sigma types. Targets the Snowflake
connection holding the landed data.

## Phase 3 — Convert dashboards  ⏳ scaffold
`convert.py dashboard` → workbook spec: widget `type` → element
(`pivot2`→pivot-table, `indicator`→KPI, `chart/*`→chart, `tablewidget`→table),
panel JAQL → formulas via `jaql_expr.py`, filters → controls.

## Phase 4 — Verify parity  ⏳ scaffold
`verify_parity.py` runs each widget's JAQL (`POST /api/datasources/{ds}/jaql`)
and compares to the Sigma element query. **GREEN gate** before done.

## Phase 5 — Repoint + enhance
Wire workbook → DM, lay out (decollide), polish. Defer to `sigma-workbooks`.

## Flag, never fake
Custom JAQL functions, BloX/plugin/scripted widgets, import-time
`modelingTransformations`, and any unmapped viz are surfaced as loud flags in
the conversion report — not silently approximated.
