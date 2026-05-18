"""
validate_serp_batch.py
Validate a compiled SERP batch before import.

Usage (from repo root):
  python serp/scripts/validate_serp_batch.py --batch-id SERP_B001
  python serp/scripts/validate_serp_batch.py --batch-id SERP_B001 --verbose

Exit codes:
  0  no errors (warnings may still be present)
  1  one or more errors — do not import until resolved
"""

import argparse
import csv
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
BATCHES_DIR = REPO_ROOT / "serp/batches"
MANIFEST = REPO_ROOT / "serp/manifests/serp_query_manifest.csv"
OBS_CANONICAL = REPO_ROOT / "data/collection/serp_observations.csv"

# Every field listed here must be filled before the batch can be imported
REQUIRED_FILLED = [
    "crawl_run_id", "course_id", "university_id", "query_template_id",
    "query_type", "query_string", "search_engine", "search_interface",
    "hl", "gl", "browser_mode", "login_status", "device_profile",
    "viewport_width", "observed_at", "max_organic_depth",
    "max_organic_depth_observed", "target_found", "target_found_top10",
    "target_match_type", "canonical_course_url", "ads_observed",
    "evidence_capture_path",
]

# Placeholders that indicate the user has not filled a field
PLACEHOLDERS = {
    "[auto_on_import]", "[to_be_filled]",
    "[fill: register crxxx in crawl_run.csv first]",
    "[fill:", "",
}

VALID_MATCH_TYPES = {
    "canonical_exact", "canonical_normalized", "official_equivalent",
    "official_related", "official_domain_only", "third_party_related",
    "ambiguous", "not_found",
}

# Only these three match types justify target_found=true — anything else is partial or negative
FULL_MATCH_TYPES = {"canonical_exact", "canonical_normalized", "official_equivalent"}

VALID_QUERY_TYPES = {
    "known_institution", "user_like_institutional",
    "information_seeking", "generic_visibility",
}


def load_csv(path: Path) -> list[dict]:
    with open(path, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def is_placeholder(val: str) -> bool:
    return val.strip().lower() in PLACEHOLDERS or val.strip().lower().startswith("[fill")


def parse_bool(val: str) -> bool | None:
    v = val.strip().lower()
    if v in ("true", "1", "yes"):
        return True
    if v in ("false", "0", "no"):
        return False
    return None


def is_null(val: str) -> bool:
    return val.strip().lower() in ("null", "", "none")


def existing_obs_ids() -> set[str]:
    if not OBS_CANONICAL.exists():
        return set()
    rows = load_csv(OBS_CANONICAL)
    return {r.get("serp_observation_id", "").strip() for r in rows if r.get("serp_observation_id")}


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate a SERP batch before import")
    parser.add_argument("--batch-id", required=True, metavar="ID")
    parser.add_argument("--verbose", action="store_true",
                        help="Show all checks, not just errors/warnings")
    args = parser.parse_args()

    batch_dir = BATCHES_DIR / args.batch_id
    obs_path = batch_dir / "batch_observations.csv"
    long_path = batch_dir / "batch_results_long.csv"

    if not batch_dir.exists():
        print(f"[ERROR] Batch not found: {batch_dir}", file=sys.stderr)
        return 1
    if not obs_path.exists():
        print(f"[ERROR] batch_observations.csv not found in {batch_dir}", file=sys.stderr)
        return 1

    rows = load_csv(obs_path)
    existing_ids = existing_obs_ids()

    errors: list[str] = []
    warnings: list[str] = []

    if not rows:
        print("[WARN] batch_observations.csv is empty.")
        return 0

    # Load manifest for cross-check
    manifest_index: dict[tuple[str, str], dict] = {}
    if MANIFEST.exists():
        for r in load_csv(MANIFEST):
            manifest_index[(r["course_id"], r["query_template_id"])] = r

    seen_obs_ids: set[str] = set()
    crawl_run_ids: set[str] = set()

    for i, row in enumerate(rows, start=2):
        obs_id = row.get("serp_observation_id", "").strip()
        prefix = f"Row {i} ({obs_id or '?'})"

        # 1. Required fields filled (not placeholder)
        for field in REQUIRED_FILLED:
            val = row.get(field, "")
            if not val.strip() or is_placeholder(val):
                errors.append(f"{prefix}: '{field}' is empty or still a placeholder")

        # 2. crawl_run_id format
        crid = row.get("crawl_run_id", "").strip()
        if crid and not is_placeholder(crid):
            if not crid.startswith("CR"):
                warnings.append(f"{prefix}: crawl_run_id '{crid}' does not start with 'CR'")
            crawl_run_ids.add(crid)

        # 3. serp_observation_id — can be [auto_on_import] or a real SOBS value
        if obs_id and obs_id != "[auto_on_import]":
            if obs_id in seen_obs_ids:
                errors.append(f"{prefix}: duplicate serp_observation_id '{obs_id}' within batch")
            if obs_id in existing_ids:
                errors.append(
                    f"{prefix}: serp_observation_id '{obs_id}' already exists in "
                    "serp_observations.csv — will cause duplicate on import"
                )
            seen_obs_ids.add(obs_id)

        # 4. target_found / match_type consistency
        target_found = parse_bool(row.get("target_found", ""))
        match_type = row.get("target_match_type", "").strip()

        if match_type and match_type not in VALID_MATCH_TYPES:
            errors.append(
                f"{prefix}: target_match_type '{match_type}' not in approved vocabulary. "
                f"Valid: {sorted(VALID_MATCH_TYPES)}"
            )
        elif match_type:
            if target_found is True and match_type not in FULL_MATCH_TYPES:
                errors.append(
                    f"{prefix}: target_found=true but match_type='{match_type}' is not a "
                    f"full match. Full match types: {sorted(FULL_MATCH_TYPES)}"
                )
            if target_found is False and match_type in FULL_MATCH_TYPES:
                errors.append(
                    f"{prefix}: target_found=false but match_type='{match_type}' is a full match "
                    "— contradiction"
                )

        # 5. target_rank consistency with target_found
        rank_organic = row.get("target_rank_organic", "").strip()
        result_url = row.get("target_result_url", "").strip()

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

        # 6. target_found_top10 / target_found_top20 / max_organic_depth_observed consistency
        tf_top10 = parse_bool(row.get("target_found_top10", ""))
        tf_top20 = parse_bool(row.get("target_found_top20", ""))
        depth_obs = row.get("max_organic_depth_observed", "").strip()

        if tf_top10 is True and target_found is not True:
            errors.append(f"{prefix}: target_found_top10=true but target_found is not true")

        if depth_obs == "10":
            if not is_null(row.get("target_found_top20", "")):
                warnings.append(
                    f"{prefix}: max_organic_depth_observed=10 but target_found_top20 is set "
                    f"('{row.get('target_found_top20')}') — expected null when depth was 10"
                )
        elif depth_obs == "20":
            if tf_top20 is None:
                warnings.append(
                    f"{prefix}: max_organic_depth_observed=20 but target_found_top20 is empty"
                )

        # 7. query_type vocabulary
        qt = row.get("query_type", "").strip()
        if qt and qt not in VALID_QUERY_TYPES:
            warnings.append(f"{prefix}: query_type '{qt}' not in approved vocabulary")

        # 8. evidence path exists (warn, not error, for png)
        evpath = row.get("evidence_capture_path", "").strip()
        if evpath and not is_placeholder(evpath):
            # Check top10 path
            full = REPO_ROOT / evpath
            if not full.exists():
                warnings.append(f"{prefix}: evidence_capture_path not found on disk: {evpath}")

        # 9. Warn on ambiguous match_type
        if match_type == "ambiguous":
            warnings.append(
                f"{prefix}: target_match_type=ambiguous — resolve before finalising analysis"
            )

        # 10. Cross-check against manifest
        mkey = (row.get("course_id", ""), row.get("query_template_id", ""))
        if mkey not in manifest_index:
            warnings.append(
                f"{prefix}: ({mkey[0]}, {mkey[1]}) not found in manifest — unexpected row"
            )

    # Multi-session warning
    if len(crawl_run_ids) > 1:
        warnings.append(
            f"Multiple crawl_run_ids in batch: {sorted(crawl_run_ids)}. "
            "Multi-session collection is acceptable if each row has correct observed_at."
        )

    # Optional: validate results_long if present and non-empty
    if long_path.exists():
        long_rows = load_csv(long_path)
        if long_rows:
            long_errors = 0
            for i, r in enumerate(long_rows, start=2):
                for field in ["crawl_run_id", "course_id", "query_template_id",
                              "organic_rank", "result_url", "result_domain"]:
                    if not r.get(field, "").strip():
                        errors.append(f"[results_long] Row {i}: missing '{field}'")
                        long_errors += 1
            if args.verbose:
                print(f"[INFO] batch_results_long.csv: {len(long_rows)} rows checked")

    # Summary
    print(f"\n=== Batch Validation: {args.batch_id} ===")
    print(f"Rows checked:  {len(rows)}")
    print(f"Crawl run(s):  {sorted(crawl_run_ids) if crawl_run_ids else '[not filled]'}")

    if errors:
        print(f"\nERRORS ({len(errors)}) — fix before import:")
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

    if not errors:
        print(f"\n[READY] Batch {args.batch_id} can be imported.")
        print(f"  python serp/scripts/import_serp_batch.py --batch-id {args.batch_id}")

    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
