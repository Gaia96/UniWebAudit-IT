#!/usr/bin/env python3
"""
WAVE API Collection Script

Reads wave_target_manifest.csv, calls the WAVE WebAIM API for each
api_primary target, saves raw JSON responses, and appends summary rows
to data/collection/wave_results.csv.

Usage:
    python wave/scripts/wave_collect.py --run-id WVRUN_001
    python wave/scripts/wave_collect.py --run-id WVRUN_001 --target-ids WV_HOME_UNI01,WV_COURSE_C001
    python wave/scripts/wave_collect.py --run-id WVRUN_001 --dry-run
    python wave/scripts/wave_collect.py --run-id WVRUN_001 --include-browser-fallback

Requirements:
    pip install requests pyyaml

API key:
    Set WAVE_API_KEY in your shell or in a .env file at the repo root.
    See wave/docs/README.md for setup.
"""

import os
import csv
import json
import logging
import argparse
import time
import requests
from pathlib import Path
from datetime import datetime, timezone

try:
    import yaml
except ImportError:
    raise ImportError("pyyaml required: pip install pyyaml")

ROOT = Path(__file__).resolve().parents[2]

RESULTS_FIELDNAMES = [
    "crawl_run_id",
    "target_id",
    "source_document_id",
    "page_role",
    "requested_url",
    "returned_pageurl",
    "http_status",
    "wave_success",
    "tool_name",
    "tool_mode",
    "tool_version",
    "reporttype",
    "audit_date",
    "viewport_policy",
    "viewportwidth",
    "useragent_profile",
    "evaldelay_ms",
    "pagetitle",
    "aimscore",
    "allitemcount",
    "totalelements",
    "error_count",
    "contrast_count",
    "alert_count",
    "feature_count",
    "structure_count",
    "aria_count",
    "raw_json_path",
    "notes",
]


def setup_logging(log_dir: Path, run_id: str) -> None:
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / f"{run_id}.log"
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[
            logging.FileHandler(log_file, encoding="utf-8"),
            logging.StreamHandler(),
        ],
    )


def load_config() -> dict:
    config_path = ROOT / "wave" / "config" / "wave_config.yaml"
    with open(config_path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def get_api_key() -> str:
    key = os.environ.get("WAVE_API_KEY", "").strip()
    if not key:
        env_path = ROOT / ".env"
        if env_path.exists():
            for line in env_path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line.startswith("WAVE_API_KEY=") and not line.startswith("#"):
                    key = line.split("=", 1)[1].strip().strip("\"'")
                    break
    if not key:
        raise EnvironmentError(
            "WAVE_API_KEY not set.\n"
            "  Option 1: export WAVE_API_KEY=yourkey\n"
            "  Option 2: add WAVE_API_KEY=yourkey to .env at repo root\n"
            "  See wave/docs/README.md for details."
        )
    return key


def load_manifest(config: dict, include_browser_fallback: bool = False) -> list:
    manifest_path = ROOT / config["paths"]["manifest"]
    with open(manifest_path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    if include_browser_fallback:
        return rows
    return [r for r in rows if r.get("wave_collection_mode") == "api_primary"]


def call_wave_api(api_key: str, url: str, config: dict) -> dict:
    params = {
        "key": api_key,
        "url": url,
        "reporttype": config["api"]["reporttype"],
        "viewportwidth": config["api"]["viewportwidth"],
        "evaldelay": config["api"]["evaldelay"],
    }
    if config["api"].get("useragent"):
        params["useragent"] = config["api"]["useragent"]
    resp = requests.get(
        config["api"]["endpoint"],
        params=params,
        timeout=config["collection"]["request_timeout_s"],
    )
    resp.raise_for_status()
    return resp.json()


def build_empty_result(row: dict, run_id: str, config: dict, audit_date: str) -> dict:
    return {
        "crawl_run_id": run_id,
        "target_id": row["wave_target_id"],
        "source_document_id": row["source_document_id"],
        "page_role": row["page_role"],
        "requested_url": row["url_to_audit"],
        "returned_pageurl": "",
        "http_status": "",
        "wave_success": "",
        "tool_name": config["run"]["tool_name"],
        "tool_mode": config["run"]["tool_mode"],
        "tool_version": "",
        "reporttype": config["api"]["reporttype"],
        "audit_date": audit_date,
        "viewport_policy": config["run"]["viewport_policy"],
        "viewportwidth": config["api"]["viewportwidth"],
        "useragent_profile": config["run"]["useragent_profile"],
        "evaldelay_ms": config["api"]["evaldelay"],
        "pagetitle": "",
        "aimscore": "",
        "allitemcount": "",
        "totalelements": "",
        "error_count": "",
        "contrast_count": "",
        "alert_count": "",
        "feature_count": "",
        "structure_count": "",
        "aria_count": "",
        "raw_json_path": "",
        "notes": "",
    }


def process_target(
    row: dict,
    api_key: str,
    config: dict,
    run_id: str,
    raw_run_dir: Path,
    dry_run: bool = False,
) -> dict:
    wave_target_id = row["wave_target_id"]
    url = row["url_to_audit"]
    audit_date = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    raw_path = raw_run_dir / f"{wave_target_id}.json"

    result = build_empty_result(row, run_id, config, audit_date)
    result["raw_json_path"] = str(raw_path.relative_to(ROOT))

    if dry_run:
        result["notes"] = "dry_run"
        logging.info(f"[DRY RUN] {wave_target_id} -> {url}")
        return result

    max_attempts = config["collection"]["retry_attempts"]
    retry_delay = config["collection"]["retry_delay_s"]

    for attempt in range(1, max_attempts + 1):
        try:
            logging.info(f"[{wave_target_id}] attempt {attempt}/{max_attempts}: {url}")
            data = call_wave_api(api_key, url, config)
            raw_path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
            )

            status = data.get("status", {})
            stats = data.get("statistics", {})
            cats = data.get("categories", {})

            result["wave_success"] = status.get("success", False)
            result["http_status"] = status.get("httpstatuscode", "")
            result["returned_pageurl"] = stats.get("pageurl", "")
            result["pagetitle"] = stats.get("pagetitle", "")
            result["aimscore"] = stats.get("AIMscore", stats.get("aimscore", ""))
            result["allitemcount"] = stats.get("allitemcount", "")
            result["totalelements"] = stats.get("totalelements", "")
            result["error_count"] = cats.get("error", {}).get("count", "")
            result["contrast_count"] = cats.get("contrast", {}).get("count", "")
            result["alert_count"] = cats.get("alert", {}).get("count", "")
            result["feature_count"] = cats.get("feature", {}).get("count", "")
            result["structure_count"] = cats.get("structure", {}).get("count", "")
            result["aria_count"] = cats.get("aria", {}).get("count", "")

            credits_left = stats.get("creditsremaining", "?")
            logging.info(
                f"[{wave_target_id}] OK success={result['wave_success']} "
                f"errors={result['error_count']} credits_left={credits_left}"
            )
            break

        except requests.HTTPError as e:
            msg = f"HTTPError attempt {attempt}: {e}"
            result["notes"] = msg
            logging.warning(f"[{wave_target_id}] {msg}")
            if attempt < max_attempts:
                time.sleep(retry_delay)

        except Exception as e:
            msg = f"{type(e).__name__} attempt {attempt}: {e}"
            result["notes"] = msg
            logging.error(f"[{wave_target_id}] {msg}")
            if attempt < max_attempts:
                time.sleep(retry_delay)

    return result


def append_results(results: list, results_path: Path) -> None:
    write_header = not results_path.exists() or results_path.stat().st_size == 0
    with open(results_path, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=RESULTS_FIELDNAMES, extrasaction="ignore")
        if write_header:
            writer.writeheader()
        writer.writerows(results)


def main() -> None:
    parser = argparse.ArgumentParser(description="WAVE API collection script")
    parser.add_argument(
        "--run-id", required=True,
        help="Unique crawl run ID for this batch, e.g. WVRUN_001"
    )
    parser.add_argument(
        "--target-ids",
        help="Comma-separated wave_target_id filter, e.g. WV_HOME_UNI01,WV_COURSE_C001"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Skip API calls; test manifest loading, file creation, and CSV output only"
    )
    parser.add_argument(
        "--include-browser-fallback", action="store_true",
        help="Also attempt API calls for browser_fallback targets (JS-heavy; expect partial results)"
    )
    args = parser.parse_args()

    config = load_config()
    log_dir = ROOT / config["paths"]["log_dir"]
    setup_logging(log_dir, args.run_id)
    logging.info(f"=== WAVE collection start: {args.run_id} ===")

    api_key = "" if args.dry_run else get_api_key()

    targets = load_manifest(config, include_browser_fallback=args.include_browser_fallback)
    logging.info(f"Manifest loaded: {len(targets)} targets")

    if args.target_ids:
        filter_ids = {t.strip() for t in args.target_ids.split(",")}
        targets = [r for r in targets if r["wave_target_id"] in filter_ids]
        logging.info(f"Filtered to {len(targets)} targets")

    raw_run_dir = ROOT / config["paths"]["raw_output_dir"] / args.run_id
    raw_run_dir.mkdir(parents=True, exist_ok=True)

    delay = config["collection"]["delay_between_requests_s"]
    results = []

    for i, row in enumerate(targets):
        if i > 0 and not args.dry_run:
            time.sleep(delay)
        result = process_target(row, api_key, config, args.run_id, raw_run_dir, args.dry_run)
        results.append(result)

        # Incremental write: append after each target so progress survives interruptions
        results_path = ROOT / config["paths"]["results_csv"]
        append_results([result], results_path)

    success_count = sum(1 for r in results if str(r.get("wave_success")) == "True")
    logging.info(
        f"=== WAVE collection complete: {success_count}/{len(results)} successful ==="
    )
    logging.info(f"Results appended to: {ROOT / config['paths']['results_csv']}")
    logging.info(f"Raw JSON saved to:   {raw_run_dir}")


if __name__ == "__main__":
    main()
