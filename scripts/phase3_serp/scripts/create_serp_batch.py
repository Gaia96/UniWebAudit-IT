"""
create_serp_batch.py
Create a SERP collection batch: pre-filled observation template + evidence directory.

Selects courses from the manifest (collection_status=pending), includes ALL 3 core
query templates per selected course, writes a pre-filled CSV for manual completion.

Usage (from repo root):
  python serp/scripts/create_serp_batch.py --n 3
  python serp/scripts/create_serp_batch.py --courses C001 C002 C003
  python serp/scripts/create_serp_batch.py --n 10 --batch-id MY_PILOT

Outputs:
  serp/batches/{batch_id}/
  ├── batch_info.yaml              metadata + checklist
  ├── batch_observations.csv       pre-filled template — YOU fill the empty columns
  └── batch_results_long.csv       empty template for individual SERP results (optional)

  artifacts/runs/{batch_id}/serp/ evidence capture directory (put screenshots here)

Import after collection:
  python serp/scripts/validate_serp_batch.py --batch-id {batch_id}
  python serp/scripts/import_serp_batch.py   --batch-id {batch_id}
"""

import argparse
import csv
import sys
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

MANIFEST = REPO_ROOT / "serp/manifests/serp_query_manifest.csv"
OBS_CANONICAL = REPO_ROOT / "data/collection/serp_observations.csv"
BATCHES_DIR = REPO_ROOT / "serp/batches"
ARTIFACTS_RUNS = REPO_ROOT / "artifacts/runs"

# These columns are copied directly from the manifest; modifying them would break the import crosswalk
PREFILLED = [
    "course_id", "university_id", "source_document_id",
    "query_template_id", "query_type", "query_string",
    "search_engine", "search_interface", "hl", "gl",
    "browser_mode", "login_status", "device_profile", "viewport_width",
    "max_organic_depth", "canonical_course_url",
]

# Columns the user must fill in during/after collection
USER_FIELDS = [
    "crawl_run_id",          # register CRxxx in crawl_run.csv first; fill same value for all rows in one session
    "serp_observation_id",   # leave blank — auto-assigned on import (or fill SOBS-format manually)
    "observed_at",           # ISO 8601 with timezone, e.g. 2026-05-10T14:32:00+02:00
    "max_organic_depth_observed",  # 10 (default) or 20 if follow-up was needed
    "target_found",          # true / false
    "target_found_top10",    # true / false
    "target_found_top20",    # true / false / null (null if depth stayed at 10)
    "target_rank_organic",   # integer 1–10 (or 1–20) or null
    "target_rank_absolute",  # integer or null
    "target_result_title",   # title as shown in SERP; empty if not found
    "target_result_url",     # URL as shown in SERP; empty if not found
    "target_match_type",     # canonical_exact | canonical_normalized | official_equivalent |
                             # official_related | official_domain_only | third_party_related |
                             # ambiguous | not_found
    "serp_features_observed", # none | featured_snippet | knowledge_panel | people_also_ask | ...
    "ads_observed",          # true / false
    "evidence_capture_path", # artifacts/runs/{batch_id}/serp/{batch_id}_r{row:03d}_top10.png
    "notes",                 # anomalies, deviations, observations
]

OBS_FIELDNAMES = [
    "crawl_run_id", "serp_observation_id", "course_id", "university_id",
    "source_document_id", "query_template_id", "query_type", "query_string",
    "search_engine", "search_interface", "hl", "gl", "browser_mode",
    "login_status", "device_profile", "viewport_width", "observed_at",
    "max_organic_depth", "max_organic_depth_observed", "target_found",
    "target_found_top10", "target_found_top20", "target_rank_organic",
    "target_rank_absolute", "target_result_title", "target_result_url",
    "target_match_type", "canonical_course_url", "serp_features_observed",
    "ads_observed", "evidence_capture_path", "notes",
]

RESULTS_LONG_FIELDNAMES = [
    "crawl_run_id", "serp_observation_id", "course_id", "university_id",
    "query_template_id", "query_type", "query_string", "organic_rank",
    "absolute_rank", "result_title", "result_url", "result_domain", "snippet",
    "is_official_university_domain", "matches_target_course", "match_type",
    "evidence_capture_path", "notes",
]


def load_csv(path: Path) -> list[dict]:
    with open(path, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def next_batch_id() -> str:
    # Auto-increments from the highest existing SERP_Bxxx directory so batches never collide
    existing = sorted(BATCHES_DIR.glob("SERP_B*")) if BATCHES_DIR.exists() else []
    nums = []
    for p in existing:
        try:
            nums.append(int(p.name.split("_B")[1].split("_")[0]))
        except (IndexError, ValueError):
            pass
    n = (max(nums) + 1) if nums else 1
    return f"SERP_B{n:03d}"


def select_courses(manifest: list[dict], course_ids: list[str] | None,
                   n: int | None) -> list[str]:
    pending = [r for r in manifest if r.get("collection_status") == "pending"]
    # Unique course IDs in manifest order
    seen: set[str] = set()
    ordered: list[str] = []
    for r in pending:
        cid = r["course_id"]
        if cid not in seen:
            seen.add(cid)
            ordered.append(cid)

    if course_ids:
        unknown = set(course_ids) - seen
        if unknown:
            print(f"[WARN] These course IDs have no pending rows: {sorted(unknown)}")
        return [c for c in course_ids if c in seen]

    if n:
        return ordered[:n]

    print("[ERROR] Specify --courses or --n", file=sys.stderr)
    sys.exit(1)


def build_prefilled_row(manifest_row: dict, batch_id: str, row_idx: int) -> dict:
    evidence_placeholder = (
        f"artifacts/runs/{batch_id}/serp/"
        f"{batch_id}_r{row_idx:03d}_top10.png"
    )
    return {
        "crawl_run_id": "[FILL: register CRxxx in crawl_run.csv first]",
        "serp_observation_id": "[auto_on_import]",
        "course_id": manifest_row["course_id"],
        "university_id": manifest_row["university_id"],
        "source_document_id": manifest_row["source_document_id"],
        "query_template_id": manifest_row["query_template_id"],
        "query_type": manifest_row["query_type"],
        "query_string": manifest_row["query_string"],
        "search_engine": "Google",
        "search_interface": "google.it",
        "hl": "it",
        "gl": "IT",
        "browser_mode": "incognito",
        "login_status": "logged_out",
        "device_profile": "desktop",
        "viewport_width": "1536",
        "observed_at": "",
        "max_organic_depth": "10",
        "max_organic_depth_observed": "",
        "target_found": "",
        "target_found_top10": "",
        "target_found_top20": "",
        "target_rank_organic": "",
        "target_rank_absolute": "",
        "target_result_title": "",
        "target_result_url": "",
        "target_match_type": "",
        "canonical_course_url": manifest_row["canonical_course_url"],
        "serp_features_observed": "",
        "ads_observed": "",
        "evidence_capture_path": evidence_placeholder,
        "notes": "",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Create a SERP collection batch")
    grp = parser.add_mutually_exclusive_group(required=True)
    grp.add_argument("--courses", nargs="+", metavar="COURSE_ID",
                     help="Specific course IDs to include (e.g. C001 C002 C003)")
    grp.add_argument("--n", type=int, metavar="N",
                     help="Select first N pending courses from manifest")
    parser.add_argument("--batch-id", metavar="ID",
                        help="Batch identifier (default: auto SERP_Bxxx)")
    args = parser.parse_args()

    if not MANIFEST.exists():
        print(f"[ERROR] Manifest not found: {MANIFEST}", file=sys.stderr)
        sys.exit(1)

    manifest = load_csv(MANIFEST)
    batch_id = args.batch_id or next_batch_id()
    batch_dir = BATCHES_DIR / batch_id

    if batch_dir.exists():
        print(f"[ERROR] Batch directory already exists: {batch_dir}", file=sys.stderr)
        sys.exit(1)

    selected_courses = select_courses(manifest, args.courses, args.n)
    if not selected_courses:
        print("[ERROR] No pending courses found for selection.", file=sys.stderr)
        sys.exit(1)

    # Filter manifest rows for selected courses (all templates)
    selected_rows = [
        r for r in manifest
        if r["course_id"] in selected_courses
        and r.get("collection_status") == "pending"
    ]
    # Preserve manifest order within each course
    selected_rows.sort(key=lambda r: (
        selected_courses.index(r["course_id"]),
        r["query_template_id"],
    ))

    # Create directories
    batch_dir.mkdir(parents=True)
    evidence_dir = ARTIFACTS_RUNS / batch_id / "serp"
    evidence_dir.mkdir(parents=True)

    # Write batch_observations.csv
    obs_path = batch_dir / "batch_observations.csv"
    with open(obs_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=OBS_FIELDNAMES)
        writer.writeheader()
        for idx, mrow in enumerate(selected_rows, start=1):
            writer.writerow(build_prefilled_row(mrow, batch_id, idx))

    # Write batch_results_long.csv (empty template)
    long_path = batch_dir / "batch_results_long.csv"
    with open(long_path, "w", encoding="utf-8", newline="") as f:
        csv.DictWriter(f, fieldnames=RESULTS_LONG_FIELDNAMES).writeheader()

    # Write batch_info.yaml
    info_path = batch_dir / "batch_info.yaml"
    info_path.write_text(
        f"batch_id: {batch_id}\n"
        f"created_at: {datetime.now().isoformat(timespec='seconds')}\n"
        f"courses_selected: {len(selected_courses)}\n"
        f"total_rows: {len(selected_rows)}\n"
        f"course_ids: [{', '.join(selected_courses)}]\n"
        f"collection_status: pre_collection\n"
        f"crawl_run_id: '[ASSIGN before collection — register in crawl_run.csv]'\n"
        f"\n"
        f"workflow:\n"
        f"  1. Assign CRxxx in data/collection/crawl_run.csv\n"
        f"  2. Fill crawl_run_id in batch_observations.csv (all rows, same value)\n"
        f"  3. Collect SERP observations per serp_collection_protocol.md\n"
        f"  4. Fill remaining columns in batch_observations.csv\n"
        f"  5. Optionally fill batch_results_long.csv\n"
        f"  6. Run: python serp/scripts/validate_serp_batch.py --batch-id {batch_id}\n"
        f"  7. Run: python serp/scripts/import_serp_batch.py --batch-id {batch_id}\n"
        f"  8. Run: python serp/scripts/summarize_serp_coverage.py\n"
        f"\n"
        f"paths:\n"
        f"  batch_dir: serp/batches/{batch_id}/\n"
        f"  observations_template: serp/batches/{batch_id}/batch_observations.csv\n"
        f"  results_long_template: serp/batches/{batch_id}/batch_results_long.csv\n"
        f"  evidence_dir: artifacts/runs/{batch_id}/serp/\n",
        encoding="utf-8",
    )

    print(f"\n[OK] Batch created: {batch_id}")
    print(f"     Courses ({len(selected_courses)}): {', '.join(selected_courses)}")
    print(f"     Rows in template: {len(selected_rows)}")
    print(f"\n     Fill in:  serp/batches/{batch_id}/batch_observations.csv")
    print(f"     Evidence: artifacts/runs/{batch_id}/serp/")
    print(f"\n     User-fillable columns:")
    for f in USER_FIELDS:
        print(f"       - {f}")
    print(f"\n     Next steps:")
    print(f"       python serp/scripts/validate_serp_batch.py --batch-id {batch_id}")
    print(f"       python serp/scripts/import_serp_batch.py   --batch-id {batch_id}")


if __name__ == "__main__":
    main()
