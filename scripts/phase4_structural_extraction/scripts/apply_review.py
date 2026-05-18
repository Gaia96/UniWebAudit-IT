#!/usr/bin/env python3
"""
apply_review.py — Phase 4 Step 6 closer.

Reads structural_extraction/review_queue.csv (filled by the human reviewer)
and propagates each non-pending decision back into the staging long file:
    structural_extraction/staging/structural_evidence_long.staging.csv

Decision semantics:
    - confirmed       -> keep auto values; just stamp extraction_method=manual_confirmed
    - corrected       -> overwrite observed/location_type/local_findability/
                          confidence/evidence_text/evidence_url with reviewer_*
                          values; extraction_method=manual_review
    - cannot_resolve  -> set observed=ambiguous, confidence=low,
                         location_type=ambiguous; extraction_method=manual_cannot_resolve
                         AND require reviewer_notes (else fail)
    - pending         -> rejected; script exits non-zero so promotion (Step 7)
                         is blocked (D6 gate)

Side effect:
    Re-derives the staging wide file rows (present/location_type pairs) so they
    stay in sync with the corrected long rows.

Outputs:
    structural_extraction/staging/structural_evidence_long.staging.csv (rewritten)
    structural_extraction/staging/structural_indicators.staging.csv (rewritten)
    structural_extraction/logs/apply_review.log

Run:
    python3 structural_extraction/scripts/apply_review.py

Dependencies: stdlib only.
"""

from __future__ import annotations

import csv
import logging
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
QUEUE = REPO_ROOT / "structural_extraction/review_queue.csv"
STAGING_LONG = REPO_ROOT / "structural_extraction/staging/structural_evidence_long.staging.csv"
STAGING_WIDE = REPO_ROOT / "structural_extraction/staging/structural_indicators.staging.csv"
LOG_DIR = REPO_ROOT / "structural_extraction/logs"

VALID_DECISIONS = {"confirmed", "corrected", "cannot_resolve"}


def load_csv(p: Path) -> tuple[list[dict[str, str]], list[str]]:
    with p.open(newline="", encoding="utf-8") as f:
        r = csv.DictReader(f)
        return list(r), r.fieldnames or []


def write_csv(p: Path, rows: list[dict[str, str]], fields: list[str]) -> None:
    with p.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def main() -> int:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[logging.FileHandler(LOG_DIR / "apply_review.log", mode="w"),
                  logging.StreamHandler()],
    )

    if not QUEUE.exists():
        logging.error("Queue missing: %s", QUEUE)
        return 2
    if not STAGING_LONG.exists():
        logging.error("Staging long missing: %s", STAGING_LONG)
        return 2

    queue_rows, _ = load_csv(QUEUE)
    long_rows, long_fields = load_csv(STAGING_LONG)

    # D6 gate: every queue row must have a decision before the staging file can be promoted
    pending = [q for q in queue_rows if q["reviewer_decision"] == "pending"]
    invalid = [q for q in queue_rows if q["reviewer_decision"] not in (set(VALID_DECISIONS) | {"pending"})]
    # cannot_resolve decisions require notes so a future analyst understands why
    cannot_no_notes = [q for q in queue_rows
                       if q["reviewer_decision"] == "cannot_resolve" and not q["reviewer_notes"].strip()]

    if pending:
        logging.error("D6 gate violated: %d queue rows still pending", len(pending))
        for q in pending[:10]:
            logging.error("  pending: %s / %s", q["course_id"], q["indicator_id"])
        return 3
    if invalid:
        logging.error("Invalid reviewer_decision values in %d rows", len(invalid))
        for q in invalid[:10]:
            logging.error("  invalid: %s / %s -> %r",
                          q["course_id"], q["indicator_id"], q["reviewer_decision"])
        return 4
    if cannot_no_notes:
        logging.error("'cannot_resolve' rows missing reviewer_notes: %d", len(cannot_no_notes))
        for q in cannot_no_notes[:10]:
            logging.error("  no_notes: %s / %s", q["course_id"], q["indicator_id"])
        return 5

    queue_idx = {(q["course_id"], q["indicator_id"]): q for q in queue_rows}
    applied = 0
    for r in long_rows:
        key = (r["course_id"], r["indicator_id"])
        q = queue_idx.get(key)
        if not q:
            continue
        decision = q["reviewer_decision"]
        if decision == "confirmed":
            r["extraction_method"] = "manual_confirmed"
        elif decision == "corrected":
            for src, dst in [
                ("reviewer_observed", "observed"),
                ("reviewer_location_type", "location_type"),
                ("reviewer_local_findability", "local_findability"),
                ("reviewer_confidence", "confidence"),
                ("reviewer_evidence_text", "evidence_text"),
                ("reviewer_evidence_url", "evidence_url"),
            ]:
                v = q.get(src, "").strip()
                if v:
                    r[dst] = v
            r["extraction_method"] = "manual_review"
            r["notes"] = (r.get("notes", "") + f" | reviewer:{q.get('reviewer_notes', '')[:200]}").strip(" |")
        elif decision == "cannot_resolve":
            r["observed"] = "ambiguous"
            r["location_type"] = "ambiguous"
            r["local_findability"] = "unclear"
            r["confidence"] = "low"
            r["extraction_method"] = "manual_cannot_resolve"
            r["notes"] = (r.get("notes", "") + f" | cannot_resolve:{q.get('reviewer_notes', '')[:200]}").strip(" |")
        applied += 1

    write_csv(STAGING_LONG, long_rows, long_fields)
    logging.info("Applied %d reviewer decisions to staging long", applied)

    # Keep the wide (per-course summary) in sync with the corrected long (per-indicator detail)
    if STAGING_WIDE.exists():
        wide_rows, wide_fields = load_csv(STAGING_WIDE)
        widx = {r["course_id"]: r for r in wide_rows}
        for r in long_rows:
            cid = r["course_id"]
            iid = r["indicator_id"]
            present_col = f"{iid}_present"
            location_col = f"{iid}_location_type"
            if cid not in widx:
                continue
            if present_col in wide_fields:
                widx[cid][present_col] = "present" if r["observed"] == "present" else r["observed"]
            if location_col in wide_fields:
                widx[cid][location_col] = r["location_type"]
        write_csv(STAGING_WIDE, list(widx.values()), wide_fields)
        logging.info("Re-derived %s", STAGING_WIDE.relative_to(REPO_ROOT))
    else:
        logging.warning("Staging wide missing — re-run extract_structural.py to regenerate")

    logging.info("Done at %s", datetime.now(timezone.utc).isoformat())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
