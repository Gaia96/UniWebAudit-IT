#!/usr/bin/env python3
"""
WAVE Browser Extension Import Script

Reads a filled-in WVRUN_browser_001_template.yaml and appends compatible rows
to data/collection/wave_results.csv and data/collection/wave_items_long.csv.

Refuses to run if any required field still contains the sentinel value FILL_IN.

Usage:
    python wave/scripts/wave_browser_import.py
    python wave/scripts/wave_browser_import.py --dry-run
    python wave/scripts/wave_browser_import.py --template wave/browser_fallback/WVRUN_browser_001_template.yaml

Requirements:
    pip install pyyaml
"""

import argparse
import csv
import logging
import shutil
from datetime import datetime, timezone
from pathlib import Path

try:
    import yaml
except ImportError:
    raise ImportError("pyyaml required: pip install pyyaml")

ROOT = Path(__file__).resolve().parents[2]

RESULTS_FIELDNAMES = [
    "crawl_run_id", "target_id", "source_document_id", "page_role",
    "requested_url", "returned_pageurl", "http_status", "wave_success",
    "tool_name", "tool_mode", "tool_version", "reporttype", "audit_date",
    "viewport_policy", "viewportwidth", "useragent_profile", "evaldelay_ms",
    "pagetitle", "aimscore", "allitemcount", "totalelements", "error_count",
    "contrast_count", "alert_count", "feature_count", "structure_count",
    "aria_count", "raw_json_path", "notes",
]

ITEMS_FIELDNAMES = [
    "crawl_run_id", "target_id", "category", "item_id",
    "item_description", "item_count", "selector_or_xpath_available", "raw_json_path",
]

# Any field still containing this string means the YAML template has not been completed
SENTINEL = "FILL_IN"

REQUIRED_RESULT_FIELDS = [
    "returned_pageurl", "http_status", "wave_success", "tool_version",
    "audit_date", "viewport_width", "pagetitle", "allitemcount",
    "error_count", "contrast_count", "alert_count",
    "feature_count", "structure_count", "aria_count",
]

REQUIRED_ITEM_FIELDS = ["category", "item_id", "description", "count"]


def check_sentinel(value: object, path: str) -> None:
    if str(value).strip() == SENTINEL:
        raise ValueError(f"Unfilled field: {path} is still '{SENTINEL}'. Fill in all values before importing.")


def validate_target(t: dict) -> None:
    tid = t.get("wave_target_id", "?")
    for field in REQUIRED_RESULT_FIELDS:
        check_sentinel(t.get(field, SENTINEL), f"targets[{tid}].{field}")
    for i, item in enumerate(t.get("items", [])):
        for field in REQUIRED_ITEM_FIELDS:
            check_sentinel(item.get(field, SENTINEL), f"targets[{tid}].items[{i}].{field}")


def build_result_row(t: dict, run_id: str, tool_name: str) -> dict:
    return {
        "crawl_run_id": run_id,
        "target_id": t["wave_target_id"],
        "source_document_id": t["source_document_id"],
        "page_role": t["page_role"],
        "requested_url": t["requested_url"],
        "returned_pageurl": t.get("returned_pageurl", ""),
        "http_status": t.get("http_status", ""),
        "wave_success": t.get("wave_success", ""),
        "tool_name": tool_name,
        "tool_mode": "browser_extension",
        "tool_version": t.get("tool_version", ""),
        "reporttype": "",
        "audit_date": t.get("audit_date", ""),
        "viewport_policy": "manual_browser",
        "viewportwidth": t.get("viewport_width", ""),
        "useragent_profile": "chrome_desktop",
        "evaldelay_ms": "",
        "pagetitle": t.get("pagetitle", ""),
        "aimscore": t.get("aimscore", ""),
        "allitemcount": t.get("allitemcount", ""),
        "totalelements": t.get("totalelements", ""),
        "error_count": t.get("error_count", ""),
        "contrast_count": t.get("contrast_count", ""),
        "alert_count": t.get("alert_count", ""),
        "feature_count": t.get("feature_count", ""),
        "structure_count": t.get("structure_count", ""),
        "aria_count": t.get("aria_count", ""),
        "raw_json_path": "",
        "notes": t.get("notes", "browser_extension manual collection"),
    }


def build_item_rows(t: dict, run_id: str) -> list:
    rows = []
    for item in t.get("items", []):
        # Skip placeholder blocks that weren't filled
        if any(str(item.get(f, SENTINEL)).strip() == SENTINEL
               for f in ["item_id", "description", "count"]):
            continue
        rows.append({
            "crawl_run_id": run_id,
            "target_id": t["wave_target_id"],
            "category": item["category"],
            "item_id": item["item_id"],
            "item_description": item.get("description", ""),
            "item_count": item.get("count", ""),
            "selector_or_xpath_available": item.get("selector_available", False),
            "raw_json_path": "",
        })
    return rows


def backup_csv(path: Path) -> Path:
    if not path.exists():
        return path
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = path.with_name(f"{path.stem}.pre_browser_import.{ts}.csv")
    shutil.copy2(path, backup)
    logging.info(f"Backup: {backup.relative_to(ROOT)}")
    return backup


def append_rows(rows: list, path: Path, fieldnames: list) -> None:
    write_header = not path.exists() or path.stat().st_size == 0
    with open(path, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        if write_header:
            writer.writeheader()
        writer.writerows(rows)


def check_duplicates(target_ids: list, results_path: Path) -> None:
    # Prevents double-importing the same collection run, which would corrupt aggregates
    if not results_path.exists():
        return
    existing = {r["target_id"] for r in csv.DictReader(
        open(results_path, newline="", encoding="utf-8")
    )}
    dupes = set(target_ids) & existing
    if dupes:
        raise ValueError(
            f"These target_ids are already in wave_results.csv: {dupes}\n"
            "Delete the existing rows or use a different run_id before importing."
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="Import WAVE browser extension results")
    parser.add_argument(
        "--template",
        default=str(ROOT / "wave" / "browser_fallback" / "WVRUN_browser_001_template.yaml"),
        help="Path to the filled-in YAML template",
    )
    parser.add_argument("--dry-run", action="store_true", help="Validate only; do not write")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    template_path = Path(args.template)
    if not template_path.exists():
        raise FileNotFoundError(f"Template not found: {template_path}")

    with open(template_path, encoding="utf-8") as f:
        data = yaml.safe_load(f)

    run_id = data["run_id"]
    tool_name = data["tool_name"]
    targets = data["targets"]

    logging.info(f"Template: {template_path.relative_to(ROOT)}")
    logging.info(f"Run ID: {run_id} | Targets: {len(targets)}")

    for t in targets:
        validate_target(t)
    logging.info("Validation OK — no FILL_IN sentinels found in required fields")

    results_path = ROOT / "data" / "collection" / "wave_results.csv"
    items_path = ROOT / "data" / "collection" / "wave_items_long.csv"

    target_ids = [t["wave_target_id"] for t in targets]
    check_duplicates(target_ids, results_path)

    result_rows = [build_result_row(t, run_id, tool_name) for t in targets]
    item_rows = [row for t in targets for row in build_item_rows(t, run_id)]

    logging.info(f"Built {len(result_rows)} result rows, {len(item_rows)} item rows")

    if args.dry_run:
        logging.info("DRY RUN — no files modified")
        for r in result_rows:
            logging.info(f"  result: {r['target_id']} | errors={r['error_count']} | items={r['allitemcount']}")
        for r in item_rows:
            logging.info(f"  item:   {r['target_id']} | {r['category']}.{r['item_id']} | count={r['item_count']}")
        return

    backup_csv(results_path)
    backup_csv(items_path)

    append_rows(result_rows, results_path, RESULTS_FIELDNAMES)
    append_rows(item_rows, items_path, ITEMS_FIELDNAMES)

    result_total = sum(1 for _ in open(results_path, encoding="utf-8")) - 1
    items_total = sum(1 for _ in open(items_path, encoding="utf-8")) - 1
    logging.info(f"Done. wave_results.csv: {result_total} rows | wave_items_long.csv: {items_total} rows")


if __name__ == "__main__":
    main()
