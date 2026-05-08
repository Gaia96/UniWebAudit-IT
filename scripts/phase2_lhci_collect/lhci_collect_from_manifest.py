#!/usr/bin/env python3
"""Run Lighthouse CI collect for each target in a manifest CSV.

This wrapper is designed for research/data-collection workflows where you want:
- one auditable target manifest as source of truth
- isolated per-target artifacts
- local-only storage of raw LHCI outputs
- a combined collection summary CSV for later extraction

It intentionally shells out to `lhci collect` and `lhci upload --target=filesystem`
so the measurement step is performed by Lighthouse CI, not by the standalone
Lighthouse CLI.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import shlex
import shutil
import subprocess
import sys
import textwrap
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


DEFAULT_REQUIRED_COLUMNS = [
    "lighthouse_target_id",
    "source_document_id",
    "university_id",
    "page_role",
    "default_strategy",
    "tested_url",
    "final_url",
]


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def ts_slug() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def sanitize_slug(value: str) -> str:
    safe = []
    for ch in value:
        if ch.isalnum() or ch in {"-", "_", "."}:
            safe.append(ch)
        else:
            safe.append("_")
    cleaned = "".join(safe).strip("._")
    return cleaned or "item"


@dataclass
class RunResult:
    row: dict[str, str]
    started_at: str
    ended_at: str
    status: str
    audited_url: str
    url_source_column: str
    strategy_used: str
    target_dir: str
    work_dir: str
    filesystem_dir: str
    collection_crawl_run_id: str = ""
    collect_exit_code: int | None = None
    upload_exit_code: int | None = None
    error_message: str = ""
    representative_json_path: str = ""
    representative_html_path: str = ""
    representative_requested_url: str = ""
    representative_final_url: str = ""
    fetch_time: str = ""
    lighthouse_version: str = ""
    runtime_error_code: str = ""
    runtime_error_message: str = ""
    category_performance: str = ""
    category_accessibility: str = ""
    category_best_practices: str = ""
    category_seo: str = ""
    metric_fcp_ms: str = ""
    metric_lcp_ms: str = ""
    metric_speed_index_ms: str = ""
    metric_tbt_ms: str = ""
    metric_cls: str = ""
    metric_inp_ms: str = ""
    report_count: int = 0


class ScriptError(RuntimeError):
    pass


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run lhci collect from a CSV target manifest and store per-target artifacts locally.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent(
            """
            Examples:
              python lhci_collect_from_manifest.py \
                --manifest ./lhci_collect/lighthouse_target_manifest.csv \
                --output-root ./artifacts/runs/CR033_lighthouse_mobile_v1

              python lhci_collect_from_manifest.py \
                --manifest ./lhci_collect/lighthouse_target_manifest.csv \
                --output-root ./artifacts/runs/CR033_smoke \
                --target-id LH_HOME_UNI01 LH_COURSE_C035 \
                --number-of-runs 1 \
                --dry-run
            """
        ),
    )
    parser.add_argument("--manifest", required=True, help="Path to lighthouse_target_manifest.csv")
    parser.add_argument(
        "--output-root",
        default=f"./lhci_collect_output/lhci_collect_{ts_slug()}",
        help="Root directory for this collection run.",
    )
    parser.add_argument(
        "--lhci-launcher",
        default="npx --yes @lhci/cli@0.15.1",
        help="Command prefix used to invoke LHCI, e.g. 'npx --yes @lhci/cli@0.15.1' or 'lhci'.",
    )
    parser.add_argument(
        "--number-of-runs",
        type=int,
        default=3,
        help="Number of Lighthouse runs per URL. LHCI default is 3.",
    )
    parser.add_argument(
        "--collection-crawl-run-id",
        default="",
        help="Optional new crawl_run_id for this Lighthouse collection batch (e.g. CR033).",
    )
    parser.add_argument(
        "--url-column",
        choices=["final_url", "tested_url"],
        default="final_url",
        help="Which manifest column to audit. Default: final_url.",
    )
    parser.add_argument(
        "--target-id",
        nargs="*",
        default=None,
        help="Optional subset of lighthouse_target_id values to run.",
    )
    parser.add_argument(
        "--page-role",
        nargs="*",
        default=None,
        help="Optional subset of page_role values to run, e.g. course_page university_homepage.",
    )
    parser.add_argument("--limit", type=int, default=None, help="Stop after the first N selected targets.")
    parser.add_argument(
        "--chrome-path",
        default="",
        help="Optional explicit Chrome/Chromium executable path passed to LHCI.",
    )
    parser.add_argument(
        "--headful",
        action="store_true",
        help="Run Chrome in headful mode for debugging/problem cases.",
    )
    parser.add_argument(
        "--max-wait-for-load",
        type=int,
        default=None,
        help="Optional LHCI settings.maxWaitForLoad override in milliseconds.",
    )
    parser.add_argument(
        "--sleep-seconds",
        type=float,
        default=0.0,
        help="Optional delay between targets.",
    )
    parser.add_argument(
        "--stop-on-error",
        action="store_true",
        help="Abort the whole run on the first target failure.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print planned commands and write the run manifest, but do not execute LHCI.",
    )
    return parser.parse_args()


def ensure_required_columns(rows: list[dict[str, str]]) -> None:
    if not rows:
        raise ScriptError("Manifest is empty.")
    available = set(rows[0].keys())
    missing = [col for col in DEFAULT_REQUIRED_COLUMNS if col not in available]
    if missing:
        raise ScriptError(f"Manifest is missing required columns: {', '.join(missing)}")


def load_manifest(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    ensure_required_columns(rows)
    return rows


def select_rows(rows: list[dict[str, str]], args: argparse.Namespace) -> list[dict[str, str]]:
    selected = rows
    if args.target_id:
        allowed = set(args.target_id)
        selected = [row for row in selected if row.get("lighthouse_target_id", "") in allowed]
    if args.page_role:
        allowed_roles = set(args.page_role)
        selected = [row for row in selected if row.get("page_role", "") in allowed_roles]
    if args.limit is not None:
        selected = selected[: args.limit]
    if not selected:
        raise ScriptError("No manifest rows matched the provided filters.")
    return selected


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def run_command(
    cmd: list[str],
    cwd: Path,
    stdout_path: Path,
    stderr_path: Path,
    dry_run: bool,
) -> int:
    if dry_run:
        write_text(stdout_path, "$ " + shlex.join(cmd) + "\n[dry-run]\n")
        write_text(stderr_path, "")
        return 0

    proc = subprocess.run(
        cmd,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        check=False,
    )
    write_text(stdout_path, proc.stdout)
    write_text(stderr_path, proc.stderr)
    return proc.returncode


def parse_lhci_launcher(value: str) -> list[str]:
    parts = shlex.split(value)
    if not parts:
        raise ScriptError("--lhci-launcher resolved to an empty command.")
    return parts


def build_collect_command(args: argparse.Namespace, audited_url: str, strategy: str) -> list[str]:
    cmd = parse_lhci_launcher(args.lhci_launcher) + [
        "collect",
        f"--numberOfRuns={args.number_of_runs}",
        f"--url={audited_url}",
    ]
    if args.headful:
        cmd.append("--headful")
    if args.chrome_path:
        cmd.append(f"--chromePath={args.chrome_path}")
    if args.max_wait_for_load is not None:
        cmd.append(f"--settings.maxWaitForLoad={args.max_wait_for_load}")
    if strategy == "desktop":
        cmd.append("--settings.preset=desktop")
    return cmd


def build_upload_command(args: argparse.Namespace, output_dir_relative_to_workdir: str) -> list[str]:
    cmd = parse_lhci_launcher(args.lhci_launcher) + [
        "upload",
        "--target=filesystem",
        f"--outputDir={output_dir_relative_to_workdir}",
    ]
    return cmd


def build_healthcheck_command(args: argparse.Namespace) -> list[str]:
    cmd = parse_lhci_launcher(args.lhci_launcher) + ["healthcheck", "--fatal"]
    if args.chrome_path:
        cmd.append(f"--chromePath={args.chrome_path}")
    return cmd


def tail_text(path: Path, max_chars: int = 800) -> str:
    if not path.exists():
        return ""
    text = path.read_text(encoding="utf-8", errors="replace")
    return text[-max_chars:].strip()


def score_from(obj: dict[str, Any], path: Iterable[str]) -> str:
    cur: Any = obj
    for key in path:
        if not isinstance(cur, dict) or key not in cur:
            return ""
        cur = cur[key]
    if cur is None:
        return ""
    return str(cur)


def numeric_value_from(audits: dict[str, Any], audit_id: str) -> str:
    item = audits.get(audit_id)
    if not isinstance(item, dict):
        return ""
    value = item.get("numericValue")
    if value is None:
        return ""
    return str(value)


def parse_representative_payload(filesystem_dir: Path) -> dict[str, Any]:
    manifest_path = filesystem_dir / "manifest.json"
    if not manifest_path.exists():
        return {}
    manifest_data = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(manifest_data, list) or not manifest_data:
        return {}

    representative = None
    for item in manifest_data:
        if isinstance(item, dict) and item.get("isRepresentativeRun"):
            representative = item
            break
    if representative is None:
        representative = manifest_data[0]
    if not isinstance(representative, dict):
        return {}

    json_path = representative.get("jsonPath")
    report_obj: dict[str, Any] = {}
    if isinstance(json_path, str) and Path(json_path).exists():
        try:
            report_obj = json.loads(Path(json_path).read_text(encoding="utf-8"))
        except Exception:
            report_obj = {}

    categories = report_obj.get("categories") if isinstance(report_obj, dict) else {}
    audits = report_obj.get("audits") if isinstance(report_obj, dict) else {}
    runtime_error = report_obj.get("runtimeError") if isinstance(report_obj, dict) else {}

    return {
        "representative_json_path": str(json_path or ""),
        "representative_html_path": str(representative.get("htmlPath") or ""),
        "representative_requested_url": str(report_obj.get("requestedUrl") or representative.get("url") or ""),
        "representative_final_url": str(report_obj.get("finalUrl") or report_obj.get("finalDisplayedUrl") or ""),
        "fetch_time": str(report_obj.get("fetchTime") or ""),
        "lighthouse_version": str(report_obj.get("lighthouseVersion") or ""),
        "runtime_error_code": str(runtime_error.get("code") or "") if isinstance(runtime_error, dict) else "",
        "runtime_error_message": str(runtime_error.get("message") or "") if isinstance(runtime_error, dict) else "",
        "category_performance": score_from(categories, ["performance", "score"]),
        "category_accessibility": score_from(categories, ["accessibility", "score"]),
        "category_best_practices": score_from(categories, ["best-practices", "score"]),
        "category_seo": score_from(categories, ["seo", "score"]),
        "metric_fcp_ms": numeric_value_from(audits if isinstance(audits, dict) else {}, "first-contentful-paint"),
        "metric_lcp_ms": numeric_value_from(audits if isinstance(audits, dict) else {}, "largest-contentful-paint"),
        "metric_speed_index_ms": numeric_value_from(audits if isinstance(audits, dict) else {}, "speed-index"),
        "metric_tbt_ms": numeric_value_from(audits if isinstance(audits, dict) else {}, "total-blocking-time"),
        "metric_cls": numeric_value_from(audits if isinstance(audits, dict) else {}, "cumulative-layout-shift"),
        "metric_inp_ms": numeric_value_from(audits if isinstance(audits, dict) else {}, "interaction-to-next-paint"),
        "report_count": len(manifest_data),
    }


def write_summary_csv(path: Path, results: list[RunResult]) -> None:
    fieldnames = [
        # source manifest columns
        "lighthouse_target_id",
        "source_document_id",
        "crawl_run_id",
        "university_id",
        "sample_course_id",
        "journey_id",
        "page_role",
        "source_kind",
        "default_strategy",
        "default_device_category",
        "scope_status",
        "selection_rule",
        "js_dependency_level_preaudit",
        "tested_url",
        "final_url",
        "notes",
        # execution columns
        "collection_crawl_run_id",
        "started_at",
        "ended_at",
        "status",
        "audited_url",
        "url_source_column",
        "strategy_used",
        "target_dir",
        "work_dir",
        "filesystem_dir",
        "collect_exit_code",
        "upload_exit_code",
        "error_message",
        # representative run / extracted fields
        "representative_json_path",
        "representative_html_path",
        "representative_requested_url",
        "representative_final_url",
        "fetch_time",
        "lighthouse_version",
        "runtime_error_code",
        "runtime_error_message",
        "category_performance",
        "category_accessibility",
        "category_best_practices",
        "category_seo",
        "metric_fcp_ms",
        "metric_lcp_ms",
        "metric_speed_index_ms",
        "metric_tbt_ms",
        "metric_cls",
        "metric_inp_ms",
        "report_count",
    ]

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for result in results:
            row = {key: result.row.get(key, "") for key in fieldnames}
            row.update(
                {
                    "collection_crawl_run_id": getattr(result, 'collection_crawl_run_id', ''),
                    "started_at": result.started_at,
                    "ended_at": result.ended_at,
                    "status": result.status,
                    "audited_url": result.audited_url,
                    "url_source_column": result.url_source_column,
                    "strategy_used": result.strategy_used,
                    "target_dir": result.target_dir,
                    "work_dir": result.work_dir,
                    "filesystem_dir": result.filesystem_dir,
                    "collect_exit_code": "" if result.collect_exit_code is None else str(result.collect_exit_code),
                    "upload_exit_code": "" if result.upload_exit_code is None else str(result.upload_exit_code),
                    "error_message": result.error_message,
                    "representative_json_path": result.representative_json_path,
                    "representative_html_path": result.representative_html_path,
                    "representative_requested_url": result.representative_requested_url,
                    "representative_final_url": result.representative_final_url,
                    "fetch_time": result.fetch_time,
                    "lighthouse_version": result.lighthouse_version,
                    "runtime_error_code": result.runtime_error_code,
                    "runtime_error_message": result.runtime_error_message,
                    "category_performance": result.category_performance,
                    "category_accessibility": result.category_accessibility,
                    "category_best_practices": result.category_best_practices,
                    "category_seo": result.category_seo,
                    "metric_fcp_ms": result.metric_fcp_ms,
                    "metric_lcp_ms": result.metric_lcp_ms,
                    "metric_speed_index_ms": result.metric_speed_index_ms,
                    "metric_tbt_ms": result.metric_tbt_ms,
                    "metric_cls": result.metric_cls,
                    "metric_inp_ms": result.metric_inp_ms,
                    "report_count": str(result.report_count),
                }
            )
            writer.writerow(row)


def main() -> int:
    args = parse_args()

    manifest_path = Path(args.manifest).resolve()
    if not manifest_path.exists():
        raise ScriptError(f"Manifest not found: {manifest_path}")

    rows = load_manifest(manifest_path)
    selected_rows = select_rows(rows, args)

    output_root = Path(args.output_root).resolve()
    output_root.mkdir(parents=True, exist_ok=True)

    run_metadata = {
        "started_at": utc_now(),
        "manifest_path": str(manifest_path),
        "output_root": str(output_root),
        "lhci_launcher": args.lhci_launcher,
        "number_of_runs": args.number_of_runs,
        "collection_crawl_run_id": args.collection_crawl_run_id,
        "url_column": args.url_column,
        "dry_run": args.dry_run,
        "headful": args.headful,
        "chrome_path": args.chrome_path,
        "max_wait_for_load": args.max_wait_for_load,
        "sleep_seconds": args.sleep_seconds,
        "stop_on_error": args.stop_on_error,
        "selected_target_count": len(selected_rows),
        "selected_target_ids": [row.get("lighthouse_target_id", "") for row in selected_rows],
    }
    write_json(output_root / "run_manifest.json", run_metadata)

    # One up-front healthcheck is enough for the environment.
    healthcheck_dir = output_root / "_healthcheck_workdir"
    healthcheck_dir.mkdir(parents=True, exist_ok=True)
    healthcheck_cmd = build_healthcheck_command(args)
    healthcheck_code = run_command(
        healthcheck_cmd,
        cwd=healthcheck_dir,
        stdout_path=output_root / "_healthcheck_stdout.txt",
        stderr_path=output_root / "_healthcheck_stderr.txt",
        dry_run=args.dry_run,
    )
    if healthcheck_code != 0:
        raise ScriptError(
            "LHCI healthcheck failed. See _healthcheck_stdout.txt and _healthcheck_stderr.txt in the output root."
        )

    results: list[RunResult] = []

    for index, row in enumerate(selected_rows, start=1):
        started_at = utc_now()
        target_id = row.get("lighthouse_target_id", f"target_{index}")
        target_dir = output_root / sanitize_slug(target_id)
        work_dir = target_dir / "workdir"
        filesystem_dir = target_dir / "lhci_filesystem"
        logs_dir = target_dir / "logs"

        if target_dir.exists() and any(target_dir.iterdir()):
            raise ScriptError(
                f"Target output directory already exists and is non-empty: {target_dir}. "
                "Use a fresh --output-root for each collection run."
            )

        work_dir.mkdir(parents=True, exist_ok=True)
        filesystem_dir.mkdir(parents=True, exist_ok=True)
        logs_dir.mkdir(parents=True, exist_ok=True)
        write_json(target_dir / "target_row.json", row)

        audited_url = (row.get(args.url_column, "") or "").strip()
        if not audited_url:
            fallback_column = "tested_url" if args.url_column == "final_url" else "final_url"
            audited_url = (row.get(fallback_column, "") or "").strip()
        if not audited_url:
            ended_at = utc_now()
            results.append(
                RunResult(
                    row=row,
                    started_at=started_at,
                    ended_at=ended_at,
                    status="failed_precheck",
                    audited_url="",
                    url_source_column=args.url_column,
                    strategy_used=row.get("default_strategy", "") or "mobile",
                    target_dir=str(target_dir),
                    work_dir=str(work_dir),
                    filesystem_dir=str(filesystem_dir),
                    collection_crawl_run_id=args.collection_crawl_run_id,
                    error_message="No usable audited URL found in manifest row.",
                )
            )
            if args.stop_on_error:
                break
            continue

        strategy = (row.get("default_strategy", "") or "mobile").strip().lower()
        collect_cmd = build_collect_command(args, audited_url=audited_url, strategy=strategy)
        upload_cmd = build_upload_command(args, output_dir_relative_to_workdir="../lhci_filesystem")

        write_text(logs_dir / "planned_commands.txt", "\n".join([shlex.join(collect_cmd), shlex.join(upload_cmd)]) + "\n")

        collect_code = run_command(
            collect_cmd,
            cwd=work_dir,
            stdout_path=logs_dir / "collect_stdout.txt",
            stderr_path=logs_dir / "collect_stderr.txt",
            dry_run=args.dry_run,
        )

        if collect_code != 0:
            ended_at = utc_now()
            err = tail_text(logs_dir / "collect_stderr.txt") or tail_text(logs_dir / "collect_stdout.txt")
            results.append(
                RunResult(
                    row=row,
                    started_at=started_at,
                    ended_at=ended_at,
                    status="collect_failed",
                    audited_url=audited_url,
                    url_source_column=args.url_column,
                    strategy_used=strategy,
                    target_dir=str(target_dir),
                    work_dir=str(work_dir),
                    filesystem_dir=str(filesystem_dir),
                    collection_crawl_run_id=args.collection_crawl_run_id,
                    collect_exit_code=collect_code,
                    error_message=err,
                )
            )
            if args.stop_on_error:
                break
            if args.sleep_seconds:
                time.sleep(args.sleep_seconds)
            continue

        upload_code = run_command(
            upload_cmd,
            cwd=work_dir,
            stdout_path=logs_dir / "upload_stdout.txt",
            stderr_path=logs_dir / "upload_stderr.txt",
            dry_run=args.dry_run,
        )

        ended_at = utc_now()
        if upload_code != 0:
            err = tail_text(logs_dir / "upload_stderr.txt") or tail_text(logs_dir / "upload_stdout.txt")
            results.append(
                RunResult(
                    row=row,
                    started_at=started_at,
                    ended_at=ended_at,
                    status="upload_failed",
                    audited_url=audited_url,
                    url_source_column=args.url_column,
                    strategy_used=strategy,
                    target_dir=str(target_dir),
                    work_dir=str(work_dir),
                    filesystem_dir=str(filesystem_dir),
                    collection_crawl_run_id=args.collection_crawl_run_id,
                    collect_exit_code=collect_code,
                    upload_exit_code=upload_code,
                    error_message=err,
                )
            )
            if args.stop_on_error:
                break
            if args.sleep_seconds:
                time.sleep(args.sleep_seconds)
            continue

        extracted = parse_representative_payload(filesystem_dir)
        results.append(
            RunResult(
                row=row,
                started_at=started_at,
                ended_at=ended_at,
                status="ok_dry_run" if args.dry_run else "ok",
                audited_url=audited_url,
                url_source_column=args.url_column,
                strategy_used=strategy,
                target_dir=str(target_dir),
                work_dir=str(work_dir),
                filesystem_dir=str(filesystem_dir),
                collection_crawl_run_id=args.collection_crawl_run_id,
                collect_exit_code=collect_code,
                upload_exit_code=upload_code,
                error_message="",
                representative_json_path=str(extracted.get("representative_json_path", "")),
                representative_html_path=str(extracted.get("representative_html_path", "")),
                representative_requested_url=str(extracted.get("representative_requested_url", "")),
                representative_final_url=str(extracted.get("representative_final_url", "")),
                fetch_time=str(extracted.get("fetch_time", "")),
                lighthouse_version=str(extracted.get("lighthouse_version", "")),
                runtime_error_code=str(extracted.get("runtime_error_code", "")),
                runtime_error_message=str(extracted.get("runtime_error_message", "")),
                category_performance=str(extracted.get("category_performance", "")),
                category_accessibility=str(extracted.get("category_accessibility", "")),
                category_best_practices=str(extracted.get("category_best_practices", "")),
                category_seo=str(extracted.get("category_seo", "")),
                metric_fcp_ms=str(extracted.get("metric_fcp_ms", "")),
                metric_lcp_ms=str(extracted.get("metric_lcp_ms", "")),
                metric_speed_index_ms=str(extracted.get("metric_speed_index_ms", "")),
                metric_tbt_ms=str(extracted.get("metric_tbt_ms", "")),
                metric_cls=str(extracted.get("metric_cls", "")),
                metric_inp_ms=str(extracted.get("metric_inp_ms", "")),
                report_count=int(extracted.get("report_count", 0) or 0),
            )
        )

        if args.sleep_seconds:
            time.sleep(args.sleep_seconds)

    write_summary_csv(output_root / "collection_summary.csv", results)

    finished_metadata = {
        **run_metadata,
        "ended_at": utc_now(),
        "success_count": sum(1 for r in results if r.status in {"ok", "ok_dry_run"}),
        "failure_count": sum(1 for r in results if r.status not in {"ok", "ok_dry_run"}),
        "statuses": {
            status: sum(1 for r in results if r.status == status)
            for status in sorted({r.status for r in results})
        },
        "summary_csv": str((output_root / "collection_summary.csv").resolve()),
    }
    write_json(output_root / "run_manifest.json", finished_metadata)

    print(json.dumps(finished_metadata, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ScriptError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
