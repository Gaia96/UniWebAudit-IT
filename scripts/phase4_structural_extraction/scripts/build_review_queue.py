#!/usr/bin/env python3
"""
build_review_queue.py — Phase 4 Step 6 (D6 trigger).

Reads the staging long file produced by extract_structural.py and emits
structural_extraction/review_queue.csv listing every essential indicator that
must be human-reviewed before promotion to data/collection/.

D6 trigger (any one is sufficient):
    - priority == essential AND confidence in {low, not_observed}
    - priority == essential AND location_type in {ambiguous, linked_pdf,
                                                  external_official_portal}
    - course is an outlier with >= --essential-missing-threshold (default 3)
      essential indicators in {not_observed, low}; in that case ALL essential
      rows for that course enter the queue

Outputs:
    structural_extraction/review_queue.csv   (overwritten on rerun, with
                                              backup of any previous file)
    structural_extraction/logs/build_review_queue.log

Run:
    python3 structural_extraction/scripts/build_review_queue.py
    python3 structural_extraction/scripts/build_review_queue.py --essential-missing-threshold 4

Dependencies: stdlib only.
"""

from __future__ import annotations

import argparse
import csv
import logging
import shutil
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
STAGING_LONG = REPO_ROOT / "structural_extraction/staging/structural_evidence_long.staging.csv"
MANIFEST = REPO_ROOT / "structural_extraction/extraction_manifest.csv"
QUEUE = REPO_ROOT / "structural_extraction/review_queue.csv"
LOG_DIR = REPO_ROOT / "structural_extraction/logs"

QUEUE_FIELDS = [
    "course_id", "university_id", "source_document_id", "indicator_id",
    "indicator_label", "priority", "trigger_reason",
    "auto_observed", "auto_location_type", "auto_local_findability",
    "auto_confidence", "auto_evidence_text", "auto_evidence_url",
    "auto_evidence_selector", "auto_evidence_document_type", "auto_notes",
    "evidence_artifact_path", "rendered_screenshot_path", "target_url",
    "reviewer_decision",  # pending | confirmed | corrected | cannot_resolve
    "reviewer_observed", "reviewer_location_type", "reviewer_local_findability",
    "reviewer_confidence", "reviewer_evidence_text", "reviewer_evidence_url",
    "reviewer_notes", "reviewer_id", "reviewed_at",
]

ESSENTIAL_TRIGGERS = {"low", "not_observed"}
ESSENTIAL_LOCATION_TRIGGERS = {"ambiguous", "linked_pdf", "external_official_portal"}


def load_long() -> list[dict[str, str]]:
    with STAGING_LONG.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def load_manifest_index() -> dict[str, dict[str, str]]:
    with MANIFEST.open(newline="", encoding="utf-8") as f:
        return {r["course_id"]: r for r in csv.DictReader(f)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--essential-missing-threshold", type=int, default=3)
    args = ap.parse_args()

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[logging.FileHandler(LOG_DIR / "build_review_queue.log", mode="w"),
                  logging.StreamHandler()],
    )

    if not STAGING_LONG.exists():
        logging.error("Staging long missing: %s", STAGING_LONG)
        return 2

    rows = load_long()
    manifest = load_manifest_index()

    by_course: dict[str, list[dict[str, str]]] = {}
    for r in rows:
        by_course.setdefault(r["course_id"], []).append(r)

    queue_rows: list[dict[str, str]] = []
    for cid, course_rows in sorted(by_course.items()):
        essentials = [r for r in course_rows if r.get("priority") == "essential"]
        missing_count = sum(
            1 for r in essentials
            if r["confidence"] in ESSENTIAL_TRIGGERS
            or r["location_type"] in ESSENTIAL_LOCATION_TRIGGERS
        )
        outlier = missing_count >= args.essential_missing_threshold

        for r in essentials:
            triggers: list[str] = []
            if r["confidence"] in ESSENTIAL_TRIGGERS:
                triggers.append(f"confidence={r['confidence']}")
            if r["location_type"] in ESSENTIAL_LOCATION_TRIGGERS:
                triggers.append(f"location_type={r['location_type']}")
            if outlier:
                triggers.append(f"course_outlier(missing>={args.essential_missing_threshold})")
            if not triggers:
                continue

            mrow = manifest.get(cid, {})
            artifact_path = (mrow.get("rendered_artifact_path")
                             if mrow.get("render_mode") == "browser_rendered"
                             and mrow.get("rendered_capture_status") == "captured"
                             else mrow.get("static_html_path", ""))
            queue_rows.append({
                "course_id": cid,
                "university_id": r["university_id"],
                "source_document_id": r["source_document_id"],
                "indicator_id": r["indicator_id"],
                "indicator_label": r["indicator_label"],
                "priority": r["priority"],
                "trigger_reason": " | ".join(triggers),
                "auto_observed": r["observed"],
                "auto_location_type": r["location_type"],
                "auto_local_findability": r["local_findability"],
                "auto_confidence": r["confidence"],
                "auto_evidence_text": r["evidence_text"],
                "auto_evidence_url": r["evidence_url"],
                "auto_evidence_selector": r["evidence_selector"],
                "auto_evidence_document_type": r["evidence_document_type"],
                "auto_notes": r["notes"],
                "evidence_artifact_path": artifact_path,
                "rendered_screenshot_path": mrow.get("rendered_screenshot_path", ""),
                "target_url": mrow.get("target_url", ""),
                "reviewer_decision": "pending",
                "reviewer_observed": "",
                "reviewer_location_type": "",
                "reviewer_local_findability": "",
                "reviewer_confidence": "",
                "reviewer_evidence_text": "",
                "reviewer_evidence_url": "",
                "reviewer_notes": "",
                "reviewer_id": "",
                "reviewed_at": "",
            })

    if QUEUE.exists():
        backup = QUEUE.with_suffix(
            f".csv.bak.{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}")
        shutil.copy2(QUEUE, backup)
        logging.info("Backed up previous queue to %s", backup.name)

    with QUEUE.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=QUEUE_FIELDS)
        w.writeheader()
        w.writerows(queue_rows)

    logging.info("Wrote %s with %d items needing review", QUEUE.relative_to(REPO_ROOT), len(queue_rows))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
