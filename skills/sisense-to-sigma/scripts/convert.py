#!/usr/bin/env python3
"""
Sisense -> Sigma converter.

  convert.py model     <model_*.json> <inodes.json>  -> sigma_dm_spec.json
  convert.py dashboard <dashboards.json> <dm.json>    -> sigma_workbook_spec.json
  convert.py classify  <dashboards.json>              -> coverage report (stdout)

model:     ElastiCube/Live datamodel export -> Sigma data-model spec (warehouse-table
           elements + relationships). inodes.json maps TABLE -> {inodeId, columns}.
dashboard: dashboard widgets -> Sigma workbook spec; widget type -> element,
           panel JAQL -> column formulas via jaql_expr. Unmapped widgets/JAQL are
           FLAGGED (kind:"flagged") not faked.
"""
import json, sys, re
import jaql_expr as J

# Sisense type code -> Sigma column type
TYPE = {4: "datetime", 5: "number", 8: "number", 18: "text", 6: "datetime", 31: "datetime"}

# Sisense widget type -> Sigma workbook element + coverage tag
WIDGET_MAP = {
    "indicator":     ("kpi",   "AUTO"),
    "chart/column":  ("bar",   "AUTO"),
    "chart/bar":     ("bar",   "AUTO"),
    "chart/line":    ("line",  "AUTO"),
    "chart/area":    ("area",  "AUTO"),
    "chart/pie":     ("pie",   "AUTO"),
    "pivot2":        ("pivot", "AUTO"),
    "pivot":         ("pivot", "AUTO"),
    "tablewidget":   ("table", "AUTO"),
    "chart/scatter": ("scatter", "HINT"),
    "chart/polar":   ("radar", "HINT"),
    "chart/funnel":  ("bar",   "HINT"),   # no native funnel -> bar + flag note
    "treemap":       (None,    "MANUAL"), # no native equivalent
    "sunburst":      (None,    "MANUAL"),
    "map/area":      ("geography-region", "HINT"),
    "map/scatter":   ("geography-point",  "HINT"),
}

# ---------- model -> DM ----------
import random, string
def _sid(n=10):
    return "".join(random.choices(string.ascii_letters + string.digits, k=n))

def _translate_ec_sql(sql, database, schema):
    """Best-effort port of Sisense ElastiCube SQL to warehouse SQL:
    [Table].[Col] -> "TABLE"."Col" ; bare [Table] (FROM/JOIN) -> DB.SCHEMA."TABLE".
    Always FLAGGED for human review — ElastiCube dialect funcs may not be warehouse-valid."""
    # qualify FROM/JOIN table refs first (before the column rewrites touch them)
    sql = re.sub(r"(FROM|JOIN)\s+\[([^\]]+)\]",
                 lambda m: f'{m.group(1)} {database}.{schema}."{m.group(2).upper()}" "{m.group(2).upper()}"', sql, flags=re.I)
    # [Table].[Col] and [Table].Col  ->  "TABLE"."Col"
    sql = re.sub(r"\[([^\]]+)\]\.\[([^\]]+)\]",
                 lambda m: f'"{m.group(1).upper()}"."{m.group(2)}"', sql)
    sql = re.sub(r"\[([^\]]+)\]\.([A-Za-z_][\w]*)",
                 lambda m: f'"{m.group(1).upper()}"."{m.group(2)}"', sql)
    return sql

def _split_top_commas(s):
    """Split a SQL projection list on top-level commas (respecting parens)."""
    parts, depth, cur = [], 0, ""
    for ch in s:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch == "," and depth == 0:
            parts.append(cur); cur = ""
        else:
            cur += ch
    if cur.strip():
        parts.append(cur)
    return parts

def _ec_sql_aliased(expr, declared, database, schema):
    """Translate ElastiCube SQL AND alias each SELECT output to the declared
    column name (quoted) so the warehouse output columns match the element's
    column formulas exactly (Snowflake uppercases unquoted aliases otherwise)."""
    sql = _translate_ec_sql(expr, database, schema)
    m = re.match(r"\s*SELECT\s+(.*?)\s+FROM\s", sql, re.S | re.I)
    if not m:
        return sql, False  # couldn't parse projection — leave as-is, flag harder
    proj = _split_top_commas(m.group(1))
    if len(proj) != len(declared):
        return sql, False
    aliased = []
    for part, name in zip(proj, declared):
        base = re.sub(r'\s+AS\s+("?[\w]+"?)\s*$', "", part.strip(), flags=re.I)
        aliased.append(f'{base} AS "{name}"')
    return sql[:m.start(1)] + ", ".join(aliased) + sql[m.end(1):], True

def convert_model(model, connection_id, schema="SISENSE_ECOMMERCE",
                  database="CSA", name=None):
    """Sisense Live/ElastiCube model export -> (Sigma DM spec, flags).
    Plain tables -> warehouse-table elements (source = connectionId + path).
    Tables with an `expression` (ElastiCube custom SQL) -> custom-SQL ('sql')
    elements with a best-effort dialect translation + a loud FLAG (never silently
    treated as a physical warehouse table). Relationships go on the fact element."""
    tables = [t for ds in model["datasets"] for t in ds["schema"]["tables"]]
    by_lower = {t["name"].lower(): t for t in tables}
    elements, el_id, col_id, flags = [], {}, {}, []
    for t in tables:
        eid = _sid()
        el_id[t["name"]] = eid
        expr = (t.get("expression") or {}).get("expression")
        cols = []
        for c in t["columns"]:
            cid = _sid()
            col_id[(t["name"], c["name"])] = cid
            # warehouse-table cols prefix on the physical table; SQL-source cols
            # use the fixed 'Custom SQL' prefix ([Custom SQL/OutputCol]) — NOT the
            # element name (which gives "dependency not found") nor bare (circular)
            formula = f'[Custom SQL/{c["name"]}]' if expr else f'[{t["name"].upper()}/{c["name"]}]'
            cols.append({"id": cid, "formula": formula, "name": c["name"]})
        if expr:
            stmt, aliased = _ec_sql_aliased(expr, [c["name"] for c in t["columns"]],
                                            database, schema)
            elements.append({"id": eid, "kind": "table",
                             "source": {"kind": "sql", "connectionId": connection_id,
                                        "statement": stmt},
                             "columns": cols, "name": t["name"],
                             "order": [c["id"] for c in cols]})
            flags.append({"table": t["name"], "reason": "ElastiCube custom-SQL table — "
                          "emitted as a Sigma SQL element with a best-effort dialect "
                          "translation" + ("" if aliased else " (column aliasing failed — review)") +
                          "; VERIFY the SQL runs on the warehouse",
                          "original_sql": expr})
        else:
            elements.append({"id": eid, "kind": "table",
                             "source": {"connectionId": connection_id, "kind": "warehouse-table",
                                        "path": [database, schema, t["name"].upper()]},
                             "columns": cols, "name": t["name"],
                             "order": [c["id"] for c in cols]})
    # relationships (fact -> dim) from model.relations[]
    colref = {}
    for ds in model["datasets"]:
        for t in ds["schema"]["tables"]:
            for c in t["columns"]:
                colref[(t["oid"], c["oid"])] = (t["name"], c["name"])
    for r in model.get("relations", []):
        cc = r["columns"]
        if len(cc) != 2:
            continue
        a = colref.get((cc[0]["table"], cc[0]["column"]))
        b = colref.get((cc[1]["table"], cc[1]["column"]))
        if not a or not b:
            continue
        (ft, fc), (tt, tc) = (a, b)
        if len(by_lower[a[0].lower()]["columns"]) < len(by_lower[b[0].lower()]["columns"]):
            (ft, fc), (tt, tc) = b, a   # fact = the wider table
        for e in elements:
            if e["id"] == el_id[ft]:
                e.setdefault("relationships", []).append({
                    "id": _sid(), "targetElementId": el_id[tt],
                    "keys": [{"sourceColumnId": col_id[(ft, fc)],
                              "targetColumnId": col_id[(tt, tc)]}],
                    "name": tt.upper()})  # clean workbook cross-refs: [Fact/DIM/Col]
    elements.sort(key=lambda e: 1 if e.get("relationships") else 0)  # dims before fact
    spec = {"name": name or f"{model.get('title', 'Model')} (from Sisense)",
            "pages": [{"id": "p1", "name": "Model", "elements": elements}]}
    return spec, flags

# ---------- dashboard -> workbook (classify + emit) ----------
def widget_fields(w):
    """Return list of (panel_name, kind, sigma_formula|FLAG, title)."""
    out = []
    for p in w.get("metadata", {}).get("panels", []):
        for it in p.get("items", []):
            jaql = it.get("jaql", {})
            if not jaql:
                continue
            try:
                kind, formula = J.classify(jaql)
            except J.Unsupported as e:
                kind, formula = "flagged", f"FLAG: {e}"
            out.append({"panel": p["name"], "kind": kind, "formula": formula,
                        "title": jaql.get("title"), "topn": (J.top_n(jaql) if kind=="dimension" else None)})
    return out

def classify_dashboard(dashboards):
    rows = []
    for d in dashboards:
        for w in d.get("widgets", []):
            wt = w.get("type")
            target, tag = WIDGET_MAP.get(wt, (None, "UNHANDLED"))
            flags = [f for f in widget_fields(w) if f["kind"] == "flagged"]
            if target is None:
                tag = "MANUAL" if tag != "UNHANDLED" else "UNHANDLED"
            rows.append({"title": w.get("title"), "sisense_type": wt,
                         "sigma_element": target, "tag": tag,
                         "field_flags": [f["formula"] for f in flags]})
    return rows

# ---------- dashboard -> workbook (generic emit) ----------
# Sisense widget type -> Sigma workbook element kind
SIGMA_KIND = {
    "indicator": "kpi-chart", "chart/column": "bar-chart", "chart/bar": "bar-chart",
    "chart/line": "line-chart", "chart/area": "area-chart", "chart/pie": "pie-chart",
    "chart/polar": "bar-chart", "chart/funnel": "bar-chart", "chart/scatter": "scatter-chart",
    "pivot2": "pivot-table", "pivot": "pivot-table", "tablewidget": "table",
}
MONEY = {"kind": "number", "formatString": "$,.0f", "currencySymbol": "$"}
# Sisense panel name -> logical role
DIM_PANELS = {"categories", "x-axis", "rows", "point", "geo", "break by"}
MEAS_PANELS = {"value", "values", "y-axis", "size", "color"}

def _masterize(formula):
    """Rewrite bare [Col] refs to [Master/Col] (skip refs that already have '/')."""
    return re.sub(r"\[([^/\]]+)\]", r"[Master/\1]", formula)

def _money_fmt(jaql):
    fmt = (jaql.get("format") or {})
    return MONEY if (fmt.get("mask", {}) or {}).get("currency") or "Revenue" in (jaql.get("title") or "") or "Cost" in (jaql.get("title") or "") else None

def convert_dashboard(dashboards, model, dm_info):
    """Emit a Sigma workbook spec from Sisense dashboards.
    dm_info = {dataModelId, factElementId, factName}. Builds a Master data
    element on the fact DM element (own cols + cross-ref dim cols) and one viz
    element per supported widget. Unsupported widgets are recorded in `flags`."""
    tables = [t for ds in model["datasets"] for t in ds["schema"]["tables"]]
    fact = max(tables, key=lambda t: len(t["columns"]))["name"]
    fact_name = dm_info["factName"]
    cid = lambda: _sid(8)

    # collect referenced (table, col) across all widgets -> Master columns
    master_cols, master_seen, name_for = [], {}, {}
    def master_ref(table, col):
        key = (table, col)
        if key in master_seen:
            return master_seen[key]
        disp = col if col not in name_for or name_for[col] == table else f"{table} {col}"
        name_for.setdefault(col, table)
        mid = "m_" + cid()
        formula = (f"[{fact_name}/{col}]" if table == fact
                   else f"[{fact_name}/{table.upper()}/{col}]")
        col_spec = {"id": mid, "formula": formula, "name": disp}
        master_cols.append(col_spec)
        master_seen[key] = disp  # viz refs use [Master/disp]
        return disp

    flags = []
    viz_elements = []
    for d in dashboards:
        # dashboard-level filters -> surface (not silently dropped). Emitting them
        # as Sigma controls is a follow-up; for now flag each so it's handled.
        for fl in (d.get("filters") or []):
            jq = (fl.get("jaql") or {})
            flags.append({"dashboard": d.get("title"), "filter": jq.get("title") or jq.get("dim"),
                          "reason": "dashboard filter — recreate as a Sigma control/element filter"})
        for w in d.get("widgets", []):
            wt = w.get("type")
            kind = SIGMA_KIND.get(wt)
            if not kind:
                flags.append({"widget": w.get("title"), "type": wt, "reason": "no Sigma element (treemap/sunburst/map/etc.) — flag"})
                continue
            dims, meas = [], []
            ok = True
            for p in w.get("metadata", {}).get("panels", []):
                role = "dim" if p["name"] in DIM_PANELS else ("meas" if p["name"] in MEAS_PANELS else None)
                for it in p.get("items", []):
                    jaql = it.get("jaql", {})
                    if not jaql:
                        continue
                    try:
                        k, formula = J.classify(jaql)
                    except J.Unsupported as e:
                        flags.append({"widget": w.get("title"), "field": jaql.get("title"), "reason": str(e)})
                        ok = False
                        continue
                    # register referenced columns into Master
                    for m in re.finditer(r"\[([^.\]/]+)\.([^\]]+)\]", J.raw_dims(jaql)):
                        master_ref(m.group(1), m.group(2))
                    vid = "c_" + cid()
                    spec = {"id": vid, "formula": _masterize(formula),
                            "name": jaql.get("title") or k}
                    fmt = _money_fmt(jaql)
                    if fmt and k == "measure":
                        spec["format"] = fmt
                    (meas if (k == "measure" or role == "meas") else dims).append((vid, spec, jaql))
            if not ok and not (dims or meas):
                continue
            viz_elements.append(_emit_viz(kind, w.get("title"), dims, meas))

    master = {"id": "master", "kind": "table",
              "source": {"dataModelId": dm_info["dataModelId"],
                         "elementId": dm_info["factElementId"], "kind": "data-model"},
              "columns": master_cols, "name": "Master",
              "order": [c["id"] for c in master_cols], "visibleAsSource": True}
    spec = {"name": "ECommerce Overview (from Sisense)", "schemaVersion": 1,
            "pages": [{"id": "pdata", "name": "Data", "elements": [master]},
                      {"id": "pmain", "name": "Overview", "elements": viz_elements}]}
    return spec, flags

def _emit_viz(kind, title, dims, meas):
    cols = [s for _, s, _ in dims] + [s for _, s, _ in meas]
    dim_ids = [i for i, _, _ in dims]
    meas_ids = [i for i, _, _ in meas]
    e = {"id": "v_" + _sid(8), "kind": kind,
         "source": {"elementId": "master", "kind": "table"},
         "columns": cols, "name": title}
    if kind == "kpi-chart":
        e["columns"] = [s for _, s, _ in meas][:1]
        e["value"] = {"columnId": meas_ids[0]} if meas_ids else None
    elif kind in ("bar-chart", "line-chart", "area-chart"):
        e["xAxis"] = {"columnId": dim_ids[0]} if dim_ids else None
        e["yAxis"] = {"columnIds": meas_ids}
        if len(dims) > 1:  # break-by series
            e["colorBy"] = {"columnId": dim_ids[1]}
    elif kind == "pie-chart":  # this org's API uses pie-chart with {id} refs
        e["value"] = {"id": meas_ids[0]} if meas_ids else None
        e["color"] = {"id": dim_ids[0]} if dim_ids else None
    elif kind == "scatter-chart":
        e["xAxis"] = {"columnId": meas_ids[0]} if meas_ids else None
        e["yAxis"] = {"columnIds": meas_ids[1:2]}
    elif kind == "pivot-table":
        # Sigma has no separate pivot element — emit a grouped table (groupBy the
        # pivot's row+column dims, calculations = the measures). A true column
        # cross-tab is a HINT: column-split dims become additional group levels.
        e["kind"] = "table"
        e["groupings"] = [{"id": "g_" + _sid(6), "groupBy": dim_ids, "calculations": meas_ids}]
    # table: columns only
    # element-level top-N: if any dim carried a JAQL top filter, rank by the
    # first measure (Sigma top-n filters rank by a measure column).
    for _, _, jq in dims:
        tn = J.top_n(jq)
        if tn and tn.get("count") and meas_ids:
            e.setdefault("filters", []).append({
                "id": "f_" + _sid(6), "columnId": meas_ids[0], "kind": "top-n",
                "rankingFunction": "rank", "mode": "top-n", "rowCount": int(tn["count"]),
                "includeNulls": "when-no-value-is-selected"})
            break
    return e

if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    cmd = sys.argv[1]
    if cmd == "model":
        # model <model.json> <connectionId> [schema] [database]
        model = json.load(open(sys.argv[2])); connection_id = sys.argv[3]
        schema = sys.argv[4] if len(sys.argv) > 4 else "SISENSE_ECOMMERCE"
        database = sys.argv[5] if len(sys.argv) > 5 else "CSA"
        spec, flags = convert_model(model, connection_id, schema, database)
        json.dump(spec, open("sigma_dm_spec.json", "w"), indent=2)
        print(f"wrote sigma_dm_spec.json ({len(spec['pages'][0]['elements'])} elements)")
        if flags:
            print("FLAGS (not faked):")
            for f in flags:
                print(f"  - {f['table']}: {f['reason']}")
    elif cmd == "classify":
        d = json.load(open(sys.argv[2]))
        rows = classify_dashboard(d)
        for r in rows:
            print(f"  [{r['tag']:8}] {r['title']:34} {r['sisense_type']:14} -> {r['sigma_element']}"
                  + (f"  FLAGS={r['field_flags']}" if r['field_flags'] else ""))
    elif cmd == "dashboard":
        # dashboard <dashboards.json> <model.json> <dataModelId> <factElementId> [factName] [--only TITLE]
        dashboards = json.load(open(sys.argv[2])); model = json.load(open(sys.argv[3]))
        dm_info = {"dataModelId": sys.argv[4], "factElementId": sys.argv[5],
                   "factName": sys.argv[6] if len(sys.argv) > 6 and not sys.argv[6].startswith("--") else "Commerce"}
        only = None
        if "--only" in sys.argv:
            only = sys.argv[sys.argv.index("--only") + 1]
            dashboards = [{**d, "widgets": [w for w in d.get("widgets", []) if d.get("title") == only or True]}
                          for d in dashboards if d.get("title") == only]
        spec, flags = convert_dashboard(dashboards, model, dm_info)
        json.dump(spec, open("sigma_workbook_spec.json", "w"), indent=2)
        print(f"wrote sigma_workbook_spec.json ({len(spec['pages'][1]['elements'])} viz elements, "
              f"{len(spec['pages'][0]['elements'][0]['columns'])} master cols)")
        if flags:
            print("FLAGS (not faked):")
            for f in flags:
                print("  -", f)
    else:
        sys.exit(f"unknown command: {cmd}")
