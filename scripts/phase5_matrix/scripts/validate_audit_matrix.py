#!/usr/bin/env python3
"""
validate_audit_matrix.py — Phase 5 Step G: QA finale

Checks (in order):
  G01  Row counts  (41 course, 20 ateneo, 61 page)
  G02  Primary key uniqueness
  G03  Master consistency  (course_id, university_id)
  G04  Missingness vocabulary  (no stray values)
  G05  No placeholder values  (TBD, XXX, ?, TODO …)
  G06  Schema match  (CSV fields == schema fields)
  G07  Threshold gate  (thresholds.yaml status=approved)
  G08  Flag consistency smoke tests
         – journey_blocked=1  ↔  journey_path_type=failed
         – wave_collection_mode=browser_fallback  ↔  wave_metric_comparability=reduced
         – journey_high_friction=1  →  journey_success=1
  G09  Evidence path populated (not empty / not raw taxonomy value)
  G10  Ateneo denominators non-zero
  G11  review_status values valid
  G12  Flag aggregate consistency  (ateneo flag rates match course-level counts)

Exit codes:
  0  all checks passed (all rows promoted to 'validated')
  1  failures found (see report; rows stay 'draft'/'checked' as appropriate)

Output:
  Prints report to stdout.
  Writes build report to phase5_matrix/reports/build_report_<YYYYMMDD>.md
  Patches review_status in data/analysis/*.csv when all clear.
"""

import csv
import re
import sys
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ANALYSIS = ROOT / "data" / "analysis"
MASTERS = ROOT / "data" / "masters"
SCHEMA = ROOT / "phase5_matrix" / "audit_matrix_schema.md"
THRESHOLDS = ROOT / "phase5_matrix" / "thresholds.yaml"
REPORTS_DIR = ROOT / "phase5_matrix" / "reports"

COURSE_CSV = ANALYSIS / "audit_matrix.csv"
ATENEO_CSV = ANALYSIS / "audit_matrix_ateneo.csv"
PAGE_CSV = ANALYSIS / "audit_matrix_page.csv"

TAXONOMY = frozenset({
    "not_collected", "not_applicable", "not_observed",
    "blocked", "not_exposed", "ambiguous", "tool_failure", "pending",
})

PLACEHOLDERS = frozenset({"TBD", "XXX", "?", "TODO", "FIXME", "N/A", "n/a", "#N/A", "PENDING"})

VALID_REVIEW_STATUS = {"draft", "checked", "validated"}

EXPECTED_COUNTS = {"course": 41, "ateneo": 20, "page": 61}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def load(path: Path) -> tuple[list[str], list[dict]]:
    with path.open(encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        fields = list(reader.fieldnames or [])
        rows = list(reader)
    return fields, rows


def write_csv(path: Path, fieldnames: list[str], rows: list[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)


def schema_fields_for(matrix: str) -> set[str]:
    """Extract field names from the schema section matching `matrix` name."""
    text = SCHEMA.read_text(encoding="utf-8")
    sections = re.split(r"^## ", text, flags=re.MULTILINE)
    sec = next(
        (s for s in sections
         if matrix in s.lower()[:50] or f"audit_matrix_{matrix}" in s[:80]
         or (matrix == "course" and "audit_matrix.csv" in s[:80])),
        None,
    )
    if sec is None:
        return set()
    return set(re.findall(r"^\|\s*`([a-z_][a-z0-9_]*)`\s*\|", sec, re.MULTILINE))


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------

class CheckResult:
    def __init__(self, name: str):
        self.name = name
        self.passed = True
        self.issues: list[str] = []
        self.warnings: list[str] = []

    def fail(self, msg: str) -> None:
        self.passed = False
        self.issues.append(msg)

    def warn(self, msg: str) -> None:
        self.warnings.append(msg)

    def summary(self) -> str:
        status = "✅ PASS" if self.passed else "❌ FAIL"
        lines = [f"{status}  {self.name}"]
        for issue in self.issues:
            lines.append(f"    ✗ {issue}")
        for w in self.warnings:
            lines.append(f"    ⚠ {w}")
        return "\n".join(lines)


def g01_row_counts(course_rows, ateneo_rows, page_rows) -> CheckResult:
    c = CheckResult("G01 Row counts")
    for label, rows, expected in [
        ("course", course_rows, 41),
        ("ateneo", ateneo_rows, 20),
        ("page", page_rows, 61),
    ]:
        if len(rows) != expected:
            c.fail(f"{label}: {len(rows)} rows (expected {expected})")
    return c


def g02_key_uniqueness(course_rows, ateneo_rows, page_rows) -> CheckResult:
    c = CheckResult("G02 Primary key uniqueness")
    # course: sample_course_id
    cids = [r.get("sample_course_id", "") for r in course_rows]
    dupes = [k for k, n in Counter(cids).items() if n > 1]
    if dupes:
        c.fail(f"course duplicate sample_course_id: {dupes}")
    # ateneo: university_id
    uids = [r.get("university_id", "") for r in ateneo_rows]
    dupes = [k for k, n in Counter(uids).items() if n > 1]
    if dupes:
        c.fail(f"ateneo duplicate university_id: {dupes}")
    # page: (source_document_id, page_role)
    pkeys = [(r.get("source_document_id", ""), r.get("page_role", "")) for r in page_rows]
    dupes = [k for k, n in Counter(pkeys).items() if n > 1]
    if dupes:
        c.fail(f"page duplicate (source_document_id, page_role): {dupes}")
    return c


def g03_master_consistency(course_rows, ateneo_rows) -> CheckResult:
    c = CheckResult("G03 Master consistency")
    # Load masters
    def ids(path, key):
        with (MASTERS / path).open(encoding="utf-8") as fh:
            return {r[key] for r in csv.DictReader(fh)}

    master_courses = ids("course_sample_master.csv", "sample_course_id")
    master_unis = ids("university_sample_master.csv", "university_id")

    csv_courses = {r.get("sample_course_id", "") for r in course_rows}
    csv_unis = {r.get("university_id", "") for r in ateneo_rows}

    extra_c = csv_courses - master_courses
    missing_c = master_courses - csv_courses
    if extra_c:
        c.fail(f"course IDs in CSV not in master: {sorted(extra_c)}")
    if missing_c:
        c.fail(f"master course IDs not in CSV: {sorted(missing_c)}")

    extra_u = csv_unis - master_unis
    missing_u = master_unis - csv_unis
    if extra_u:
        c.fail(f"ateneo IDs in CSV not in master: {sorted(extra_u)}")
    if missing_u:
        c.fail(f"master ateneo IDs not in CSV: {sorted(missing_u)}")

    # Also check course university_ids
    course_unis = {r.get("university_id", "") for r in course_rows}
    bad = course_unis - master_unis
    if bad:
        c.fail(f"course rows have university_id not in master: {sorted(bad)}")

    return c


def g04_missingness_vocabulary(course_rows, ateneo_rows, page_rows) -> CheckResult:
    """No cell should contain a taxonomy-like word not in the approved vocabulary."""
    c = CheckResult("G04 Missingness vocabulary")
    # Any value that looks like a taxonomy value but isn't in TAXONOMY
    pseudo_taxonomy = re.compile(r"^(not_|blocked|ambiguous|tool_failure|pending)", re.I)
    hits = []
    for label, rows in [("course", course_rows), ("ateneo", ateneo_rows), ("page", page_rows)]:
        for row in rows:
            key_field = "sample_course_id" if "sample_course_id" in row else "university_id"
            for k, v in row.items():
                v = v.strip()
                if pseudo_taxonomy.match(v) and v not in TAXONOMY:
                    hits.append(f"{label}:{row.get(key_field,'?')} {k}={repr(v)}")
    if hits:
        for h in hits[:20]:
            c.fail(h)
        if len(hits) > 20:
            c.fail(f"... and {len(hits)-20} more")
    return c


def g05_no_placeholders(course_rows, ateneo_rows, page_rows) -> CheckResult:
    c = CheckResult("G05 No placeholder values")
    hits = []
    for label, rows in [("course", course_rows), ("ateneo", ateneo_rows), ("page", page_rows)]:
        for row in rows:
            key_field = "sample_course_id" if "sample_course_id" in row else "university_id"
            for k, v in row.items():
                if v.strip() in PLACEHOLDERS:
                    hits.append(f"{label}:{row.get(key_field,'?')} {k}={repr(v)}")
    if hits:
        for h in hits[:20]:
            c.fail(h)
    return c


def g06_schema_match(course_fields, ateneo_fields, page_fields) -> CheckResult:
    c = CheckResult("G06 Schema match")
    for matrix, fields in [("course", course_fields), ("ateneo", ateneo_fields), ("page", page_fields)]:
        schema_f = schema_fields_for(matrix)
        if not schema_f:
            c.warn(f"{matrix}: schema section not found in {SCHEMA.name}")
            continue
        csv_set = set(fields)
        extra = csv_set - schema_f
        missing = schema_f - csv_set
        if extra:
            c.warn(f"{matrix} extra in CSV (not in schema): {sorted(extra)}")
        if missing:
            c.fail(f"{matrix} missing from CSV (in schema): {sorted(missing)}")
    return c


def g07_threshold_gate() -> CheckResult:
    c = CheckResult("G07 Threshold gate")
    try:
        import yaml
        data = yaml.safe_load(THRESHOLDS.read_text(encoding="utf-8"))
        status = data.get("status", "")
        if status != "approved":
            c.fail(f"thresholds.yaml status={repr(status)} (need 'approved')")
        approved_by = data.get("approved_by", "")
        approved_on = data.get("approved_on", "")
        if not approved_by:
            c.fail("thresholds.yaml missing approved_by")
        if not approved_on:
            c.fail("thresholds.yaml missing approved_on")
        if c.passed:
            c.warnings.append(f"approved by {approved_by} on {approved_on}")
    except ImportError:
        # Fallback: plain-text check
        text = THRESHOLDS.read_text(encoding="utf-8")
        if "status: approved" not in text:
            c.fail("thresholds.yaml does not contain 'status: approved'")
    except Exception as e:
        c.fail(f"cannot parse thresholds.yaml: {e}")
    return c


def g08_flag_consistency(course_rows) -> CheckResult:
    c = CheckResult("G08 Flag consistency smoke tests")

    for row in course_rows:
        cid = row.get("sample_course_id", "?")

        # journey_blocked=1 ↔ journey_path_type=failed
        blocked = row.get("journey_blocked", "0")
        path_type = row.get("journey_path_type", "")
        if blocked == "1" and path_type != "failed":
            c.fail(f"{cid}: journey_blocked=1 but journey_path_type={repr(path_type)}")
        if path_type == "failed" and blocked != "1":
            c.fail(f"{cid}: journey_path_type=failed but journey_blocked={repr(blocked)}")

        # wave_collection_mode=browser_fallback ↔ wave_metric_comparability=reduced
        wmode = row.get("wave_collection_mode", "")
        wcomp = row.get("wave_metric_comparability", "")
        if wmode == "browser_fallback" and wcomp != "reduced":
            c.fail(f"{cid}: wave_collection_mode=browser_fallback but wave_metric_comparability={repr(wcomp)}")
        if wcomp == "reduced" and wmode != "browser_fallback":
            c.fail(f"{cid}: wave_metric_comparability=reduced but wave_collection_mode={repr(wmode)}")

        # journey_high_friction=1 → journey_success must be 1
        hf = row.get("journey_high_friction", "0")
        js = row.get("journey_success", "")
        if hf == "1" and js not in ("1", ""):
            c.fail(f"{cid}: journey_high_friction=1 but journey_success={repr(js)}")

    return c


def g09_evidence_path(course_rows) -> CheckResult:
    c = CheckResult("G09 Evidence path populated")
    for row in course_rows:
        cid = row.get("sample_course_id", "?")
        ep = row.get("evidence_path", "").strip()
        if not ep:
            c.fail(f"{cid}: evidence_path empty")
        elif ep in TAXONOMY:
            c.fail(f"{cid}: evidence_path={repr(ep)} (raw taxonomy value)")
    return c


def g10_ateneo_denominators(ateneo_rows) -> CheckResult:
    c = CheckResult("G10 Ateneo denominators non-zero")
    denom_fields = [f for f in (ateneo_rows[0] if ateneo_rows else {}) if f.startswith("n_")]
    for row in ateneo_rows:
        uid = row.get("university_id", "?")
        for f in denom_fields:
            v = row.get(f, "").strip()
            if v in TAXONOMY:
                continue  # tagged missing, skip
            try:
                if int(v) == 0:
                    c.warn(f"{uid}: denominator {f}=0")
            except ValueError:
                if v:
                    c.warn(f"{uid}: denominator {f}={repr(v)} (non-numeric)")
    return c


def g11_review_status(course_rows, ateneo_rows, page_rows) -> CheckResult:
    c = CheckResult("G11 review_status values valid")
    for label, rows in [("course", course_rows), ("ateneo", ateneo_rows), ("page", page_rows)]:
        for row in rows:
            rs = row.get("review_status", "").strip()
            if rs not in VALID_REVIEW_STATUS:
                key = row.get("sample_course_id") or row.get("university_id") or row.get("source_document_id", "?")
                c.fail(f"{label}:{key} review_status={repr(rs)}")
    return c


def g12_flag_aggregate_consistency(course_rows, ateneo_rows) -> CheckResult:
    """Ateneo flag rates/counts must match course-level aggregation."""
    c = CheckResult("G12 Flag aggregate consistency")

    by_uni: dict[str, list[dict]] = defaultdict(list)
    for r in course_rows:
        by_uni[r.get("university_id", "")].append(r)

    RATE_FLAGS = [
        "journey_high_friction", "weak_external_findability",
        "accessibility_risk", "technical_risk", "information_fragmentation",
    ]
    COUNT_FLAGS = ["journey_blocked", "critical_student_pathway", "multi_phase_critical_case"]

    for row in ateneo_rows:
        uid = row.get("university_id", "?")
        courses = by_uni.get(uid, [])
        n = len(courses)
        if n == 0:
            c.fail(f"{uid}: no course rows found")
            continue

        for f in RATE_FLAGS:
            col = f + "_rate"
            stored = row.get(col, "").strip()
            if stored in TAXONOMY:
                continue
            try:
                expected_rate = round(sum(1 for r in courses if r.get(f, "") == "1") / n, 4)
                stored_rate = round(float(stored), 4)
                if abs(stored_rate - expected_rate) > 0.001:
                    c.fail(f"{uid} {col}: stored={stored_rate} expected={expected_rate}")
            except ValueError:
                c.warn(f"{uid} {col}={repr(stored)} not numeric")

        for f in COUNT_FLAGS:
            col = f + "_count"
            stored = row.get(col, "").strip()
            if stored in TAXONOMY or not stored:
                continue
            try:
                expected = sum(1 for r in courses if r.get(f, "") == "1")
                if int(stored) != expected:
                    c.fail(f"{uid} {col}: stored={stored} expected={expected}")
            except ValueError:
                c.warn(f"{uid} {col}={repr(stored)} not numeric")

    return c


# ---------------------------------------------------------------------------
# Promote review_status to 'validated'
# ---------------------------------------------------------------------------

def promote_status(
    course_rows, course_fields,
    ateneo_rows, ateneo_fields,
    page_rows, page_fields,
    blocked_ids: set[str],
) -> tuple[int, int]:
    """
    Promote rows to 'validated'.
    Blocked journey courses stay 'checked' (reduced data completeness).
    Returns (n_validated, n_checked).
    """
    n_validated = 0
    n_checked = 0

    for row in course_rows:
        cid = row.get("sample_course_id", "")
        if cid in blocked_ids:
            row["review_status"] = "checked"
            n_checked += 1
        else:
            row["review_status"] = "validated"
            n_validated += 1

    for row in ateneo_rows:
        row["review_status"] = "validated"
        n_validated += 1

    for row in page_rows:
        row["review_status"] = "validated"
        n_validated += 1

    write_csv(COURSE_CSV, course_fields, course_rows)
    write_csv(ATENEO_CSV, ateneo_fields, ateneo_rows)
    write_csv(PAGE_CSV, page_fields, page_rows)

    return n_validated, n_checked


# ---------------------------------------------------------------------------
# Build report
# ---------------------------------------------------------------------------

def write_report(results: list[CheckResult], promoted: bool, n_validated: int, n_checked: int) -> Path:
    today = date.today().strftime("%Y%m%d")
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    out = REPORTS_DIR / f"build_report_{today}.md"

    n_pass = sum(1 for r in results if r.passed)
    n_fail = sum(1 for r in results if not r.passed)

    lines = [
        f"# Phase 5 Build Report — {today}",
        "",
        f"**Checks passed:** {n_pass}/{len(results)}",
        f"**Checks failed:** {n_fail}/{len(results)}",
        "",
    ]

    if promoted:
        lines += [
            f"**Status promotion:** {n_validated} rows → `validated`; {n_checked} rows → `checked`",
            "",
        ]
    else:
        lines += [
            "**Status promotion:** SKIPPED (failures present — rows stay draft/checked)",
            "",
        ]

    lines.append("## Check Results")
    lines.append("")
    for r in results:
        lines.append(r.summary())
        lines.append("")

    out.write_text("\n".join(lines), encoding="utf-8")
    return out


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    course_fields, course_rows = load(COURSE_CSV)
    ateneo_fields, ateneo_rows = load(ATENEO_CSV)
    page_fields, page_rows = load(PAGE_CSV)

    print(f"Loaded: {len(course_rows)} course, {len(ateneo_rows)} ateneo, {len(page_rows)} page rows")
    print()

    results: list[CheckResult] = []

    results.append(g01_row_counts(course_rows, ateneo_rows, page_rows))
    results.append(g02_key_uniqueness(course_rows, ateneo_rows, page_rows))
    results.append(g03_master_consistency(course_rows, ateneo_rows))
    results.append(g04_missingness_vocabulary(course_rows, ateneo_rows, page_rows))
    results.append(g05_no_placeholders(course_rows, ateneo_rows, page_rows))
    results.append(g06_schema_match(course_fields, ateneo_fields, page_fields))
    results.append(g07_threshold_gate())
    results.append(g08_flag_consistency(course_rows))
    results.append(g09_evidence_path(course_rows))
    results.append(g10_ateneo_denominators(ateneo_rows))
    results.append(g11_review_status(course_rows, ateneo_rows, page_rows))
    results.append(g12_flag_aggregate_consistency(course_rows, ateneo_rows))

    for r in results:
        print(r.summary())

    n_fail = sum(1 for r in results if not r.passed)
    print()

    promoted = False
    n_validated = n_checked = 0

    if n_fail == 0:
        print("All checks passed. Promoting review_status …")
        blocked_ids = {r["sample_course_id"] for r in course_rows if r.get("journey_blocked", "0") == "1"}
        n_validated, n_checked = promote_status(
            course_rows, course_fields,
            ateneo_rows, ateneo_fields,
            page_rows, page_fields,
            blocked_ids,
        )
        promoted = True
        print(f"  {n_validated} rows → validated")
        print(f"  {n_checked} rows → checked  (blocked_js courses)")
    else:
        print(f"{n_fail} check(s) FAILED — review_status not promoted. Fix issues and re-run.")

    report_path = write_report(results, promoted, n_validated, n_checked)
    print(f"\nBuild report: {report_path}")

    sys.exit(0 if n_fail == 0 else 1)


if __name__ == "__main__":
    main()
