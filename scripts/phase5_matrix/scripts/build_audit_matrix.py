#!/usr/bin/env python3
"""
build_audit_matrix.py — Phase 5 Step D + F

Step D (this run): apply controlled missingness taxonomy to _tmp CSVs.
Step F (guarded): compute interpretive flags from thresholds.yaml — only runs
                  when thresholds.yaml has status: approved.

Usage:
    python3 build_audit_matrix.py [--step {D,F,DF}] [--dry-run]

Input:  phase5_matrix/_tmp/{course,page,ateneo}_raw.csv
Output: phase5_matrix/_tmp/{course,page,ateneo}_raw.csv  (Step D, in-place)
        data/analysis/audit_matrix{,_ateneo,_page}.csv   (Step F)
"""

import argparse
import csv
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parents[2]
TMP = ROOT / "phase5_matrix" / "_tmp"
THRESHOLDS_FILE = ROOT / "phase5_matrix" / "thresholds.yaml"
ANALYSIS_DIR = ROOT / "data" / "analysis"

COURSE_TMP = TMP / "course_raw.csv"
PAGE_TMP = TMP / "page_raw.csv"
ATENEO_TMP = TMP / "ateneo_raw.csv"

# ---------------------------------------------------------------------------
# Taxonomy
# ---------------------------------------------------------------------------
# Controlled missingness values — any blank cell that doesn't get one of these is a QA error
TAXONOMY = frozenset({
    "not_collected", "not_applicable", "not_observed",
    "blocked", "not_exposed", "ambiguous", "tool_failure", "pending",
})

# Structural indicator IDs (Phase 4, §11 codebook v1.1)
STRUCT_INDICATORS = [
    "course_title", "degree_level", "degree_class", "cfu", "duration",
    "academic_year", "location", "language", "study_plan",
    "admission_requirements", "admission_procedure", "deadlines",
    "fees_or_costs", "career_outcomes", "contacts", "official_regulation",
    "quality_or_satisfaction", "accessibility_services",
]

# Present values that make location_type / local_findability not applicable
STRUCT_NON_PRESENT = frozenset({"not_observed", "not_applicable", "blocked", "not_exposed"})

# Journey page-observation fields — blank on blocked journeys → "blocked";
# blank on successful journeys → "not_collected"
JOURNEY_OBS_FIELDS = [
    "breadcrumb_present", "menu_clarity_score", "onsite_search_present",
    "orientation_description", "orientation_requirements", "orientation_deadlines",
    "orientation_fees", "orientation_contacts", "orientation_multilingual",
    "orientation_study_plan", "orientation_careers",
    "orientation_score_raw", "orientation_score_norm",
    "title_text", "title_quality_score", "meta_description_present",
    "meta_description_quality_score", "canonical_present",
    "structured_data_course", "structured_data_breadcrumb", "indexability_status",
    "lang_declared", "skip_link_present", "accessibility_statement_present",
    "h1_present", "heading_structure_score",
]

# Page-matrix parsing fields — always not_collected when blank (data not joined yet)
PAGE_PARSING_FIELDS = [
    "title_text", "title_quality_score", "meta_description_present",
    "canonical_present", "lang_declared", "skip_link_present",
    "h1_present", "heading_structure_score", "accessibility_statement_present",
]

# Ateneo aggregated observation fields that inherit not_collected from course-level
ATENEO_OBS_AGG_FIELDS = [
    "menu_clarity_score_mean",
    "onsite_search_present_rate",
    "orientation_score_norm_mean",
    "orientation_score_norm_median",
]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _blank(v: str) -> bool:
    return v.strip() == ""


def _wave_comparability(mode: str) -> str:
    if mode == "api_primary":
        return "standard"
    if mode == "browser_fallback":
        return "reduced"
    return "not_applicable"


def _load_csv(path: Path) -> tuple[list[str], list[dict]]:
    with path.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        fieldnames = reader.fieldnames or []
        rows = list(reader)
    return list(fieldnames), rows


def _write_csv(path: Path, fieldnames: list[str], rows: list[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


# ---------------------------------------------------------------------------
# Step D: apply_missingness
# ---------------------------------------------------------------------------

def apply_missingness_course(rows: list[dict]) -> tuple[list[dict], dict]:
    changes: dict[str, int] = {}

    def tag(row: dict, field: str, value: str) -> None:
        if row.get(field, "").strip() == "":
            row[field] = value
            changes[field] = changes.get(field, 0) + 1

    for r in rows:
        is_blocked = r.get("journey_path_type", "") == "failed"

        # -- Journey metric fields —— force-overwrite for blocked journeys --
        # click_depth and time_seconds may contain partial data from the SQL step;
        # the semantic value is `blocked` (target never reached).
        if is_blocked:
            # Force-overwrite partial data: these metrics are meaningless when the target was never reached
            for f in ("journey_click_depth", "journey_time_seconds"):
                if r.get(f, "").strip() != "":
                    r[f] = "blocked"
                    changes[f] = changes.get(f, 0) + 1
                else:
                    tag(r, f, "blocked")
        # journey_target_url: URL is valid even for blocked journeys (confirmed live);
        # only tag blank if genuinely uncollected.
        tag(r, "journey_target_url", "not_collected" if not is_blocked else r.get("journey_target_url", ""))

        # -- Journey page observation fields --
        val = "blocked" if is_blocked else "not_collected"
        for f in JOURNEY_OBS_FIELDS:
            tag(r, f, val)

        # -- SERP rank fields --
        serp_collected = r.get("serp_crawl_run_id", "").strip() != ""
        for rank_field in ("google_rank_exact", "google_rank_generic"):
            if _blank(r.get(rank_field, "")):
                tag(r, rank_field, "not_observed" if serp_collected else "not_collected")

        # -- WAVE detail counts (items not extracted) --
        for f in ("missing_alt_count", "empty_link_count", "form_label_issue_count"):
            tag(r, f, "not_collected")

        # -- Structural *_location_type and *_local_findability --
        for ind in STRUCT_INDICATORS:
            pres = r.get(f"{ind}_present", "").strip()
            use_na = pres in STRUCT_NON_PRESENT

            loc_f = f"{ind}_location_type"
            find_f = f"{ind}_local_findability"

            if _blank(r.get(loc_f, "")):
                tag(r, loc_f, "not_applicable" if use_na else "ambiguous")

            if _blank(r.get(find_f, "")):
                tag(r, find_f, "not_applicable" if use_na else "ambiguous")

        # -- wave_metric_comparability --
        if _blank(r.get("wave_metric_comparability", "")):
            mode = r.get("wave_collection_mode", "").strip()
            r["wave_metric_comparability"] = _wave_comparability(mode)
            changes["wave_metric_comparability"] = changes.get("wave_metric_comparability", 0) + 1

    return rows, changes


def apply_missingness_page(rows: list[dict]) -> tuple[list[dict], dict]:
    changes: dict[str, int] = {}

    def tag(row: dict, field: str, value: str) -> None:
        if row.get(field, "").strip() == "":
            row[field] = value
            changes[field] = changes.get(field, 0) + 1

    for r in rows:
        # Parsing fields not joined from source yet
        for f in PAGE_PARSING_FIELDS:
            tag(r, f, "not_collected")

        # wave_metric_comparability
        if _blank(r.get("wave_metric_comparability", "")):
            mode = r.get("wave_collection_mode", "").strip()
            r["wave_metric_comparability"] = _wave_comparability(mode)
            changes["wave_metric_comparability"] = changes.get("wave_metric_comparability", 0) + 1

    return rows, changes


def apply_missingness_ateneo(rows: list[dict]) -> tuple[list[dict], dict]:
    changes: dict[str, int] = {}

    def tag(row: dict, field: str, value: str) -> None:
        if row.get(field, "").strip() == "":
            row[field] = value
            changes[field] = changes.get(field, 0) + 1

    for r in rows:
        # Aggregates inherited from not_collected course-level fields
        for f in ATENEO_OBS_AGG_FIELDS:
            tag(r, f, "not_collected")

        # Journey medians: not_applicable when no successful journeys exist
        n_success = r.get("n_journeys_success", "0").strip()
        try:
            has_success = int(float(n_success)) > 0
        except (ValueError, TypeError):
            has_success = False

        if not has_success:
            tag(r, "journey_click_depth_median", "not_applicable")
            tag(r, "journey_time_seconds_median", "not_applicable")

        # Excl_reduced aggregate: not_applicable when no browser_fallback pages for this ateneo
        n_fallback = r.get("n_wave_browser_fallback", "0").strip()
        try:
            has_fallback = int(float(n_fallback)) > 0
        except (ValueError, TypeError):
            has_fallback = False

        if not has_fallback:
            tag(r, "course_wave_error_count_median_excl_reduced", "not_applicable")

    return rows, changes


# ---------------------------------------------------------------------------
# QA: cross-tab controlled fields
# ---------------------------------------------------------------------------

def qa_cross_tab(rows: list[dict], matrix_name: str) -> list[str]:
    """
    For every field in TAXONOMY-tagged columns, verify only allowed values.
    Returns list of violation strings (empty = pass).
    """
    BLANK_ALLOWED = frozenset({
        "ai_search_note", "overall_notes", "provenance_notes", "journey_notes",
        "breadcrumb_depth_proxy", "department", "university_city",
        "programmes_hub_url", "course_class", "notes",
    })
    violations = []
    for r in rows:
        for field, value in r.items():
            if field in BLANK_ALLOWED:
                continue
            v = value.strip()
            if v == "":
                violations.append(
                    f"[{matrix_name}] {r.get('sample_course_id') or r.get('university_id') or '?'}"
                    f" — blank not allowed in '{field}'"
                )
    return violations


def qa_no_blank_controlled(rows: list[dict], controlled_fields: list[str], matrix_name: str) -> list[str]:
    violations = []
    for r in rows:
        key = r.get("sample_course_id") or r.get("university_id") or r.get("page_audit_id", "?")
        for f in controlled_fields:
            if f in r and r[f].strip() == "":
                violations.append(f"[{matrix_name}] {key} — '{f}' still blank after missingness")
    return violations


# ---------------------------------------------------------------------------
# Step F: interpretive flags (guarded by thresholds.yaml)
# ---------------------------------------------------------------------------

def load_thresholds() -> dict:
    try:
        import yaml  # type: ignore
    except ImportError:
        print("ERROR: PyYAML not installed. Run: pip install pyyaml", file=sys.stderr)
        sys.exit(1)

    if not THRESHOLDS_FILE.exists():
        print(f"ERROR: {THRESHOLDS_FILE} not found.", file=sys.stderr)
        sys.exit(1)

    with THRESHOLDS_FILE.open() as fh:
        data = yaml.safe_load(fh)

    # Thresholds must be explicitly signed off before the analysis layer is computed
    if data.get("status") != "approved":
        print(
            f"ERROR: thresholds.yaml status is '{data.get('status')}', not 'approved'. "
            "Step F requires explicit approval before interpretive flags are computed.",
            file=sys.stderr,
        )
        sys.exit(1)

    return data


def _int_flag(condition: bool) -> str:
    return "1" if condition else "0"


def _numeric(v: str) -> float | None:
    try:
        return float(v)
    except (ValueError, TypeError):
        return None


def _extract_thresholds(data: dict) -> dict:
    """Flatten thresholds list into {component_name: value} dict."""
    result = {}
    for entry in data.get("thresholds", []):
        for comp in entry.get("components", []):
            result[comp["name"]] = comp["threshold"]
    return result


def apply_interpretive_flags(rows: list[dict], thresholds: dict) -> list[dict]:
    T = _extract_thresholds(thresholds)

    t_click       = float(T["T_clickdepth"])
    t_jtime       = float(T["T_jtime"])
    t_wave_err    = float(T["T_wave_err"])
    t_wave_contrast = float(T["T_wave_contrast"])
    t_lh_a11y     = float(T["T_lh_a11y"])
    t_lh_perf     = float(T["T_lh_perf"])
    t_flag_count  = int(T["T_flag_count"])

    for r in rows:
        success = r.get("journey_success", "") == "1"
        blocked = r.get("journey_path_type", "") == "failed"

        # journey_blocked
        r["journey_blocked"] = _int_flag(blocked)

        # journey_high_friction (only for successful journeys)
        if success:
            depth = _numeric(r.get("journey_click_depth", ""))
            jtime = _numeric(r.get("journey_time_seconds", ""))
            path_search = r.get("journey_path_type", "") == "onsite_search"
            high_friction = (
                (depth is not None and depth >= t_click)
                or (jtime is not None and jtime >= t_jtime)
                or path_search
            )
            r["journey_high_friction"] = _int_flag(high_friction)
        else:
            r["journey_high_friction"] = "0"

        # weak_external_findability
        r["weak_external_findability"] = r.get("serp_missing_all_core_queries", "0")

        # accessibility_risk
        wave_err = _numeric(r.get("wave_error_count", ""))
        wave_cont = _numeric(r.get("wave_contrast_error_count", ""))
        lh_a11y = _numeric(r.get("lighthouse_accessibility", ""))
        a11y_risk = (
            (wave_err is not None and wave_err >= t_wave_err)
            or (wave_cont is not None and wave_cont >= t_wave_contrast)
            or (lh_a11y is not None and lh_a11y < t_lh_a11y)
        )
        r["accessibility_risk"] = _int_flag(a11y_risk)

        # technical_risk
        lh_perf = _numeric(r.get("lighthouse_performance", ""))
        tech_risk = lh_perf is not None and lh_perf < t_lh_perf
        r["technical_risk"] = _int_flag(tech_risk)

        # information_fragmentation
        frag = r.get("structural_fragmented_information", "0") == "1"
        ext_dep = r.get("structural_external_portal_dependency", "0") == "1"
        r["information_fragmentation"] = _int_flag(frag or ext_dep)

        # critical_student_pathway (compound)
        cp = (
            r["journey_high_friction"] == "1"
            and r["weak_external_findability"] == "1"
            and (
                r["accessibility_risk"] == "1"
                or r["technical_risk"] == "1"
                or r["information_fragmentation"] == "1"
            )
        )
        r["critical_student_pathway"] = _int_flag(cp)

        # multi_phase_critical_case
        construct_flags = [
            "journey_high_friction", "journey_blocked", "weak_external_findability",
            "accessibility_risk", "technical_risk", "information_fragmentation",
        ]
        active_count = sum(1 for f in construct_flags if r.get(f, "0") == "1")
        r["multi_phase_critical_case"] = _int_flag(active_count >= t_flag_count)

    return rows


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Phase 5 audit matrix build")
    parser.add_argument(
        "--step",
        choices=["D", "F", "DF"],
        default="D",
        help="D=missingness only; F=interpretive flags only; DF=both (default: D)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print changes without writing files",
    )
    args = parser.parse_args()

    run_D = args.step in ("D", "DF")
    run_F = args.step in ("F", "DF")

    if run_F:
        thresholds = load_thresholds()
        print(f"Thresholds approved on {thresholds.get('approved_on', '?')} by {thresholds.get('approved_by', '?')}")

    # -- Load --
    course_fields, course_rows = _load_csv(COURSE_TMP)
    page_fields, page_rows = _load_csv(PAGE_TMP)
    ateneo_fields, ateneo_rows = _load_csv(ATENEO_TMP)

    print(f"Loaded: {len(course_rows)} course rows, {len(page_rows)} page rows, {len(ateneo_rows)} ateneo rows")

    # Safety: abort if course CSV is empty (prevents overwriting good data with nothing)
    if len(course_rows) == 0:
        print("ERROR: course_raw.csv loaded 0 rows — aborting to prevent data loss.", file=sys.stderr)
        print(f"  Check file: {COURSE_TMP}", file=sys.stderr)
        sys.exit(1)

    if run_D:
        print("\n--- Step D: applying missingness taxonomy ---")

        course_rows, cc = apply_missingness_course(course_rows)
        page_rows, pc = apply_missingness_page(page_rows)
        ateneo_rows, ac = apply_missingness_ateneo(ateneo_rows)

        for label, changes in (("course", cc), ("page", pc), ("ateneo", ac)):
            total = sum(changes.values())
            print(f"  {label}: {total} cells tagged")
            for field, n in sorted(changes.items(), key=lambda x: -x[1])[:10]:
                print(f"    {n:4d}  {field}")

        # QA: no remaining blanks on controlled course fields
        controlled_check = JOURNEY_OBS_FIELDS + [
            "journey_click_depth", "journey_time_seconds",
            "google_rank_exact", "google_rank_generic",
            "wave_metric_comparability",
        ]
        viols = qa_no_blank_controlled(course_rows, controlled_check, "course")
        if viols:
            print(f"\n  QA WARNINGS ({len(viols)} remaining blanks on controlled fields):")
            for v in viols[:20]:
                print(f"    {v}")
        else:
            print("  QA: no remaining blanks on controlled course fields ✓")

    FLAG_COLUMNS = [
        "journey_blocked", "journey_high_friction", "weak_external_findability",
        "accessibility_risk", "technical_risk", "information_fragmentation",
        "critical_student_pathway", "multi_phase_critical_case",
    ]

    if run_F:
        print("\n--- Step F: computing interpretive flags ---")
        course_rows = apply_interpretive_flags(course_rows, thresholds)

        # Extend fieldnames so DictWriter accepts the new flag columns
        for col in FLAG_COLUMNS:
            if col not in course_fields:
                course_fields.append(col)

        for flag in FLAG_COLUMNS:
            n = sum(1 for r in course_rows if r.get(flag, "0") == "1")
            print(f"  {flag}: {n}/{len(course_rows)}")

    if args.dry_run:
        print("\n[dry-run] no files written")
        return

    # -- Write --
    if run_D:
        _write_csv(COURSE_TMP, course_fields, course_rows)
        _write_csv(PAGE_TMP, page_fields, page_rows)
        _write_csv(ATENEO_TMP, ateneo_fields, ateneo_rows)
        print(f"\nWritten: {COURSE_TMP}, {PAGE_TMP}, {ATENEO_TMP}")

    if run_F:
        ANALYSIS_DIR.mkdir(parents=True, exist_ok=True)
        _write_csv(ANALYSIS_DIR / "audit_matrix.csv", course_fields, course_rows)
        _write_csv(ANALYSIS_DIR / "audit_matrix_page.csv", page_fields, page_rows)
        _write_csv(ANALYSIS_DIR / "audit_matrix_ateneo.csv", ateneo_fields, ateneo_rows)
        print(f"\nWritten to {ANALYSIS_DIR}/")


if __name__ == "__main__":
    main()
