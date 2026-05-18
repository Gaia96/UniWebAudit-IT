#!/usr/bin/env python3
"""
build_extraction_manifest.py — Phase 4 Step 3 helper.

Builds structural_extraction/extraction_manifest.csv (41 rows, one per course).

Source of truth for the canonical SD per course (decision D2):
    lhci_collect/lighthouse_target_manifest.csv  (rows where page_role=course_page)

For each course:
- joins LH manifest with data/collection/source_document.csv to resolve storage_path
- joins data/collection/journey_matrix.csv to read js_dependency_level_preaudit
- assigns render_mode according to D3:
    - browser_rendered if js_dependency_level_preaudit in {medium, high}
    - raw_http otherwise
- expected_artifact_path:
    - raw_http      -> existing static HTML in artifacts/journeys/Jxxx/source/SDxxxx.html
                       (preferred per methodology) with fallback to artifacts/runs/CRxxx/SDxxxx.html
    - browser_rendered -> artifacts/runs/STRUN_001/source_rendered/Cxxx.html
                          (file does NOT yet exist; produced by browser_render_capture.py)

Outputs:
    structural_extraction/extraction_manifest.csv
    structural_extraction/logs/build_extraction_manifest.log

Run:
    python3 structural_extraction/scripts/build_extraction_manifest.py
    python3 structural_extraction/scripts/build_extraction_manifest.py --strun STRUN_002

Dependencies: stdlib only.
"""

from __future__ import annotations

import argparse
import csv
import logging
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

LH_MANIFEST = REPO_ROOT / "lhci_collect/lighthouse_target_manifest.csv"
SOURCE_DOC = REPO_ROOT / "data/collection/source_document.csv"
JOURNEY_MATRIX = REPO_ROOT / "data/collection/journey_matrix.csv"
COURSE_MASTER = REPO_ROOT / "data/masters/course_sample_master.csv"

OUT_MANIFEST = REPO_ROOT / "structural_extraction/extraction_manifest.csv"
LOG_DIR = REPO_ROOT / "structural_extraction/logs"

MANIFEST_FIELDS = [
    "course_id",
    "university_id",
    "journey_id",
    "source_document_id",
    "target_url",
    "static_html_path",
    "render_mode",
    "js_dependency_level_preaudit",
    "expected_artifact_path",
    "rendered_artifact_path",
    "rendered_screenshot_path",
    "rendered_log_path",
    "rendered_capture_status",
    "rendered_captured_at",
    "rendered_dom_sha256",
    "notes",
]


def load_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--strun", default="STRUN_001",
                    help="extraction_run_id used to scope rendered artifact paths")
    args = ap.parse_args()

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_path = LOG_DIR / "build_extraction_manifest.log"
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[logging.FileHandler(log_path, mode="w"), logging.StreamHandler()],
    )

    # The sample has exactly 41 courses; any deviation means the LH manifest is incomplete
    lh_rows = [r for r in load_csv(LH_MANIFEST) if r.get("page_role") == "course_page"]
    if len(lh_rows) != 41:
        logging.error("Expected 41 LH course_page rows, found %d", len(lh_rows))
        return 1
    sd_by_id = {r["source_document_id"]: r for r in load_csv(SOURCE_DOC)}
    jm_by_course = {r["sample_course_id"]: r for r in load_csv(JOURNEY_MATRIX)}
    course_master = {r["sample_course_id"]: r for r in load_csv(COURSE_MASTER)}

    rows: list[dict[str, str]] = []
    errors = 0
    for lh in sorted(lh_rows, key=lambda r: r["sample_course_id"]):
        cid = lh["sample_course_id"]
        sd_id = lh["source_document_id"]
        jid = lh["journey_id"]
        uni = lh["university_id"]
        sd = sd_by_id.get(sd_id)
        if sd is None:
            logging.error("[%s] LH points to unknown SD %s", cid, sd_id)
            errors += 1
            continue
        jm = jm_by_course.get(cid)
        if jm is None:
            logging.error("[%s] missing journey_matrix row", cid)
            errors += 1
            continue
        js_level = jm.get("js_dependency_level_preaudit", "").strip()

        # Static HTML path: prefer artifacts/journeys/Jxxx/source/SDxxxx.html
        course_slug = next(
            (p.name for p in (REPO_ROOT / "artifacts/journeys").glob(f"{jid}_*")),
            None,
        )
        static_journey = (
            REPO_ROOT / "artifacts/journeys" / course_slug / "source" / f"{sd_id}.html"
            if course_slug else None
        )
        static_run = REPO_ROOT / sd.get("storage_path", "")
        if static_journey and static_journey.exists():
            static_html_path = str(static_journey.relative_to(REPO_ROOT))
        elif static_run.exists():
            static_html_path = str(static_run.relative_to(REPO_ROOT))
        else:
            logging.error("[%s] no static HTML found for SD %s", cid, sd_id)
            errors += 1
            static_html_path = ""

        # Decision D3: JS-heavy portals need a headless browser render; others use the static HTML snapshot
        render_mode = "browser_rendered" if js_level in ("medium", "high") else "raw_http"
        rendered_path = (
            f"artifacts/runs/{args.strun}/source_rendered/{cid}.html"
            if render_mode == "browser_rendered" else ""
        )
        rendered_screenshot = (
            f"artifacts/runs/{args.strun}/screenshots/{cid}.png"
            if render_mode == "browser_rendered" else ""
        )
        rendered_log = (
            f"artifacts/runs/{args.strun}/logs/{cid}.json"
            if render_mode == "browser_rendered" else ""
        )
        expected = rendered_path if render_mode == "browser_rendered" else static_html_path
        notes = []
        if render_mode == "browser_rendered":
            notes.append(f"js_dependency={js_level}")
        if course_master.get(cid, {}).get("notes"):
            notes.append(f"course_master_notes={course_master[cid]['notes'][:80]}")

        rows.append({
            "course_id": cid,
            "university_id": uni,
            "journey_id": jid,
            "source_document_id": sd_id,
            "target_url": lh.get("tested_url") or sd.get("url", ""),
            "static_html_path": static_html_path,
            "render_mode": render_mode,
            "js_dependency_level_preaudit": js_level,
            "expected_artifact_path": expected,
            "rendered_artifact_path": rendered_path,
            "rendered_screenshot_path": rendered_screenshot,
            "rendered_log_path": rendered_log,
            "rendered_capture_status": "pending" if render_mode == "browser_rendered" else "n_a",
            "rendered_captured_at": "",
            "rendered_dom_sha256": "",
            "notes": "; ".join(notes),
        })

    if errors:
        logging.error("Aborting: %d errors during build", errors)
        return 2

    OUT_MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    with OUT_MANIFEST.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=MANIFEST_FIELDS)
        w.writeheader()
        w.writerows(rows)

    rendered = sum(1 for r in rows if r["render_mode"] == "browser_rendered")
    logging.info("Wrote %s with %d rows (%d browser_rendered, %d raw_http) at %s",
                 OUT_MANIFEST.relative_to(REPO_ROOT), len(rows), rendered,
                 len(rows) - rendered, datetime.now(timezone.utc).isoformat())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
