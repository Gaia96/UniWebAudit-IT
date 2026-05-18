#!/usr/bin/env python3
"""
WAVE Item Extraction Script

Reads raw JSON files produced by wave_collect.py and extracts per-item
detail rows into data/collection/wave_items_long.csv (one row per
WAVE item type per target).

wave_collect.py already writes summary rows to wave_results.csv.
Run this script after collection to populate the long-format table.

Usage:
    python wave/scripts/wave_extract.py --run-id WVRUN_001
    python wave/scripts/wave_extract.py --run-id WVRUN_001 --target-ids WV_HOME_UNI01,WV_COURSE_C001
    python wave/scripts/wave_extract.py --run-id WVRUN_001 --overwrite

Requirements:
    pip install pyyaml
"""

import csv
import json
import argparse
import logging
from pathlib import Path

try:
    import yaml
except ImportError:
    raise ImportError("pyyaml required: pip install pyyaml")

ROOT = Path(__file__).resolve().parents[2]

ITEMS_FIELDNAMES = [
    "crawl_run_id",
    "target_id",
    "category",
    "item_id",
    "item_description",
    "item_count",
    "selector_or_xpath_available",
    "raw_json_path",
]


def load_config() -> dict:
    config_path = ROOT / "wave" / "config" / "wave_config.yaml"
    with open(config_path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def extract_items_from_json(
    raw_path: Path, run_id: str, wave_target_id: str
) -> list:
    rows = []
    try:
        data = json.loads(raw_path.read_text(encoding="utf-8"))
    except Exception as e:
        logging.error(f"[{wave_target_id}] Cannot parse {raw_path}: {e}")
        return rows

    if not data.get("status", {}).get("success"):
        logging.warning(
            f"[{wave_target_id}] wave_success=False in raw JSON — skipping item extraction"
        )
        return rows

    rel_path = str(raw_path.relative_to(ROOT))
    categories = data.get("categories", {})

    for cat_name, cat_data in categories.items():
        items = cat_data.get("items", {})
        if not isinstance(items, dict):
            # WAVE API returns [] when a category has 0 items and {} when items are present;
            # any other type is unexpected and should be skipped with a warning.
            if items:
                logging.warning(
                    f"[{wave_target_id}] category '{cat_name}': "
                    f"'items' is {type(items).__name__} (expected dict) — skipping"
                )
            continue
        for item_id, item_data in items.items():
            xpaths = item_data.get("xpaths", [])
            selectors = item_data.get("selectors", [])
            # True when the API has returned DOM location data — useful for manual triage
            has_locations = bool(xpaths or selectors)
            rows.append(
                {
                    "crawl_run_id": run_id,
                    "target_id": wave_target_id,
                    "category": cat_name,
                    "item_id": item_id,
                    "item_description": item_data.get("description", ""),
                    "item_count": item_data.get("count", ""),
                    "selector_or_xpath_available": has_locations,
                    "raw_json_path": rel_path,
                }
            )

    return rows


def write_items(rows: list, items_path: Path, overwrite: bool = False) -> None:
    if overwrite:
        mode = "w"
        write_header = True
    else:
        mode = "a"
        write_header = not items_path.exists() or items_path.stat().st_size == 0

    with open(items_path, mode, newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=ITEMS_FIELDNAMES, extrasaction="ignore")
        if write_header:
            writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Extract per-item WAVE detail to wave_items_long.csv"
    )
    parser.add_argument(
        "--run-id", required=True,
        help="Crawl run ID matching the raw JSON directory, e.g. WVRUN_001"
    )
    parser.add_argument(
        "--target-ids",
        help="Comma-separated wave_target_id filter"
    )
    parser.add_argument(
        "--overwrite", action="store_true",
        help="Overwrite wave_items_long.csv instead of appending"
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    config = load_config()
    raw_run_dir = ROOT / config["paths"]["raw_output_dir"] / args.run_id

    if not raw_run_dir.exists():
        raise FileNotFoundError(
            f"Raw output directory not found: {raw_run_dir}\n"
            f"Run wave_collect.py with --run-id {args.run_id} first."
        )

    filter_ids = None
    if args.target_ids:
        filter_ids = {t.strip() for t in args.target_ids.split(",")}

    all_rows = []
    json_files = sorted(raw_run_dir.glob("*.json"))
    logging.info(f"Found {len(json_files)} raw JSON files in {raw_run_dir}")

    for raw_path in json_files:
        wave_target_id = raw_path.stem
        if filter_ids and wave_target_id not in filter_ids:
            continue
        rows = extract_items_from_json(raw_path, args.run_id, wave_target_id)
        all_rows.extend(rows)
        logging.info(f"[{wave_target_id}] extracted {len(rows)} item rows")

    items_path = ROOT / config["paths"]["items_long_csv"]
    write_items(all_rows, items_path, overwrite=args.overwrite)
    logging.info(
        f"{'Wrote' if args.overwrite else 'Appended'} {len(all_rows)} rows to {items_path}"
    )


if __name__ == "__main__":
    main()
