#!/usr/bin/env python3
"""
browser_render_capture.py — Phase 4 Step 4 (D3, D4).

Captures rendered DOM + screenshot + console/network logs for the 8 JS-heavy
course pages flagged in extraction_manifest.csv (render_mode=browser_rendered).

Tooling (D4): Playwright headless Chromium, viewport 1536x960,
              wait for `networkidle` + 2s buffer, no automatic interaction.

Outputs (per course):
    artifacts/runs/<STRUN>/source_rendered/<Cxxx>.html
    artifacts/runs/<STRUN>/screenshots/<Cxxx>.png
    artifacts/runs/<STRUN>/logs/<Cxxx>.json   (console + network errors)

Side effects:
    Updates structural_extraction/extraction_manifest.csv columns
        rendered_capture_status, rendered_captured_at, rendered_dom_sha256
    using a row-by-row in-place rewrite.

Run:
    python3 structural_extraction/scripts/browser_render_capture.py
    python3 structural_extraction/scripts/browser_render_capture.py --strun STRUN_001 --only C035,C036

Dependencies: playwright (`pip install playwright && python -m playwright install chromium`).
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
MANIFEST = REPO_ROOT / "structural_extraction/extraction_manifest.csv"
LOG_DIR = REPO_ROOT / "structural_extraction/logs"

VIEWPORT = {"width": 1536, "height": 960}  # desktop viewport (1536px matches most audit tools)
WAIT_BUFFER_MS = 2000    # extra wait after networkidle to allow deferred JS rendering
NAV_TIMEOUT_MS = 60_000  # 60 s before aborting; some university portals are slow


def load_manifest() -> tuple[list[dict[str, str]], list[str]]:
    with MANIFEST.open(newline="", encoding="utf-8") as f:
        r = csv.DictReader(f)
        return list(r), r.fieldnames or []


def write_manifest(rows: list[dict[str, str]], fields: list[str]) -> None:
    # Write to a temp file then rename atomically to avoid a partial manifest on crash
    tmp = MANIFEST.with_suffix(".csv.tmp")
    with tmp.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)
    tmp.replace(MANIFEST)


def capture_one(page, url: str, dom_path: Path, screenshot_path: Path, log_path: Path) -> dict:
    console_msgs: list[dict] = []
    network_errors: list[dict] = []

    def on_console(msg):
        try:
            console_msgs.append({"type": msg.type, "text": msg.text})
        except Exception:
            pass

    def on_request_failed(req):
        network_errors.append({"url": req.url, "failure": str(req.failure)})

    page.on("console", on_console)
    page.on("requestfailed", on_request_failed)

    response = page.goto(url, wait_until="networkidle", timeout=NAV_TIMEOUT_MS)
    page.wait_for_timeout(WAIT_BUFFER_MS)

    html = page.content()
    dom_path.parent.mkdir(parents=True, exist_ok=True)
    dom_path.write_text(html, encoding="utf-8")
    screenshot_path.parent.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(screenshot_path), full_page=True)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text(json.dumps({
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "final_url": page.url,
        "http_status": response.status if response else None,
        "console": console_msgs,
        "network_errors": network_errors,
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    return {
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "dom_sha256": hashlib.sha256(html.encode("utf-8")).hexdigest(),
        "final_url": page.url,
        "http_status": response.status if response else None,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--strun", default="STRUN_001")
    ap.add_argument("--only", default="", help="comma-separated course_ids (optional filter)")
    args = ap.parse_args()

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[logging.FileHandler(LOG_DIR / "browser_render_capture.log", mode="w"),
                  logging.StreamHandler()],
    )

    rows, fields = load_manifest()
    targets = [r for r in rows if r.get("render_mode") == "browser_rendered"]
    if args.only:
        wanted = {c.strip() for c in args.only.split(",") if c.strip()}
        targets = [r for r in targets if r["course_id"] in wanted]
    if not targets:
        logging.warning("No browser_rendered targets to capture (filter applied: %s)", args.only or "none")
        return 0

    logging.info("Capturing %d targets with %s", len(targets), args.strun)

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        logging.error("playwright not installed. See structural_extraction/requirements.txt")
        return 3

    failed = 0
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport=VIEWPORT, locale="it-IT")
        page = context.new_page()
        for r in targets:
            cid = r["course_id"]
            url = r["target_url"]
            dom_path = REPO_ROOT / r["rendered_artifact_path"]
            shot_path = REPO_ROOT / r["rendered_screenshot_path"]
            log_path = REPO_ROOT / r["rendered_log_path"]
            try:
                logging.info("[%s] capturing %s", cid, url)
                meta = capture_one(page, url, dom_path, shot_path, log_path)
                r["rendered_capture_status"] = "captured"
                r["rendered_captured_at"] = meta["captured_at"]
                r["rendered_dom_sha256"] = meta["dom_sha256"]
                logging.info("[%s] OK status=%s sha=%s", cid, meta["http_status"], meta["dom_sha256"][:12])
            except Exception as exc:
                logging.exception("[%s] capture FAILED: %s", cid, exc)
                r["rendered_capture_status"] = f"error:{type(exc).__name__}"
                r["rendered_captured_at"] = datetime.now(timezone.utc).isoformat()
                failed += 1
        browser.close()

    write_manifest(rows, fields)
    logging.info("Manifest updated. failed=%d/%d", failed, len(targets))
    return 0 if failed == 0 else 4


if __name__ == "__main__":
    raise SystemExit(main())
