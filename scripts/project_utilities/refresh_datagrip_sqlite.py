#!/usr/bin/env python3
"""
Refresh the local DataGrip SQLite preview database from canonical CSV files.

This script creates a derived, disposable SQL view of the project dataset.
It never writes to data/collection/, data/masters/, or artifacts/.
"""

from __future__ import annotations

import csv
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
DB_PATH = REPO_ROOT / "tmp/datagrip/university_audit_preview.sqlite"

TABLES = [
    ("university_sample_master", "data/masters/university_sample_master.csv"),
    ("course_sample_master", "data/masters/course_sample_master.csv"),
    ("crawl_run", "data/collection/crawl_run.csv"),
    ("source_document", "data/collection/source_document.csv"),
    ("source_fragment", "data/collection/source_fragment.csv"),
    ("journey_log", "data/collection/journey_log.csv"),
    ("journey_matrix", "data/collection/journey_matrix.csv"),
    ("journey_artifact_manifest", "data/collection/journey_artifact_manifest.csv"),
    ("lighthouse_results", "data/collection/lighthouse_results.csv"),
    ("wave_results", "data/collection/wave_results.csv"),
    ("wave_items_long", "data/collection/wave_items_long.csv"),
    ("serp_observations", "data/collection/serp_observations.csv"),
    ("serp_results_long", "data/collection/serp_results_long.csv"),
    ("structural_indicators", "data/collection/structural_indicators.csv"),
    ("structural_evidence_long", "data/collection/structural_evidence_long.csv"),
]

INDEXES = [
    ("idx_course_sample_master_university_id", "course_sample_master", "university_id"),
    ("idx_source_document_crawl_run_id", "source_document", "crawl_run_id"),
    ("idx_source_document_university_id", "source_document", "university_id"),
    ("idx_source_document_sample_course_id", "source_document", "sample_course_id"),
    ("idx_source_fragment_source_document_id", "source_fragment", "source_document_id"),
    ("idx_journey_log_journey_id", "journey_log", "journey_id"),
    ("idx_journey_log_sample_course_id", "journey_log", "sample_course_id"),
    ("idx_journey_matrix_university_id", "journey_matrix", "university_id"),
    ("idx_journey_matrix_sample_course_id", "journey_matrix", "sample_course_id"),
    ("idx_journey_artifact_manifest_journey_id", "journey_artifact_manifest", "journey_id"),
    ("idx_lighthouse_source_document_id", "lighthouse_results", "source_document_id"),
    ("idx_lighthouse_sample_course_id", "lighthouse_results", "sample_course_id"),
    ("idx_wave_source_document_id", "wave_results", "source_document_id"),
    ("idx_wave_items_target_id", "wave_items_long", "target_id"),
    ("idx_serp_observations_course_id", "serp_observations", "course_id"),
    ("idx_serp_results_observation_id", "serp_results_long", "serp_observation_id"),
]


def quote_identifier(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def import_csv(conn: sqlite3.Connection, table_name: str, relative_path: str) -> int:
    path = REPO_ROOT / relative_path
    if not path.exists():
        raise FileNotFoundError(path)

    with path.open(encoding="utf-8", newline="") as f:
        reader = csv.reader(f)
        try:
            headers = next(reader)
        except StopIteration:
            headers = []

        quoted_table = quote_identifier(table_name)
        conn.execute(f"DROP TABLE IF EXISTS {quoted_table}")

        if not headers:
            conn.execute(f"CREATE TABLE {quoted_table} (_empty TEXT)")
            return 0

        columns_sql = ", ".join(f"{quote_identifier(h)} TEXT" for h in headers)
        conn.execute(f"CREATE TABLE {quoted_table} ({columns_sql})")

        placeholders = ", ".join("?" for _ in headers)
        insert_sql = f"INSERT INTO {quoted_table} VALUES ({placeholders})"
        rows = list(reader)
        conn.executemany(insert_sql, rows)
        return len(rows)


def refresh() -> list[tuple[str, int, str]]:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    imported_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    imported: list[tuple[str, int, str]] = []

    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("PRAGMA foreign_keys = OFF")

        for table_name, relative_path in TABLES:
            row_count = import_csv(conn, table_name, relative_path)
            imported.append((table_name, row_count, relative_path))

        conn.execute("DROP TABLE IF EXISTS _import_metadata")
        conn.execute(
            """
            CREATE TABLE _import_metadata (
                table_name TEXT PRIMARY KEY,
                source_path TEXT NOT NULL,
                imported_at TEXT NOT NULL,
                row_count INTEGER NOT NULL,
                notes TEXT
            )
            """
        )
        conn.executemany(
            """
            INSERT INTO _import_metadata
            (table_name, source_path, imported_at, row_count, notes)
            VALUES (?, ?, ?, ?, ?)
            """,
            [
                (
                    table_name,
                    source_path,
                    imported_at,
                    row_count,
                    "derived import from canonical CSV; refresh after collection batches",
                )
                for table_name, row_count, source_path in imported
            ],
        )

        for index_name, table_name, column_name in INDEXES:
            conn.execute(
                "CREATE INDEX IF NOT EXISTS "
                f"{quote_identifier(index_name)} ON "
                f"{quote_identifier(table_name)}({quote_identifier(column_name)})"
            )

    return imported


def main() -> int:
    imported = refresh()
    print(f"Refreshed {DB_PATH.relative_to(REPO_ROOT)}")
    for table_name, row_count, source_path in imported:
        print(f"{table_name}: {row_count} rows from {source_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
