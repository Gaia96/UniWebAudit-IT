"""
build_serp_manifest.py
Generate or update serp/manifests/serp_query_manifest.csv from master files.

Reads:
  - data/masters/course_sample_master.csv
  - data/masters/university_sample_master.csv
  - data/masters/serp_query_templates.csv
  - data/collection/source_document.csv  (to look up source_document_id per course)

Writes:
  - serp/manifests/serp_query_manifest.csv

Run from the repository root:
  python serp/scripts/build_serp_manifest.py

Options:
  --dry-run    Print the manifest to stdout without writing the file.
  --overwrite  Overwrite the existing manifest (default: skip if file exists and is non-empty).
"""

import argparse
import csv
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

COURSE_MASTER = REPO_ROOT / "data/masters/course_sample_master.csv"
UNI_MASTER = REPO_ROOT / "data/masters/university_sample_master.csv"
TEMPLATE_MASTER = REPO_ROOT / "data/masters/serp_query_templates.csv"
SOURCE_DOC = REPO_ROOT / "data/collection/source_document.csv"
OUTPUT = REPO_ROOT / "serp/manifests/serp_query_manifest.csv"

CITY_MAP = {
    "UNI01": "Bologna", "UNI02": "Padova", "UNI03": "Pisa", "UNI04": "Firenze",
    "UNI05": "Siena", "UNI06": "Torino", "UNI07": "Genova", "UNI08": "Milano",
    "UNI09": "Milano", "UNI10": "Varese", "UNI11": "Salerno", "UNI12": "Roma",
    "UNI13": "Palermo", "UNI14": "Perugia", "UNI15": "Urbino", "UNI16": "Online",
    "UNI17": "Rende", "UNI18": "Napoli", "UNI19": "Bergamo", "UNI20": "Trento",
}

# Substitutions for university name used in query strings.
# Removes typographic inner quotes and other characters unsuitable for search queries.
UNI_NAME_QUERY_OVERRIDES = {
    "UNI18": "Università degli Studi di Napoli Federico II",
}

# Substitutions for course name used in query strings.
# Use when the official course name contains metadata unsuitable for a realistic user query.
COURSE_NAME_QUERY_OVERRIDES = {
    "C022": "Corporate Communication e Media",  # full name includes interclasse parenthetical
}

DOMAIN_MAP = {
    "UNI01": "unibo.it", "UNI02": "unipd.it", "UNI03": "unipi.it",
    "UNI04": "unifi.it", "UNI05": "unisi.it", "UNI06": "unito.it",
    "UNI07": "unige.it", "UNI08": "unimib.it", "UNI09": "unimi.it",
    "UNI10": "uninsubria.it", "UNI11": "unisa.it", "UNI12": "uniroma3.it",
    "UNI13": "unipa.it", "UNI14": "unistrapg.it", "UNI15": "uniurb.it",
    "UNI16": "uninettunouniversity.net", "UNI17": "unical.it", "UNI18": "unina.it",
    "UNI19": "unibg.it", "UNI20": "unitn.it",
}

# Maps query_template_id to the analytical query_type classification.
QUERY_TYPE_MAP = {
    "SQ01": "known_institution",
    "SQ02": "user_like_institutional",
    "SQ03": "information_seeking",
}


def load_csv(path: Path) -> list[dict]:
    with open(path, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def build_query(template: str, course_name: str, university_name: str,
                short_name: str, degree_type: str, city: str) -> str:
    return (
        template
        .replace("{course_name}", course_name)
        .replace("{university_name}", university_name)
        .replace("{short_name}", short_name)
        .replace("{degree_type}", degree_type)
        .replace("{city}", city)
    )


def build_note(course: dict, template: dict, course_name_query: str,
               university_name_query: str, uni_id: str) -> str:
    notes = []
    original_course_name = course["course_name"]
    if course_name_query != original_course_name:
        notes.append(
            "course name abbreviated; full official name includes interclasse parenthetical "
            "retained in course_sample_master.csv"
        )
    if uni_id == "UNI18":
        notes.append("university name uses simplified form without typographic inner quotes")
    if "," in course_name_query:
        notes.append("course name contains commas")
    notes_from_course = course.get("notes", "")
    if "JS heavy" in notes_from_course or "Angular" in notes_from_course:
        notes.append("JS-heavy course portal")
    if course.get("selection_role") == "optional_cycle_unique" or course.get("selection_rationale", "").startswith("optional"):
        notes.append("optional course in sample (ciclo_unico)")
    if course.get("selection_priority") == "optional":
        if "optional course in sample" not in " ".join(notes):
            notes.append("optional course in sample")
    return "; ".join(notes)


def main(dry_run: bool = False, overwrite: bool = False) -> None:
    if OUTPUT.exists() and OUTPUT.stat().st_size > 100 and not overwrite and not dry_run:
        print(
            f"[SKIP] {OUTPUT} already exists and is non-empty. "
            "Use --overwrite to regenerate."
        )
        sys.exit(0)

    courses = load_csv(COURSE_MASTER)
    universities = {u["university_id"]: u for u in load_csv(UNI_MASTER)}
    templates = load_csv(TEMPLATE_MASTER)

    # Build course_id → source_document_id lookup (course_page or course_seed role)
    source_doc_map: dict[str, str] = {}
    if SOURCE_DOC.exists():
        for row in load_csv(SOURCE_DOC):
            cid = row.get("sample_course_id", "")
            role = row.get("page_role", "")
            if cid and role in ("course_page", "course_seed") and cid not in source_doc_map:
                source_doc_map[cid] = row["source_document_id"]

    rows = []
    counter = 1
    for course in courses:
        course_id = course["sample_course_id"]
        uni_id = course["university_id"]
        uni = universities.get(uni_id, {})
        short_name = uni.get("short_name", "")
        university_name = uni.get("university_name", "")
        university_name_query = UNI_NAME_QUERY_OVERRIDES.get(uni_id, university_name)
        course_name_query = COURSE_NAME_QUERY_OVERRIDES.get(course_id, course["course_name"])
        degree_type = course["degree_type"]
        city = CITY_MAP.get(uni_id, "")
        canonical_url = course["course_page_url"]
        domain = DOMAIN_MAP.get(uni_id, "")
        source_doc_id = source_doc_map.get(course_id, "[to_be_filled]")

        for tmpl in templates:
            tid = tmpl["query_template_id"]
            raw_template = tmpl["query_template"]
            query_string = build_query(
                raw_template, course_name_query, university_name_query,
                short_name, degree_type, city,
            )
            query_type = QUERY_TYPE_MAP.get(tid, tid)
            # All templates are core observations (collection_status=pending)
            status = "pending"
            note = build_note(course, tmpl, course_name_query, university_name_query, uni_id)

            rows.append({
                "serp_target_id": f"ST{counter:03d}",
                "course_id": course_id,
                "university_id": uni_id,
                "source_document_id": source_doc_id,
                "query_template_id": tid,
                "query_type": query_type,
                "query_string": query_string,
                "canonical_course_url": canonical_url,
                "university_domain": domain,
                "collection_status": status,
                "notes": note,
            })
            counter += 1

    fieldnames = [
        "serp_target_id", "course_id", "university_id", "source_document_id",
        "query_template_id", "query_type", "query_string", "canonical_course_url",
        "university_domain", "collection_status", "notes",
    ]

    if dry_run:
        writer = csv.DictWriter(sys.stdout, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
        print(f"\n[DRY RUN] {len(rows)} rows generated (not written to file).", file=sys.stderr)
        return

    with open(OUTPUT, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print(f"[OK] Written {len(rows)} rows to {OUTPUT}")
    template_counts = {}
    for r in rows:
        template_counts[r["query_template_id"]] = template_counts.get(r["query_template_id"], 0) + 1
    for tid, count in sorted(template_counts.items()):
        qt = QUERY_TYPE_MAP.get(tid, tid)
        print(f"  {tid} ({qt}): {count} rows")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Build serp_query_manifest.csv")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    main(dry_run=args.dry_run, overwrite=args.overwrite)
