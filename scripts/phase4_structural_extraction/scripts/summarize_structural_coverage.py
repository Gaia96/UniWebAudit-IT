#!/usr/bin/env python3
"""
summarize_structural_coverage.py — Phase 4 Step 9 helper.

Reads data/collection/structural_indicators.csv and structural_evidence_long.csv
(or staging files with --target=staging) and prints summary tables suitable for
docs/reports/phase_4_structural_extraction_report.md.

Tables:
    A. Indicator coverage by priority
       indicator_id, priority, n_present, n_not_observed, n_ambiguous,
       n_blocked, n_not_exposed, n_not_applicable
    B. location_type distribution per indicator
    C. confidence distribution per indicator
    D. course-level missingness (essential indicators not_observed/ambiguous)
    E. render_mode breakdown (raw_http vs browser_rendered, with js_dependency_level)

Run:
    python3 structural_extraction/scripts/summarize_structural_coverage.py
    python3 structural_extraction/scripts/summarize_structural_coverage.py --target staging --markdown

Dependencies: stdlib only.
"""

from __future__ import annotations

import argparse
import csv
from collections import Counter, defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
COLLECTION_WIDE = REPO_ROOT / "data/collection/structural_indicators.csv"
COLLECTION_LONG = REPO_ROOT / "data/collection/structural_evidence_long.csv"
STAGING_WIDE = REPO_ROOT / "structural_extraction/staging/structural_indicators.staging.csv"
STAGING_LONG = REPO_ROOT / "structural_extraction/staging/structural_evidence_long.staging.csv"
MANIFEST = REPO_ROOT / "structural_extraction/extraction_manifest.csv"


def load_csv(p: Path) -> list[dict[str, str]]:
    with p.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def fmt_table(title: str, headers: list[str], rows: list[list[str]], markdown: bool) -> str:
    if markdown:
        out = [f"\n### {title}\n", "| " + " | ".join(headers) + " |",
               "|" + "|".join(["---"] * len(headers)) + "|"]
        for r in rows:
            out.append("| " + " | ".join(str(c) for c in r) + " |")
        return "\n".join(out)
    widths = [max(len(str(r[i])) for r in [headers] + rows) for i in range(len(headers))]
    line = "  ".join(h.ljust(widths[i]) for i, h in enumerate(headers))
    out = [f"\n=== {title} ===", line, "  ".join("-" * w for w in widths)]
    for r in rows:
        out.append("  ".join(str(c).ljust(widths[i]) for i, c in enumerate(r)))
    return "\n".join(out)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", choices=["staging", "collection"], default="collection")
    ap.add_argument("--markdown", action="store_true")
    args = ap.parse_args()

    long_path = STAGING_LONG if args.target == "staging" else COLLECTION_LONG
    if not long_path.exists():
        print(f"Missing: {long_path}")
        return 2
    rows = load_csv(long_path)

    # A. Indicator coverage by priority
    cov: dict[str, Counter] = defaultdict(Counter)
    priority: dict[str, str] = {}
    for r in rows:
        cov[r["indicator_id"]][r["observed"]] += 1
        priority[r["indicator_id"]] = r.get("priority", "")

    a_rows = []
    for iid in sorted(cov, key=lambda x: (priority.get(x, "z"), x)):
        c = cov[iid]
        a_rows.append([
            iid, priority.get(iid, ""),
            c["present"], c["not_observed"], c["ambiguous"],
            c["blocked"], c["not_exposed"], c["not_applicable"],
        ])
    print(fmt_table(
        "A. Indicator coverage (counts of observed values, 41 courses)",
        ["indicator_id", "priority", "present", "not_observed", "ambiguous",
         "blocked", "not_exposed", "not_applicable"],
        a_rows, args.markdown))

    # B. location_type distribution per indicator
    loc_counter: dict[str, Counter] = defaultdict(Counter)
    for r in rows:
        loc_counter[r["indicator_id"]][r["location_type"]] += 1
    all_loc = sorted({k for c in loc_counter.values() for k in c})
    b_rows = []
    for iid in sorted(loc_counter):
        b_rows.append([iid] + [loc_counter[iid].get(l, 0) for l in all_loc])
    print(fmt_table("B. location_type distribution", ["indicator_id"] + all_loc,
                    b_rows, args.markdown))

    # C. confidence distribution
    conf_counter: dict[str, Counter] = defaultdict(Counter)
    for r in rows:
        conf_counter[r["indicator_id"]][r["confidence"]] += 1
    all_conf = ["high", "medium", "low", "not_observed", "not_applicable"]
    c_rows = []
    for iid in sorted(conf_counter):
        c_rows.append([iid] + [conf_counter[iid].get(l, 0) for l in all_conf])
    print(fmt_table("C. confidence distribution", ["indicator_id"] + all_conf,
                    c_rows, args.markdown))

    # D. course-level missingness (essential)
    essential_per_course: dict[str, Counter] = defaultdict(Counter)
    for r in rows:
        if r.get("priority") == "essential":
            essential_per_course[r["course_id"]][r["observed"]] += 1
    d_rows = sorted(
        [[cid, c["present"], c["not_observed"], c["ambiguous"]]
         for cid, c in essential_per_course.items()],
        key=lambda x: -(int(x[2]) + int(x[3])),
    )
    print(fmt_table("D. Per-course essential missingness",
                    ["course_id", "present", "not_observed", "ambiguous"],
                    d_rows, args.markdown))

    # E. render_mode breakdown
    if MANIFEST.exists():
        mrows = load_csv(MANIFEST)
        e_counter = Counter((r["render_mode"], r.get("js_dependency_level_preaudit", "") or "(none)")
                            for r in mrows)
        e_rows = sorted([[mode, lvl, n] for (mode, lvl), n in e_counter.items()])
        print(fmt_table("E. Manifest render_mode breakdown",
                        ["render_mode", "js_dependency_level", "count"],
                        e_rows, args.markdown))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
