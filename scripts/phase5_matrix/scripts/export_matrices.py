#!/usr/bin/env python3
"""
Phase 5 Step C — Export raw matrices to CSV.

Runs the three SQL files against the preview SQLite and writes:
  phase5_matrix/_tmp/course_raw.csv   (expected: 41 rows)
  phase5_matrix/_tmp/page_raw.csv     (expected: 61 rows)
  phase5_matrix/_tmp/ateneo_raw.csv   (expected: 20 rows)

Usage:
  cd <project-root>
  python3 phase5_matrix/scripts/export_matrices.py [--no-refresh]
"""

import argparse
import csv
import sqlite3
import subprocess
import sys
from pathlib import Path

ROOT    = Path(__file__).resolve().parents[2]
DB_PATH = ROOT / "tmp" / "datagrip" / "university_audit_preview.sqlite"
SQL_DIR = ROOT / "phase5_matrix" / "sql"
TMP_DIR = ROOT / "phase5_matrix" / "_tmp"

JOBS = [
    ("course_matrix_raw.sql",  TMP_DIR / "course_raw.csv",  41),
    ("page_matrix_raw.sql",    TMP_DIR / "page_raw.csv",    61),
    ("ateneo_matrix_raw.sql",  TMP_DIR / "ateneo_raw.csv",  20),
]

EXPECTED_COUNTS = {"course_raw.csv": 41, "page_raw.csv": 61, "ateneo_raw.csv": 20}


def refresh_sqlite():
    # Rebuilds the SQLite DB from canonical CSVs so the SQL queries always run against fresh data
    print("[step] Regenerating preview SQLite …")
    result = subprocess.run(
        [sys.executable, "scripts/refresh_datagrip_sqlite.py"],
        cwd=ROOT, capture_output=False
    )
    if result.returncode != 0:
        sys.exit("[ERROR] refresh_datagrip_sqlite.py failed")


def run_sql_to_csv(sql_file: Path, out_csv: Path, expected_rows: int) -> bool:
    print(f"\n[sql] {sql_file.name} → {out_csv.name}")
    sql = sql_file.read_text()

    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    try:
        cur = con.execute(sql)
        rows = cur.fetchall()
    except sqlite3.Error as e:
        print(f"  [ERROR] SQL failed: {e}")
        con.close()
        return False
    finally:
        con.close()

    out_csv.parent.mkdir(parents=True, exist_ok=True)
    with out_csv.open("w", newline="", encoding="utf-8") as f:
        if not rows:
            print("  [WARN] 0 rows returned")
            return False
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows([dict(r) for r in rows])

    n = len(rows)
    ok = n == expected_rows
    status = "OK" if ok else f"WARN — expected {expected_rows}, got {n}"
    print(f"  rows: {n}  [{status}]")
    return ok


def qa_counts(out_csv: Path, key_col: str):
    """Verify the primary key column has no duplicate values (each row must be unique)."""
    with out_csv.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        if key_col not in (reader.fieldnames or []):
            print(f"  [SKIP unique-check] column '{key_col}' not found")
            return
        vals = [row[key_col] for row in reader]
    dupes = [v for v in set(vals) if vals.count(v) > 1]
    if dupes:
        print(f"  [ERROR] duplicate {key_col}: {dupes}")
    else:
        print(f"  unique {key_col}: OK ({len(vals)} distinct)")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-refresh", action="store_true",
                        help="Skip SQLite regeneration")
    args = parser.parse_args()

    if not args.no_refresh:
        refresh_sqlite()

    if not DB_PATH.exists():
        sys.exit(f"[ERROR] SQLite not found at {DB_PATH}")

    all_ok = True
    for sql_name, out_csv, expected in JOBS:
        sql_path = SQL_DIR / sql_name
        if not sql_path.exists():
            print(f"[ERROR] SQL file missing: {sql_path}")
            all_ok = False
            continue
        ok = run_sql_to_csv(sql_path, out_csv, expected)
        all_ok = all_ok and ok

    # QA: primary key uniqueness
    print("\n[qa] Primary key uniqueness checks …")
    qa_counts(TMP_DIR / "course_raw.csv",  "sample_course_id")
    qa_counts(TMP_DIR / "page_raw.csv",    "source_document_id")
    qa_counts(TMP_DIR / "ateneo_raw.csv",  "university_id")

    # QA: blocked_js courses present in course_raw
    print("\n[qa] Blocked-JS courses check …")
    _check_blocked_js(TMP_DIR / "course_raw.csv")

    # QA: browser_fallback in course_raw
    print("[qa] WAVE browser_fallback check …")
    _check_wave_fallback(TMP_DIR / "course_raw.csv")

    print(f"\n{'[DONE] All checks passed.' if all_ok else '[WARN] Some checks failed — review above.'}")


def _check_blocked_js(course_csv: Path):
    if not course_csv.exists():
        return
    with course_csv.open("r", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    failed = [r["sample_course_id"] for r in rows if r.get("journey_success") == "0"]
    print(f"  journey_success=0 (blocked): {len(failed)} — {failed}")
    if len(failed) != 6:
        print("  [WARN] expected 6 blocked courses")
    else:
        print("  OK (6 blocked)")


def _check_wave_fallback(course_csv: Path):
    if not course_csv.exists():
        return
    with course_csv.open("r", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    fallback = [r["sample_course_id"] for r in rows if r.get("wave_collection_mode") == "browser_fallback"]
    print(f"  browser_fallback: {len(fallback)} — {fallback}")
    if len(fallback) != 2:
        print("  [WARN] expected 2 browser_fallback rows")
    else:
        print("  OK (2 browser_fallback)")


if __name__ == "__main__":
    main()
