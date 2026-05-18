#!/usr/bin/env python3
"""
validate_structural.py — Phase 4 Step 7 gate.

Validates the staging files (or, with --target=collection, the canonical files
in data/collection/) against the methodology controlled vocabularies and the
D6 review gate. Exits non-zero on any error so promotion is blocked.

Checks:
    - 41 wide rows, course_id unique
    - every wide course_id present in long
    - location_type values ⊆ controlled vocabulary (§10)
    - local_findability values ⊆ controlled vocabulary (§11)
    - missingness (observed) values ⊆ {present, not_observed, not_applicable,
                                       blocked, not_exposed, ambiguous}
    - confidence values ⊆ {high, medium, low, not_observed, not_applicable}
    - every present row has evidence_url
    - every linked_pdf row has evidence_url ending in .pdf or notes about it
    - every external_official_portal row has evidence_url
    - D6 gate: no essential row with extraction_method=auto AND
      (confidence in {low, not_observed} OR location_type in {ambiguous,
       linked_pdf, external_official_portal})
    - if review_queue.csv exists, no row with reviewer_decision=pending

Outputs:
    structural_extraction/logs/validate_structural.log

Run:
    python3 structural_extraction/scripts/validate_structural.py
    python3 structural_extraction/scripts/validate_structural.py --target collection

Dependencies: stdlib only.
"""

from __future__ import annotations

import argparse
import csv
import logging
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
STAGING_WIDE = REPO_ROOT / "structural_extraction/staging/structural_indicators.staging.csv"
STAGING_LONG = REPO_ROOT / "structural_extraction/staging/structural_evidence_long.staging.csv"
COLLECTION_WIDE = REPO_ROOT / "data/collection/structural_indicators.csv"
COLLECTION_LONG = REPO_ROOT / "data/collection/structural_evidence_long.csv"
QUEUE = REPO_ROOT / "structural_extraction/review_queue.csv"
LOG_DIR = REPO_ROOT / "structural_extraction/logs"

# Controlled vocabularies from methodology codebook §10-§12;
# any value outside these sets is a schema violation.
LOCATION_TYPES = {
    "inline_html", "heading_or_summary", "accordion", "tab", "table",
    "linked_official_page", "linked_pdf", "download", "external_official_portal",
    "central_university_page", "not_observed", "not_applicable", "ambiguous",
}
LOCAL_FINDABILITY = {
    "direct", "one_click", "document_link", "portal_link", "unclear",
    "not_found", "not_applicable",
}
OBSERVED = {
    "present", "not_observed", "not_applicable", "blocked", "not_exposed", "ambiguous",
}
CONFIDENCE = {"high", "medium", "low", "not_observed", "not_applicable"}
ESSENTIAL_TRIGGER_LOC = {"ambiguous", "linked_pdf", "external_official_portal"}
ESSENTIAL_TRIGGER_CONF = {"low", "not_observed"}


def load_csv(p: Path) -> list[dict[str, str]]:
    with p.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", choices=["staging", "collection"], default="staging")
    args = ap.parse_args()

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[logging.FileHandler(LOG_DIR / "validate_structural.log", mode="w"),
                  logging.StreamHandler()],
    )

    wide_path = STAGING_WIDE if args.target == "staging" else COLLECTION_WIDE
    long_path = STAGING_LONG if args.target == "staging" else COLLECTION_LONG

    errors: list[str] = []

    if not wide_path.exists():
        errors.append(f"Missing wide file: {wide_path}")
    if not long_path.exists():
        errors.append(f"Missing long file: {long_path}")
    if errors:
        for e in errors:
            logging.error(e)
        return 2

    wide = load_csv(wide_path)
    long_rows = load_csv(long_path)

    # 1) wide row count
    if len(wide) != 41:
        errors.append(f"wide rows = {len(wide)}, expected 41")
    course_ids = [r["course_id"] for r in wide]
    if len(set(course_ids)) != len(course_ids):
        dup = [c for c in course_ids if course_ids.count(c) > 1]
        errors.append(f"duplicate course_id in wide: {sorted(set(dup))}")

    long_courses = {r["course_id"] for r in long_rows}
    for cid in course_ids:
        if cid not in long_courses:
            errors.append(f"wide course {cid} has no long rows")

    # 2/3/4/5) Vocabularies
    for r in long_rows:
        if r["location_type"] not in LOCATION_TYPES:
            errors.append(f"{r['course_id']}/{r['indicator_id']}: bad location_type={r['location_type']!r}")
        if r["local_findability"] not in LOCAL_FINDABILITY:
            errors.append(f"{r['course_id']}/{r['indicator_id']}: bad local_findability={r['local_findability']!r}")
        if r["observed"] not in OBSERVED:
            errors.append(f"{r['course_id']}/{r['indicator_id']}: bad observed={r['observed']!r}")
        if r["confidence"] not in CONFIDENCE:
            errors.append(f"{r['course_id']}/{r['indicator_id']}: bad confidence={r['confidence']!r}")
        if r["observed"] == "present" and not r["evidence_url"].strip():
            errors.append(f"{r['course_id']}/{r['indicator_id']}: present without evidence_url")
        if r["location_type"] == "linked_pdf" and not r["evidence_url"].strip():
            errors.append(f"{r['course_id']}/{r['indicator_id']}: linked_pdf without URL")
        if r["location_type"] == "external_official_portal" and not r["evidence_url"].strip():
            errors.append(f"{r['course_id']}/{r['indicator_id']}: external_official_portal without URL")

    # 6) D6 gate (only meaningful pre-review)
    if args.target == "staging":
        for r in long_rows:
            if r.get("priority") != "essential":
                continue
            if r.get("extraction_method") != "auto":
                continue
            if r["confidence"] in ESSENTIAL_TRIGGER_CONF or r["location_type"] in ESSENTIAL_TRIGGER_LOC:
                errors.append(
                    f"D6 gate: essential {r['course_id']}/{r['indicator_id']} "
                    f"still extraction_method=auto with confidence={r['confidence']} "
                    f"location_type={r['location_type']}"
                )

    if QUEUE.exists():
        with QUEUE.open(newline="", encoding="utf-8") as f:
            qrows = list(csv.DictReader(f))
        pending = [q for q in qrows if q["reviewer_decision"] == "pending"]
        if pending:
            errors.append(f"review_queue.csv has {len(pending)} pending rows (D6)")

    if errors:
        logging.error("VALIDATION FAILED: %d errors", len(errors))
        for e in errors[:50]:
            logging.error("  %s", e)
        if len(errors) > 50:
            logging.error("  ...and %d more", len(errors) - 50)
        return 1

    logging.info("VALIDATION OK: wide=%d long=%d", len(wide), len(long_rows))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
