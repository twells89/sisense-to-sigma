# Design notes — sisense-to-sigma

## Status (2026-06-17) — production-hardened, live-validated
End-to-end **live-validated at exact parity** on Sample ECommerce (DM + 7-element
workbook; Total Revenue $39,759,625.515, monthly trend, joined category
breakdown all match Sisense JAQL). Built and tested:
- `discover.py` — live pull (auth, model schema export, dashboards). ✅
- `convert.py model` — DM spec; warehouse-table + **custom-SQL tables** (ElastiCube
  SQL → warehouse SQL, flagged); relationships; parameterized db/schema. ✅
- `convert.py dashboard` — **generic** widget→workbook emit (Master data element +
  kpi/bar/line/area/pie/scatter/pivot→grouped-table/table), JAQL formulas via
  `jaql_expr`, top-N filters, money formatting. ✅
- `jaql_expr.py` — aggs, ratio/nested formulas, date-level→DateTrunc, top-N;
  flags filtered/scoped measures + `PREV/PAST/RSUM/...`. 19 unit tests. ✅
- `verify_parity.py` — automated gate (Sisense JAQL vs warehouse), GREEN/RED. ✅
- `sisense-assessment/assess.py` — inventory + converter-coverage scoring. ✅
- Offline regression: `tests/test_jaql.py` (19) + `tests/test_convert.py` (17)
  against bundled `fixtures/`. ✅

### Known limitations (before unattended customer production)
- **Full live round-trip validated on ECommerce only.** Converter is hardened
  against Healthcare (custom-SQL) + Retail (more joins) structurally, but those
  weren't landed in Snowflake + parity-run end-to-end.
- **Dashboard filters → controls**: detected and **flagged**, not yet emitted as
  Sigma controls. Widget-level filters beyond top-N likewise.
- **pie-chart**: emitted as `pie-chart` with `{id}` refs (this org's API);
  donut/holeValue variants untested.
- **Multi-fact / snowflake schemas**: fact = widest table (heuristic); multi-fact
  models may need manual relationship review.
- **Conditional formatting, drill, RLS/data security**: not converted.
- ElastiCube custom-SQL translation is **best-effort + flagged** — verify the SQL
  runs on the warehouse (Sisense dialect functions may differ).

## Architecture (phases, mirroring the sibling converters)

- **Phase 0 — Assess.** `sisense-assessment` inventories the estate (cubes,
  dashboards, widget-type histogram, JAQL complexity) and scores each dashboard
  against converter coverage. Read-only.
- **Phase 1 — Discover.** `discover.py` pulls the model schema export + the
  dashboards/widgets bundle over REST. ✅ working.
- **Phase 2 — Convert model.** ElastiCube datasets → Sigma data model. Each
  `schema.tables[]` becomes a DM element: plain tables → warehouse table
  sources; tables with a non-null `expression` → Custom-SQL elements (SQL
  preserved verbatim, flagged). `relations[]` → DM relationships. Column `type`
  codes → Sigma column types.
- **Phase 3 — Convert dashboards.** Each widget → a workbook element
  (`pivot2`→pivot-table, `indicator`→KPI, `chart/*`→chart, `tablewidget`→table).
  Panel JAQL → workbook formulas via `jaql_expr.py`; dashboard + widget filters →
  controls. Translate what maps; **flag** custom JAQL functions, BloX/plugin
  widgets, scripted widgets.
- **Phase 4 — Parity.** Run each widget's JAQL via `POST /api/datasources/{ds}/jaql`
  and compare to the Sigma element's query. GREEN gate before claiming done.
- **Phase 5 — Repoint + enhance.** Wire the workbook to the DM, lay out, polish.

## The Snowflake-parity requirement (full migrations)

Sisense sample cubes live in Sisense's **ECCloud** storage — Sigma can't read
that. A *full* migration with real parity needs **both tools reading the same
warehouse**. Plan:

1. **Land the source data in Snowflake.** Load the Sisense sample dataset(s)
   into the shared demo warehouse (Snowflake `CSA.TJ`, the connection the other
   migration skills use). One schema per cube, e.g. `CSA.TJ.SISENSE_ECOMMERCE_*`.
2. **Make Sisense read Snowflake (Live).** Add a Snowflake connection in Sisense
   and build the source dashboard on a **Live** model over those same tables —
   so the Sisense side and the Sigma side query byte-identical data. (Reuses the
   existing sample-schema table structure from the model export.)
3. **Sigma DM targets the same Snowflake connection.** Phase-2 emits a DM whose
   sources are the `CSA.TJ.SISENSE_*` tables. Parity is then exact, not
   approximate.

Decision pending with the user: which sample cube to use as the first
end-to-end fixture (ECommerce is smallest: 4 datasets / 3 relations), and
whether to load via the Snowflake MCP / connector creds already on this machine.

## Hard problems / flags (don't fake)
- **JAQL custom formulas** with rich `context` (nested measures, `PREV`, `PAST`,
  `RSUM`, `RANK`, filtered measures) — translate the common ones, flag the rest.
- **BloX / plugin / scripted widgets** — no Sigma equivalent; flag.
- **ElastiCube import-time transforms** (`modelingTransformations`) — may encode
  ETL that belongs upstream in the warehouse; surface, don't silently inline.
- **Column type code map** — only `18`=text confirmed; complete the map from a
  populated cube before trusting numeric/date conversions.

## Graduation target
`sigma-migration-skills/plugins/sisense-to-sigma/` once a live ECommerce
end-to-end run hits GREEN parity. Until then, README + SKILL status banners say
scaffold.
