"""
import_serp_batch.py
Import a validated SERP batch into the canonical collection tables.

Runs validation first. Aborts if errors are found unless --force is passed.

Usage (from repo root):
  python serp/scripts/import_serp_batch.py --batch-id SERP_B001
  python serp/scripts/import_serp_batch.py --batch-id SERP_B001 --force  # skip validation check

Actions:
  1. Validate batch (abort on errors unless --force)
  2. Backup canonical CSVs to data/collection/backups/
  3. Assign SOBS-format IDs to rows with [auto_on_import]
  4. Append batch_observations.csv rows to data/collection/serp_observations.csv
  5. Append batch_results_long.csv rows to data/collection/serp_results_long.csv
  6. Update collection_status=completed in serp_query_manifest.csv for imported rows
  7. Mark batch as imported in serp/batches/{batch_id}/batch_info.yaml
"""

import argparse
import csv
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
BATCHES_DIR = REPO_ROOT / "serp/batches"
MANIFEST_PATH = REPO_ROOT / "serp/manifests/serp_query_manifest.csv"
OBS_PATH = REPO_ROOT / "data/collection/serp_observations.csv"
LONG_PATH = REPO_ROOT / "data/collection/serp_results_long.csv"
BACKUP_DIR = REPO_ROOT / "data/collection/backups"

VALIDATE_SCRIPT = REPO_ROOT / "serp/scripts/validate_serp_batch.py"


def load_csv(path: Path) -> list[dict]:
    with open(path, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def write_csv(path: Path, rows: list[dict], fieldnames: list[str]) -> None:
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def backup(path: Path, tag: str) -> Path:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stem = path.stem
    suffix = path.suffix
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = BACKUP_DIR / f"{stem}_backup_{tag}_{ts}{suffix}"
    shutil.copy2(path, dest)
    return dest


def next_obs_id(existing: list[dict]) -> int:
    """Return the next SOBS integer, based on existing rows."""
    # Scans the canonical table to avoid ID collisions across batches
    nums = []
    for r in existing:
        oid = r.get("serp_observation_id", "").strip()
        if oid.startswith("SOBS"):
            try:
                nums.append(int(oid[4:]))
            except ValueError:
                pass
    return (max(nums) + 1) if nums else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Import a validated SERP batch")
    parser.add_argument("--batch-id", required=True, metavar="ID")
    parser.add_argument("--force", action="store_true",
                        help="Skip validation check and import anyway")
    args = parser.parse_args()

    batch_dir = BATCHES_DIR / args.batch_id
    obs_batch = batch_dir / "batch_observations.csv"
    long_batch = batch_dir / "batch_results_long.csv"
    info_path = batch_dir / "batch_info.yaml"

    if not batch_dir.exists():
        print(f"[ERROR] Batch not found: {batch_dir}", file=sys.stderr)
        return 1

    # Check not already imported
    if info_path.exists():
        info_text = info_path.read_text(encoding="utf-8")
        if "imported_at:" in info_text:
            print(
                f"[ERROR] Batch {args.batch_id} was already imported. "
                "Check batch_info.yaml for details.",
                file=sys.stderr,
            )
            return 1

    # --- 1. Validate ---
    if not args.force:
        print(f"[INFO] Running validation for {args.batch_id}...")
        result = subprocess.run(
            [sys.executable, str(VALIDATE_SCRIPT), "--batch-id", args.batch_id],
            capture_output=False,
        )
        if result.returncode != 0:
            print(
                "\n[ABORT] Validation failed. Fix errors above before importing. "
                "Use --force to override (not recommended).",
                file=sys.stderr,
            )
            return 1
        print()

    # --- 2. Load data ---
    if not obs_batch.exists():
        print(f"[ERROR] batch_observations.csv not found in {batch_dir}", file=sys.stderr)
        return 1

    batch_obs_rows = load_csv(obs_batch)
    if not batch_obs_rows:
        print("[ERROR] batch_observations.csv is empty — nothing to import.", file=sys.stderr)
        return 1

    existing_obs = load_csv(OBS_PATH) if OBS_PATH.exists() else []
    existing_ids = {r.get("serp_observation_id", "").strip() for r in existing_obs}

    # --- 3. Assign SOBS IDs ---
    counter = next_obs_id(existing_obs)
    for row in batch_obs_rows:
        obs_id = row.get("serp_observation_id", "").strip()
        if not obs_id or obs_id == "[auto_on_import]":
            row["serp_observation_id"] = f"SOBS{counter:04d}"
            counter += 1
        elif obs_id in existing_ids:
            print(
                f"[ERROR] serp_observation_id '{obs_id}' already exists in "
                "serp_observations.csv. Resolve duplicate before importing.",
                file=sys.stderr,
            )
            return 1

    # --- 4. Backup canonical files ---
    tag = args.batch_id
    backed = []
    for path in [OBS_PATH, LONG_PATH, MANIFEST_PATH]:
        if path.exists():
            dest = backup(path, tag)
            backed.append(dest)
            print(f"[BACKUP] {path.name} → {dest.relative_to(REPO_ROOT)}")

    # --- 5. Append observations ---
    obs_fieldnames = list(batch_obs_rows[0].keys()) if batch_obs_rows else []
    # Use canonical field order if possible
    if existing_obs:
        obs_fieldnames = list(existing_obs[0].keys())

    all_obs = existing_obs + batch_obs_rows
    write_csv(OBS_PATH, all_obs, obs_fieldnames)
    print(f"[OK] Appended {len(batch_obs_rows)} rows to serp_observations.csv "
          f"(total: {len(all_obs)})")

    # --- 6. Append long results (if non-empty) ---
    if long_batch.exists():
        batch_long_rows = load_csv(long_batch)
        if batch_long_rows:
            existing_long = load_csv(LONG_PATH) if LONG_PATH.exists() else []
            long_fieldnames = (
                list(existing_long[0].keys()) if existing_long
                else list(batch_long_rows[0].keys())
            )
            # Align serp_observation_id in long rows with assigned IDs
            obs_id_map = {
                (r.get("course_id", ""), r.get("query_template_id", "")): r["serp_observation_id"]
                for r in batch_obs_rows
            }
            for lr in batch_long_rows:
                key = (lr.get("course_id", ""), lr.get("query_template_id", ""))
                if lr.get("serp_observation_id", "") == "[auto_on_import]" and key in obs_id_map:
                    lr["serp_observation_id"] = obs_id_map[key]
            all_long = existing_long + batch_long_rows
            write_csv(LONG_PATH, all_long, long_fieldnames)
            print(f"[OK] Appended {len(batch_long_rows)} rows to serp_results_long.csv "
                  f"(total: {len(all_long)})")
        else:
            print("[INFO] batch_results_long.csv is empty — skipping long results import.")

    # Mark imported rows as completed so create_serp_batch.py skips them in future batches
    imported_pairs = {
        (r.get("course_id", ""), r.get("query_template_id", ""))
        for r in batch_obs_rows
    }
    manifest_rows = load_csv(MANIFEST_PATH)
    manifest_fieldnames = list(manifest_rows[0].keys()) if manifest_rows else []
    updated = 0
    for mrow in manifest_rows:
        key = (mrow.get("course_id", ""), mrow.get("query_template_id", ""))
        if key in imported_pairs and mrow.get("collection_status") != "completed":
            mrow["collection_status"] = "completed"
            updated += 1
    write_csv(MANIFEST_PATH, manifest_rows, manifest_fieldnames)
    print(f"[OK] Manifest updated: {updated} rows → collection_status=completed")

    # --- 8. Mark batch as imported ---
    ts = datetime.now().isoformat(timespec="seconds")
    with open(info_path, "a", encoding="utf-8") as f:
        f.write(f"\nimported_at: {ts}\n")
        f.write(f"imported_rows: {len(batch_obs_rows)}\n")
        f.write(f"obs_ids_assigned: SOBS{next_obs_id(existing_obs):04d} – SOBS{counter-1:04d}\n")

    print(f"\n[DONE] Batch {args.batch_id} imported successfully at {ts}")
    print(f"  Run: python serp/scripts/summarize_serp_coverage.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
