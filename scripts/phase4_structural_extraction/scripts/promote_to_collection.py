#!/usr/bin/env python3
"""
promote_to_collection.py — Phase 4 Step 7 promotion.

Copies the staging files to data/collection/ after validate_structural.py
has passed with --target=staging. Backs up any preexisting collection files
to data/collection/backups/ with a UTC timestamp.

Run:
    python3 structural_extraction/scripts/promote_to_collection.py
    python3 structural_extraction/scripts/promote_to_collection.py --force

The script REFUSES to overwrite unless validate_structural.py succeeds first
(it re-runs the validator internally on the staging target). With --force it
still runs the validator but treats validation warnings as non-blocking
(errors are still blocking).

Dependencies: stdlib only.
"""

from __future__ import annotations

import argparse
import csv
import logging
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
STAGING_WIDE = REPO_ROOT / "structural_extraction/staging/structural_indicators.staging.csv"
STAGING_LONG = REPO_ROOT / "structural_extraction/staging/structural_evidence_long.staging.csv"
COLLECTION_WIDE = REPO_ROOT / "data/collection/structural_indicators.csv"
COLLECTION_LONG = REPO_ROOT / "data/collection/structural_evidence_long.csv"
BACKUP_DIR = REPO_ROOT / "data/collection/backups"
LOG_DIR = REPO_ROOT / "structural_extraction/logs"
VALIDATOR = REPO_ROOT / "structural_extraction/scripts/validate_structural.py"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[logging.FileHandler(LOG_DIR / "promote_to_collection.log", mode="w"),
                  logging.StreamHandler()],
    )

    if not STAGING_WIDE.exists() or not STAGING_LONG.exists():
        logging.error("Staging files missing.")
        return 2

    logging.info("Running validator (target=staging)...")
    proc = subprocess.run(
        [sys.executable, str(VALIDATOR), "--target", "staging"],
        capture_output=True, text=True,
    )
    sys.stdout.write(proc.stdout)
    sys.stderr.write(proc.stderr)
    if proc.returncode != 0 and not args.force:
        logging.error("Validator failed (rc=%d). Aborting promotion.", proc.returncode)
        return proc.returncode

    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    for src, dst in [(STAGING_WIDE, COLLECTION_WIDE), (STAGING_LONG, COLLECTION_LONG)]:
        if dst.exists():
            backup = BACKUP_DIR / f"{dst.name}.pre_STRUN.{ts}.csv"
            shutil.copy2(dst, backup)
            logging.info("Backed up %s -> %s", dst.relative_to(REPO_ROOT), backup.relative_to(REPO_ROOT))
        shutil.copy2(src, dst)
        logging.info("Promoted %s -> %s", src.relative_to(REPO_ROOT), dst.relative_to(REPO_ROOT))

    logging.info("Re-running validator (target=collection)...")
    proc2 = subprocess.run(
        [sys.executable, str(VALIDATOR), "--target", "collection"],
        capture_output=True, text=True,
    )
    sys.stdout.write(proc2.stdout)
    sys.stderr.write(proc2.stderr)
    return proc2.returncode


if __name__ == "__main__":
    raise SystemExit(main())
