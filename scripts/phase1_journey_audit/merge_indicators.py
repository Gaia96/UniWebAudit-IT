#!/usr/bin/env python3
"""
merge_indicators.py — Phase 1 supplementary merge (v2)

Auto-derives all orientation fields and onsite_search_present from existing data.
Only truly manual input needed: menu_clarity_score (20 values, one per university).

Sources:
  - parsed_course_indicators.csv      → HTML-parsed page fields (14 auto fields)
  - structural_indicators.csv         → 6/8 orientation items (Phase 4 data)
  - journey_matrix.csv               → onsite_search_present (internal_search_used)
  - parse_course_pages.py output     → orientation_description, orientation_multilingual
                                       (keyword detection, spot-check optional)
  - manual_menu_clarity.csv          → menu_clarity_score (20 rows, one per university)

Workflow:
  1. python3 phase1_journey_audit/parse_course_pages.py   (already done)
  2. python3 phase1_journey_audit/merge_indicators.py --generate-menu-sheet
     → writes data/collection/manual_menu_clarity.csv  (20 rows to fill)
  3. Fill menu_clarity_score in manual_menu_clarity.csv (0-3, one per university)
  4. python3 phase1_journey_audit/merge_indicators.py
     → patches course_raw.csv
  5. python3 phase5_matrix/scripts/build_audit_matrix.py --step D
"""

import argparse
import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AUTO_CSV       = ROOT / "data" / "collection" / "parsed_course_indicators.csv"
STRUCT_CSV     = ROOT / "data" / "collection" / "structural_indicators.csv"
JOURNEY_CSV    = ROOT / "data" / "collection" / "journey_matrix.csv"
UNI_CSV        = ROOT / "data" / "masters" / "university_sample_master.csv"
MANUAL_ORIENT  = ROOT / "data" / "collection" / "manual_review_orientation.csv"  # legacy
MENU_CSV       = ROOT / "data" / "collection" / "manual_menu_clarity.csv"
COURSE_TMP     = ROOT / "phase5_matrix" / "_tmp" / "course_raw.csv"

BLOCKED_PATH_TYPE = "failed"

# Maps orientation binary items (Phase 1) to the Phase 4 structural_indicators fields
# that can serve as proxy evidence.  At least one SI field being 'present' → item = 1.
STRUCT_ORIENTATION_MAP = {
    "orientation_requirements": ["admission_requirements_present", "admission_procedure_present"],
    "orientation_deadlines":    ["deadlines_present"],
    "orientation_fees":         ["fees_or_costs_present"],
    "orientation_contacts":     ["contacts_present"],
    "orientation_study_plan":   ["study_plan_present"],
    "orientation_careers":      ["career_outcomes_present"],
}

# HTML-parsed auto fields: parser_field → course_raw field
AUTO_FIELD_MAP = {
    "lang_declared":                   "lang_declared",
    "title_text":                      "title_text",
    "meta_description_present":        "meta_description_present",
    "canonical_present":               "canonical_present",
    "structured_data_course":          "structured_data_course",
    "structured_data_breadcrumb":      "structured_data_breadcrumb",
    "indexability_status":             "indexability_status",
    "skip_link_present":               "skip_link_present",
    "h1_present":                      "h1_present",
    "breadcrumb_present":              "breadcrumb_present",
    "accessibility_statement_present": "accessibility_statement_present",
    "missing_alt_count":               "missing_alt_count",
    "empty_link_count":                "empty_link_count",
    "form_label_issue_count":          "form_label_issue_count",
}

# Heuristic scores from parser → course_raw (validated by parser algorithm)
HEURISTIC_SCORE_MAP = {
    "title_quality_score_heuristic":             "title_quality_score",
    "meta_description_quality_score_heuristic":  "meta_description_quality_score",
    "heading_structure_score_heuristic":         "heading_structure_score",
}

# These fields may be populated by WAVE (more precise) or by the HTML parser (fallback).
# The parser value is used only when WAVE has not yet collected data for this course.
WAVE_ITEM_FIELDS = {"missing_alt_count", "empty_link_count", "form_label_issue_count"}


def load_csv_by_key(path: Path, key: str) -> dict[str, dict]:
    with path.open(encoding="utf-8") as fh:
        return {r[key]: r for r in csv.DictReader(fh)}


def load_course_rows() -> tuple[list[str], list[dict]]:
    with COURSE_TMP.open(encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        return list(reader.fieldnames or []), list(reader)


def write_course_rows(fieldnames: list[str], rows: list[dict]) -> None:
    with COURSE_TMP.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)


# ---------------------------------------------------------------------------
# Generate menu clarity sheet (20 rows, one per university)
# ---------------------------------------------------------------------------

def generate_menu_sheet(course_rows: list[dict]) -> None:
    unis = load_csv_by_key(UNI_CSV, "university_id")

    # Menu clarity is assessed at university level (the menu is shared across courses)
    from collections import defaultdict
    by_uni: dict[str, list[str]] = defaultdict(list)
    for r in course_rows:
        by_uni[r["university_id"]].append(r["sample_course_id"])

    seen = set()
    menu_rows = []
    for r in course_rows:
        uid = r["university_id"]
        if uid in seen:
            continue
        seen.add(uid)
        uni = unis.get(uid, {})
        menu_rows.append({
            "university_id":       uid,
            "university_name":     r.get("university_name", ""),
            "homepage_url":        uni.get("university_homepage_url", ""),
            "programmes_hub_url":  uni.get("programmes_hub_url", ""),
            "sample_course_ids":   " ".join(by_uni[uid]),
            "menu_clarity_score":  "",
            "notes":               "",
        })

    fields = ["university_id", "university_name", "homepage_url", "programmes_hub_url",
              "sample_course_ids", "menu_clarity_score", "notes"]
    with MENU_CSV.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        w.writerows(menu_rows)

    print(f"Generated: {MENU_CSV}")
    print(f"  {len(menu_rows)} universities — fill 'menu_clarity_score' (0-3) per row")
    print(f"  Open 'homepage_url' in browser to assess navigation clarity")
    print()
    print("  Rubric:")
    print("  0 = menu assente / non interpretabile per orientamento")
    print("  1 = etichette molto generiche, orientamento per tentativi")
    print("  2 = abbastanza chiaro ma con ambiguità")
    print("  3 = chiaramente task-oriented, percorso facilmente inferibile")


# ---------------------------------------------------------------------------
# Derive orientation items
# ---------------------------------------------------------------------------

def derive_orientation_from_struct(course_id: str, si: dict[str, dict]) -> dict[str, str]:
    """Derive 6/8 orientation items from structural_indicators."""
    s = si.get(course_id, {})
    result = {}
    for ori_field, si_fields in STRUCT_ORIENTATION_MAP.items():
        vals = [s.get(f, "") for f in si_fields]
        result[ori_field] = "1" if any(v == "present" for v in vals) else "0"
    return result


def derive_orientation_from_parser(course_id: str, auto: dict[str, dict]) -> dict[str, str]:
    """
    orientation_description and orientation_multilingual from keyword detection
    (stored in the legacy manual_review_orientation.csv if it exists, else use auto parser).
    """
    result = {}
    # Try legacy manual_review sheet first (has keyword hits)
    if MANUAL_ORIENT.exists():
        legacy = load_csv_by_key(MANUAL_ORIENT, "sample_course_id")
        row = legacy.get(course_id, {})
        result["orientation_description"] = row.get("orientation_description_FINAL", "")
        result["orientation_multilingual"] = row.get("orientation_multilingual_FINAL", "")
    return result


# ---------------------------------------------------------------------------
# Patch one course row
# ---------------------------------------------------------------------------

def patch_row(
    row: dict,
    auto_data: dict[str, dict],
    si: dict[str, dict],
    jm: dict[str, dict],
    menu_by_uni: dict[str, str],
) -> list[str]:
    cid = row["sample_course_id"]
    is_blocked = row.get("journey_path_type", "") == BLOCKED_PATH_TYPE
    changes = []

    def set_field(field: str, value: str, source: str) -> None:
        old = row.get(field, "")
        if value and value.strip() and value != old:
            row[field] = value
            changes.append(f"{field}: {repr(old)[:30]} → {repr(value)[:30]} [{source}]")

    auto = auto_data.get(cid, {})

    # -- HTML-parsed fields: apply even for blocked journeys (page HTML was still captured) --
    for auto_field, course_field in AUTO_FIELD_MAP.items():
        val = auto.get(auto_field, "").strip()
        if not val or val == "not_collected":
            continue
        if course_field in WAVE_ITEM_FIELDS:
            current = row.get(course_field, "").strip()
            if current not in ("not_collected", "", "blocked"):
                continue  # WAVE data exists, don't overwrite
        set_field(course_field, val, "parser")

    # -- Heuristic scores --
    for auto_field, course_field in HEURISTIC_SCORE_MAP.items():
        val = auto.get(auto_field, "").strip()
        if val:
            set_field(course_field, val, "heuristic")

    # -- onsite_search_present from journey_matrix --
    if is_blocked:
        set_field("onsite_search_present", "blocked", "journey_auto")
    else:
        isu = jm.get(cid, {}).get("internal_search_used", "").strip()
        if isu in ("0", "1"):
            set_field("onsite_search_present", isu, "journey_auto")

    # -- Orientation items from structural_indicators (6/8) --
    struct_ori = derive_orientation_from_struct(cid, si)
    for field, val in struct_ori.items():
        if is_blocked:
            # For blocked courses: content IS on page (page was captured);
            # structural Phase 4 assessed it independently → use the derived value
            set_field(field, val, "struct_phase4")
        else:
            set_field(field, val, "struct_phase4")

    # -- orientation_description and orientation_multilingual from keyword detection --
    kw_ori = derive_orientation_from_parser(cid, auto_data)
    for field in ("orientation_description", "orientation_multilingual"):
        val = kw_ori.get(field, "").strip()
        if val in ("0", "1"):
            set_field(field, val, "keyword_detect")

    # -- menu_clarity_score from manual sheet (per university) --
    uid = row.get("university_id", "")
    menu_score = menu_by_uni.get(uid, "").strip()
    if is_blocked:
        # menu can be assessed even for blocked courses (same university menu)
        pass
    if menu_score in ("0", "1", "2", "3"):
        set_field("menu_clarity_score", menu_score, "manual_menu")
    elif is_blocked and not menu_score:
        # leave as blocked (set by Step D) — do nothing
        pass

    # Recompute aggregate scores only when all 8 items are binary (0/1); skip partial data
    from phase1_journey_audit_items import ORIENTATION_ITEMS
    item_vals = [row.get(item, "").strip() for item in ORIENTATION_ITEMS]
    if all(v in ("0", "1") for v in item_vals):
        raw = sum(int(v) for v in item_vals)
        norm = round(raw / 8, 4)
        set_field("orientation_score_raw", str(raw), "derived")
        set_field("orientation_score_norm", str(norm), "derived")

    return changes


ORIENTATION_ITEMS = [
    "orientation_description", "orientation_requirements", "orientation_deadlines",
    "orientation_fees", "orientation_contacts", "orientation_multilingual",
    "orientation_study_plan", "orientation_careers",
]


def patch_row_fixed(
    row: dict,
    auto_data: dict[str, dict],
    si: dict[str, dict],
    jm: dict[str, dict],
    menu_by_uni: dict[str, str],
) -> list[str]:
    cid = row["sample_course_id"]
    is_blocked = row.get("journey_path_type", "") == BLOCKED_PATH_TYPE
    changes = []

    def set_field(field: str, value: str, source: str) -> None:
        old = row.get(field, "")
        if value and value.strip() and value != old:
            row[field] = value
            changes.append(f"{field}: {repr(old)[:30]} → {repr(value)[:30]} [{source}]")

    auto = auto_data.get(cid, {})

    # -- HTML-parsed fields --
    for auto_field, course_field in AUTO_FIELD_MAP.items():
        val = auto.get(auto_field, "").strip()
        if not val or val == "not_collected":
            continue
        if course_field in WAVE_ITEM_FIELDS:
            current = row.get(course_field, "").strip()
            if current not in ("not_collected", "", "blocked"):
                continue
        set_field(course_field, val, "parser")

    # -- Heuristic scores --
    for auto_field, course_field in HEURISTIC_SCORE_MAP.items():
        val = auto.get(auto_field, "").strip()
        if val:
            set_field(course_field, val, "heuristic")

    # -- onsite_search_present --
    if is_blocked:
        set_field("onsite_search_present", "blocked", "journey_auto")
    else:
        isu = jm.get(cid, {}).get("internal_search_used", "").strip()
        if isu in ("0", "1"):
            set_field("onsite_search_present", isu, "journey_auto")

    # -- 6 orientation items from structural_indicators --
    struct_ori = derive_orientation_from_struct(cid, si)
    for field, val in struct_ori.items():
        set_field(field, val, "struct_phase4")

    # -- orientation_description and orientation_multilingual from keyword detection --
    if MANUAL_ORIENT.exists():
        legacy = load_csv_by_key(MANUAL_ORIENT, "sample_course_id")
        row_legacy = legacy.get(cid, {})
        for field in ("orientation_description", "orientation_multilingual"):
            val = row_legacy.get(f"{field}_FINAL", "").strip()
            if val in ("0", "1"):
                set_field(field, val, "keyword_detect")

    # -- menu_clarity_score --
    uid = row.get("university_id", "")
    menu_score = menu_by_uni.get(uid, "").strip()
    if menu_score in ("0", "1", "2", "3"):
        set_field("menu_clarity_score", menu_score, "manual_menu")

    # -- orientation_score_raw and _norm --
    item_vals = [row.get(item, "").strip() for item in ORIENTATION_ITEMS]
    if all(v in ("0", "1") for v in item_vals):
        raw = sum(int(v) for v in item_vals)
        norm = round(raw / 8, 4)
        set_field("orientation_score_raw", str(raw), "derived")
        set_field("orientation_score_norm", str(norm), "derived")

    return changes


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--generate-menu-sheet", action="store_true",
                        help="Only generate manual_menu_clarity.csv then exit")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    auto_data = load_csv_by_key(AUTO_CSV, "sample_course_id")
    si        = load_csv_by_key(STRUCT_CSV, "course_id")
    jm        = load_csv_by_key(JOURNEY_CSV, "sample_course_id")
    fieldnames, course_rows = load_course_rows()

    if args.generate_menu_sheet:
        generate_menu_sheet(course_rows)
        return

    # Load menu scores
    menu_by_uni: dict[str, str] = {}
    if MENU_CSV.exists():
        with MENU_CSV.open(encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                score = r.get("menu_clarity_score", "").strip()
                if score:
                    menu_by_uni[r["university_id"]] = score
        filled = sum(1 for v in menu_by_uni.values() if v)
        print(f"menu_clarity_score: {filled}/20 universities filled")
    else:
        print(f"WARNING: {MENU_CSV} not found.")
        print("Run: python3 phase1_journey_audit/merge_indicators.py --generate-menu-sheet")
        print("Then fill the file and re-run without --generate-menu-sheet")

    # Patch rows
    total_changes = 0
    for row in course_rows:
        changes = patch_row_fixed(row, auto_data, si, jm, menu_by_uni)
        if changes:
            total_changes += len(changes)
            cid = row["sample_course_id"]
            for c in changes:
                print(f"  {cid}  {c}")

    print(f"\nTotal field updates: {total_changes}")

    if args.dry_run:
        print("[dry-run] no files written")
        return

    write_course_rows(fieldnames, course_rows)
    print(f"Written: {COURSE_TMP}")
    print("\nNext: python3 phase5_matrix/scripts/build_audit_matrix.py --step D")


if __name__ == "__main__":
    main()
