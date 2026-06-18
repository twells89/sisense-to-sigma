#!/usr/bin/env python3
"""Offline regression tests for the converter — runs against the bundled
fixtures (no network). Run: python3 tests/test_convert.py"""
import sys, os, json
HERE = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))
import convert as C

FIX = os.path.join(HERE, "..", "fixtures")
model = json.load(open(os.path.join(FIX, "model_ecommerce.json")))
dashboards = json.load(open(os.path.join(FIX, "dashboards.json")))
CONN = "00000000-0000-0000-0000-000000000000"

passed = failed = 0
def ok(label, cond):
    global passed, failed
    passed += 1 if cond else 0
    failed += 0 if cond else 1
    if not cond:
        print(f"  FAIL {label}")

# --- model -> DM ---
spec, flags = C.convert_model(model, CONN, "SISENSE_ECOMMERCE", "CSA")
els = spec["pages"][0]["elements"]
ok("model: 4 elements", len(els) == 4)
ok("model: all warehouse-table (no custom-sql in ecommerce)",
   all(e["source"]["kind"] == "warehouse-table" for e in els))
ok("model: 3 relationships on fact", sum(len(e.get("relationships", [])) for e in els) == 3)
ok("model: fact element is last (after dims)", els[-1].get("relationships"))
ok("model: clean star has only direction-heuristic flags (no custom-SQL/errors)",
   all("join direction" in f["reason"] for f in flags))
# with cardinality directions supplied, no flags at all
spec2, flags2 = C.convert_model(model, CONN, "SISENSE_ECOMMERCE", "CSA",
   directions={frozenset({("Commerce","Country ID"),("Country","Country ID")}):"Commerce",
               frozenset({("Commerce","Category ID"),("Category","Category ID")}):"Commerce",
               frozenset({("Commerce","Brand ID"),("Brand","Brand ID")}):"Commerce"})
ok("model: cardinality-resolved directions -> no flags", flags2 == [])
ok("model: warehouse path uses db+schema+TABLE",
   els[0]["source"]["path"][:2] == ["CSA", "SISENSE_ECOMMERCE"])
ok("model: column formula prefix is phys table",
   els[-1]["columns"][0]["formula"].startswith("[COMMERCE/"))

# --- dashboard -> workbook ---
dm_info = {"dataModelId": "dm-x", "factElementId": "fact-x", "factName": "Commerce"}
wb, dflags = C.convert_dashboard(
    [d for d in dashboards if d.get("title") == "ECommerce Overview (Live)"], model, dm_info)
page_els = wb["pages"][1]["elements"]
controls = [e for e in page_els if e["kind"] == "control"]
viz = [e for e in page_els if e["kind"] != "control"]
kinds = [e["kind"] for e in viz]
ok("wb: master data element present", wb["pages"][0]["elements"][0]["id"] == "master")
ok("wb: 6 viz elements", len(viz) == 6)
ok("wb: has kpi-chart", "kpi-chart" in kinds)
ok("wb: has bar-chart", "bar-chart" in kinds)
ok("wb: has line-chart", "line-chart" in kinds)
ok("wb: has pie-chart", "pie-chart" in kinds)
ok("wb: dashboard filters -> controls", len(controls) == 2 and all(c["controlType"]=="list" for c in controls))
ok("wb: control bound to master + has default values", controls[0]["filters"][0]["source"]["elementId"]=="master" and controls[0]["values"])
ok("wb: viz source the master", all(e["source"]["elementId"] == "master" for e in viz))
ok("wb: master cols are cross-ref or own (no bare warehouse path)",
   all("formula" in c for c in wb["pages"][0]["elements"][0]["columns"]))

# --- coverage classification flags the unmappable ---
rows = C.classify_dashboard(dashboards)
tags = {r["tag"] for r in rows}
ok("classify: treemap/sunburst -> MANUAL present", "MANUAL" in tags)
ok("classify: AUTO present", "AUTO" in tags)

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
