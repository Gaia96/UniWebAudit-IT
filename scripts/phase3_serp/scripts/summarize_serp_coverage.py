"""
summarize_serp_coverage.py
Coverage report for SERP observations.

Reads:
  - data/collection/serp_observations.csv
  - serp/manifests/serp_query_manifest.csv
  - data/masters/course_sample_master.csv
  - data/masters/serp_query_templates.csv

Outputs to stdout:
  - Overall coverage (collected / planned), all templates are core
  - Per-query-type coverage
  - Per-university coverage
  - List of missing targets
  - Target discovery rate (top10 vs top20)
  - match_type distribution

Run from the repository root:
  python serp/scripts/summarize_serp_coverage.py
"""

import csv
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
OBS_FILE = REPO_ROOT / "data/collection/serp_observations.csv"
MANIFEST = REPO_ROOT / "serp/manifests/serp_query_manifest.csv"
COURSE_MASTER = REPO_ROOT / "data/masters/course_sample_master.csv"
TEMPLATE_MASTER = REPO_ROOT / "data/masters/serp_query_templates.csv"

QUERY_TYPE_MAP = {
    "SQ01": "known_institution",
    "SQ02": "user_like_institutional",
    "SQ03": "information_seeking",
}


def load_csv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with open(path, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def parse_bool(val: str) -> bool | None:
    v = val.strip().lower()
    if v in ("true", "1", "yes"):
        return True
    if v in ("false", "0", "no"):
        return False
    return None


def main() -> int:
    observations = load_csv(OBS_FILE)
    manifest_rows = load_csv(MANIFEST)
    courses = {r["sample_course_id"]: r for r in load_csv(COURSE_MASTER)}
    templates = {r["query_template_id"]: r for r in load_csv(TEMPLATE_MASTER)}

    all_course_ids = sorted(courses.keys())
    all_template_ids = sorted(templates.keys())

    # All targets are now core (pending), no optional distinction
    all_targets = [(cid, tid) for cid in all_course_ids for tid in all_template_ids]
    total_targets = len(all_targets)

    # Index observations by (course_id, query_template_id)
    observed: dict[tuple[str, str], list[dict]] = {}
    for row in observations:
        key = (row.get("course_id", ""), row.get("query_template_id", ""))
        observed.setdefault(key, []).append(row)

    collected_count = sum(1 for t in all_targets if t in observed)

    print("\n" + "=" * 60)
    print("SERP COVERAGE SUMMARY")
    print("=" * 60)
    print(f"\nTotal targets:       {total_targets:3d}  (41 courses × {len(all_template_ids)} templates)")
    print(f"Collected:           {collected_count:3d} / {total_targets}")
    print(f"Total obs rows:      {len(observations)}")

    # Per-template (query-type) breakdown
    print("\n--- Coverage by query template ---")
    for tid in all_template_ids:
        qt = QUERY_TYPE_MAP.get(tid, tid)
        targets = [(cid, tid) for cid in all_course_ids]
        done = sum(1 for t in targets if t in observed)
        print(f"  {tid} ({qt:28s}): {done:2d} / {len(all_course_ids)}")

    # Per-university coverage
    print("\n--- Coverage by university ---")
    uni_ids = sorted({c["university_id"] for c in courses.values()})
    for uid in uni_ids:
        courses_for_uni = [cid for cid, c in courses.items() if c["university_id"] == uid]
        targets = [(cid, tid) for cid in courses_for_uni for tid in all_template_ids]
        done = sum(1 for t in targets if t in observed)
        total = len(targets)
        bar = "█" * done + "░" * (total - done)
        print(f"  {uid}: {done:2d}/{total:2d} [{bar}]")

    # Missing targets
    missing = [t for t in all_targets if t not in observed]
    if missing:
        print(f"\n--- Missing targets ({len(missing)}) ---")
        for cid, tid in missing:
            course = courses.get(cid, {})
            qt = QUERY_TYPE_MAP.get(tid, tid)
            print(
                f"  {cid} / {tid} ({qt:28s}) "
                f"— {course.get('course_name', '?')} ({course.get('university_id', '?')})"
            )
    else:
        print("\n[OK] All targets collected.")

    # Discovery rates (only if observations exist)
    if observations:
        found = [r for r in observations if parse_bool(r.get("target_found", "")) is True]
        not_found = [r for r in observations if parse_bool(r.get("target_found", "")) is False]
        found_top10 = [r for r in observations if parse_bool(r.get("target_found_top10", "")) is True]
        found_top20_only = [
            r for r in observations
            if parse_bool(r.get("target_found_top10", "")) is False
            and parse_bool(r.get("target_found_top20", "")) is True
        ]

        print(f"\n--- Discovery rates ({len(observations)} collected observations) ---")
        pct = lambda n: f"{n/len(observations):.1%}" if observations else "—"
        print(f"  target_found=true:           {len(found):3d}  ({pct(len(found))})")
        print(f"  target_found=false:          {len(not_found):3d}  ({pct(len(not_found))})")
        print(f"  found in top 10 (top10=true):{len(found_top10):3d}  ({pct(len(found_top10))})")
        print(f"  found only in top 20:        {len(found_top20_only):3d}  ({pct(len(found_top20_only))})")

        # Per-query-type discovery
        print("\n--- Discovery by query type ---")
        for qt in ["known_institution", "user_like_institutional", "information_seeking"]:
            qt_rows = [r for r in observations if r.get("query_type", "") == qt]
            qt_found = sum(1 for r in qt_rows if parse_bool(r.get("target_found", "")) is True)
            if qt_rows:
                print(f"  {qt:30s}: {qt_found:3d}/{len(qt_rows):3d} found  ({qt_found/len(qt_rows):.1%})")

        # match_type distribution
        match_counts: dict[str, int] = {}
        for r in observations:
            mt = r.get("target_match_type", "").strip() or "(empty)"
            match_counts[mt] = match_counts.get(mt, 0) + 1
        if match_counts:
            print("\n--- target_match_type distribution ---")
            for mt, cnt in sorted(match_counts.items(), key=lambda x: -x[1]):
                print(f"  {mt:30s}: {cnt}")

    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
