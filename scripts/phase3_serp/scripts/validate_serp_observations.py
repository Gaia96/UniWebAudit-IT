"""
validate_serp_observations.py
QA checks on data/collection/serp_observations.csv.

Checks:
  1. Required fields are not empty
  2. serp_observation_id values are unique
  3. crawl_run_id starts with CR on every row
  4. target_found=true rows have non-null target_rank_organic and target_result_url
  5. target_found=false rows have null/empty target_rank_organic
  6. target_found_top10 / target_found_top20 consistency:
       - if target_found_top10=true then target_found=true
       - if max_organic_depth_observed=10 then target_found_top20 should be null or same as top10
  7. target_match_type uses the approved vocabulary
  8. query_type uses the approved vocabulary
  9. Every course_id is in course_sample_master.csv
  10. evidence_capture_path exists on disk (warns, does not error, if marked [pending])
  11. observed_at is parseable as ISO 8601 datetime
  12. Warns about courses with no observation rows yet

Run from the repository root:
  python serp/scripts/validate_serp_observations.py
"""

import csv
import sys
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
OBS_FILE = REPO_ROOT / "data/collection/serp_observations.csv"
COURSE_MASTER = REPO_ROOT / "data/masters/course_sample_master.csv"

# All these fields must be non-empty in the canonical observations table
REQUIRED_FIELDS = [
    "crawl_run_id", "serp_observation_id", "course_id", "university_id",
    "query_template_id", "query_type", "query_string", "search_engine",
    "search_interface", "hl", "gl", "browser_mode", "login_status",
    "device_profile", "viewport_width", "observed_at",
    "max_organic_depth", "target_found", "target_match_type",
    "canonical_course_url", "ads_observed", "evidence_capture_path",
]

VALID_MATCH_TYPES = {
    "canonical_exact", "canonical_normalized", "official_equivalent",
    "official_related", "official_domain_only", "third_party_related",
    "ambiguous", "not_found",
}

VALID_QUERY_TYPES = {
    "known_institution", "user_like_institutional", "information_seeking",
    "generic_visibility",
}


def load_csv(path: Path) -> list[dict]:
    with open(path, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def parse_bool(val: str) -> bool | None:
    if val.strip().lower() in ("true", "1", "yes"):
        return True
    if val.strip().lower() in ("false", "0", "no"):
        return False
    return None


def is_null(val: str) -> bool:
    return val.strip().lower() in ("null", "", "none")


def main() -> int:
    errors: list[str] = []
    warnings: list[str] = []

    if not OBS_FILE.exists():
        print(f"[ERROR] {OBS_FILE} not found.", file=sys.stderr)
        return 1

    rows = load_csv(OBS_FILE)

    if not rows:
        print("[INFO] serp_observations.csv is empty (header only). Nothing to validate.")
        return 0

    known_courses: set[str] = set()
    if COURSE_MASTER.exists():
        for r in load_csv(COURSE_MASTER):
            known_courses.add(r["sample_course_id"])

    seen_obs_ids: set[str] = set()
    observed_courses: set[str] = set()

    for i, row in enumerate(rows, start=2):
        obs_id = row.get("serp_observation_id", "").strip()
        course_id = row.get("course_id", "").strip()
        prefix = f"Row {i} ({obs_id or '?'})"

        # 1. Required fields
        for field in REQUIRED_FIELDS:
            if not row.get(field, "").strip():
                errors.append(f"{prefix}: missing required field '{field}'")

        # 2. Unique obs ID
        if obs_id:
            if obs_id in seen_obs_ids:
                errors.append(f"{prefix}: duplicate serp_observation_id '{obs_id}'")
            seen_obs_ids.add(obs_id)

        # 3. crawl_run_id format
        crid = row.get("crawl_run_id", "").strip()
        if crid and not crid.startswith("CR"):
            warnings.append(f"{prefix}: crawl_run_id '{crid}' does not start with 'CR'")

        # 4+5. target_found consistency with ranks
        target_found = parse_bool(row.get("target_found", ""))
        rank_organic = row.get("target_rank_organic", "").strip()
        result_url = row.get("target_result_url", "").strip()
        target_found_raw = row.get("target_found", "").strip()

        if target_found is True:
            if is_null(rank_organic):
                errors.append(f"{prefix}: target_found=true but target_rank_organic is null/empty")
            if not result_url:
                errors.append(f"{prefix}: target_found=true but target_result_url is empty")
        elif target_found is False:
            if not is_null(rank_organic):
                errors.append(
                    f"{prefix}: target_found=false but target_rank_organic='{rank_organic}'"
                )
        elif target_found_raw:
            errors.append(f"{prefix}: target_found value '{target_found_raw}' is not true/false")

        # 6. target_found_top10 / target_found_top20 consistency
        tf_top10 = parse_bool(row.get("target_found_top10", ""))
        tf_top20 = parse_bool(row.get("target_found_top20", ""))
        depth_obs = row.get("max_organic_depth_observed", "").strip()

        if tf_top10 is True and target_found is not True:
            errors.append(
                f"{prefix}: target_found_top10=true but target_found is not true"
            )
        if depth_obs == "10" and tf_top20 is not None:
            warnings.append(
                f"{prefix}: max_organic_depth_observed=10 but target_found_top20 is set "
                f"('{row.get('target_found_top20')}') — expected null when depth was 10"
            )

        # 7. target_match_type vocabulary
        match_type = row.get("target_match_type", "").strip()
        if match_type and match_type not in VALID_MATCH_TYPES:
            errors.append(
                f"{prefix}: target_match_type '{match_type}' not in approved vocabulary. "
                f"Valid: {sorted(VALID_MATCH_TYPES)}"
            )

        # 8. query_type vocabulary
        query_type = row.get("query_type", "").strip()
        if query_type and query_type not in VALID_QUERY_TYPES:
            warnings.append(
                f"{prefix}: query_type '{query_type}' not in approved vocabulary. "
                f"Valid: {sorted(VALID_QUERY_TYPES)}"
            )

        # 9. Known course
        if course_id and known_courses and course_id not in known_courses:
            errors.append(
                f"{prefix}: course_id '{course_id}' not found in course_sample_master.csv"
            )
        if course_id:
            observed_courses.add(course_id)

        # 10. Evidence path
        evpath = row.get("evidence_capture_path", "").strip()
        if evpath and evpath.lower() not in ("[pending]", "", "null"):
            full_path = REPO_ROOT / evpath
            if not full_path.exists():
                warnings.append(
                    f"{prefix}: evidence_capture_path '{evpath}' does not exist on disk"
                )

        # 11. observed_at
        obs_at = row.get("observed_at", "").strip()
        if obs_at:
            try:
                datetime.fromisoformat(obs_at)
            except ValueError:
                errors.append(
                    f"{prefix}: observed_at '{obs_at}' is not a valid ISO 8601 datetime"
                )

    # 12. Missing courses
    if known_courses:
        missing = known_courses - observed_courses
        if missing:
            warnings.append(
                f"No observations yet for {len(missing)} course(s): "
                + ", ".join(sorted(missing))
            )

    # Report
    print("\n=== SERP Observations Validation ===")
    print(f"Rows checked:                {len(rows)}")
    print(f"Unique serp_observation_ids: {len(seen_obs_ids)}")
    print(f"Courses with observations:   {len(observed_courses)} / {len(known_courses)}")

    if errors:
        print(f"\nERRORS ({len(errors)}):")
        for e in errors:
            print(f"  [ERROR] {e}")
    else:
        print("\nNo errors found.")

    if warnings:
        print(f"\nWARNINGS ({len(warnings)}):")
        for w in warnings:
            print(f"  [WARN]  {w}")
    else:
        print("No warnings.")

    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
