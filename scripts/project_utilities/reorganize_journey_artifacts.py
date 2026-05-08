#!/usr/bin/env python3

from __future__ import annotations

import csv
import shutil
import textwrap
import unicodedata
from collections import defaultdict
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS_DIR = ROOT / "artifacts"
RUNS_DIR = ARTIFACTS_DIR / "runs"
JOURNEYS_DIR = ARTIFACTS_DIR / "journeys"
PROBLEMS_DIR = ROOT / "problems"
DOCS_DIR = ROOT / "docs"
DATA_DIR = ROOT / "data"
DATA_COLLECTION_DIR = DATA_DIR / "collection"
DATA_MASTERS_DIR = DATA_DIR / "masters"

COLUMN_ORDER_MANIFEST = [
    "journey_artifact_id",
    "journey_id",
    "university_id",
    "sample_course_id",
    "crawl_run_id",
    "journey_run_id",
    "source_document_id",
    "artifact_category",
    "artifact_role",
    "origin_path",
    "artifact_path",
    "artifact_status",
    "notes",
]

COLUMN_ORDER_CROSSWALK = [
    "sample_course_id",
    "journey_id",
    "university_id",
    "pilot_course_name",
    "pilot_source_document_id",
    "match_status",
    "notes",
]

SUPPORT_BATCH_SPECS = {
    "CR018": {
        "tmp_dir": ROOT / "tmp" / "journey_j007_009",
        "journey_files": {
            "unifi_home.html": [("J007", "homepage"), ("J008", "homepage")],
            "unifi_hub.html": [("J007", "programmes_hub"), ("J008", "programmes_hub")],
            "unifi_triennali.html": [("J007", "degree_type_listing")],
            "unifi_triennali_search_j007.html": [("J007", "listing_search_result")],
            "unifi_magistrali.html": [("J008", "degree_type_listing")],
            "unifi_magistrali_search_j008.html": [("J008", "listing_search_result")],
            "unisi_home.html": [("J009", "homepage")],
            "unisi_didattica.html": [("J009", "programmes_hub")],
            "unisi_corsi_2025_2026.html": [("J009", "annual_listing")],
            "unisi_degree_89917.html": [("J009", "course_sheet")],
        },
    },
    "CR020": {
        "tmp_dir": ROOT / "tmp" / "journey_j010_012",
        "journey_files": {
            "unisi_home.html": [("J010", "homepage")],
            "unisi_didattica.html": [("J010", "programmes_hub")],
            "unisi_degree_22463.html": [("J010", "historical_course_sheet")],
            "unisi_degree_82714.html": [("J010", "course_sheet")],
            "unisi_course_site_j010.html": [("J010", "dedicated_course_site")],
            "unito_home.html": [("J011", "homepage"), ("J012", "homepage")],
            "unito_didattica.html": [("J011", "programmes_hub"), ("J012", "programmes_hub")],
            "unito_offerta_formativa.html": [("J011", "intermediate_navigation"), ("J012", "intermediate_navigation")],
            "unito_corsi_di_studio.html": [("J011", "course_listing"), ("J012", "course_listing")],
            "unito_search_j011.html": [("J011", "autocomplete_request")],
            "unito_lista_j011.html": [("J011", "listing_result")],
            "unito_c011.html": [("J011", "course_page")],
            "unito_search_j012.html": [("J012", "autocomplete_request")],
            "unito_lista_j012.html": [("J012", "listing_result")],
            "unito_c012.html": [("J012", "course_page")],
        },
    },
    "CR021": {
        "tmp_dir": ROOT / "tmp" / "journey_j013_015",
        "journey_files": {
            "unige_home.html": [("J013", "homepage"), ("J014", "homepage")],
            "unige_corsi_hub.html": [("J013", "course_portal_home"), ("J014", "course_portal_home")],
            "unige_corsidilaurea.html": [("J013", "course_portal_listing"), ("J014", "course_portal_listing")],
            "unige_corsi_triennale.html": [("J013", "degree_type_listing")],
            "unige_course_j013_11938.html": [("J013", "course_page")],
            "unige_corsi_magistrale.html": [("J014", "degree_type_listing")],
            "unige_course_j014_11945.html": [("J014", "course_page")],
            "unimib_home.html": [("J015", "homepage")],
            "unimib_studiare.html": [("J015", "intermediate_navigation")],
            "unimib_offerta_formativa.html": [("J015", "programmes_hub")],
            "unimib_area_formazione.html": [("J015", "disciplinary_area")],
            "unimib_area_sociologica.html": [("J015", "disciplinary_area_context")],
            "unimib_course_j015.html": [("J015", "course_page")],
        },
    },
    "CR022": {
        "tmp_dir": ROOT / "tmp" / "journey_support_backfill_j001_j006",
        "journey_files": {
            "unibo_home.html": [("J001", "homepage"), ("J002", "homepage")],
            "unibo_search_j001.html": [("J001", "search_results")],
            "unibo_search_filtered_j001.html": [("J001", "filtered_search_results")],
            "unibo_course_card_j001.html": [("J001", "course_card")],
            "unibo_course_site_j001.html": [("J001", "dedicated_course_site")],
            "unibo_studiare.html": [("J002", "programmes_hub")],
            "unibo_magistrali_listing.html": [("J002", "degree_type_listing")],
            "unipd_home.html": [("J003", "homepage"), ("J004", "homepage")],
            "unipd_corsi_di_laurea.html": [("J003", "programmes_hub"), ("J004", "programmes_hub")],
            "unipi_home.html": [("J005", "homepage"), ("J006", "homepage")],
            "unipi_search_j005.html": [("J005", "search_results")],
            "unipi_course_j005.html": [("J005", "course_page")],
            "unipi_search_j006.html": [("J006", "search_results")],
            "unipi_course_j006.html": [("J006", "course_page")],
        },
    },
}


def slugify(value: str, max_length: int = 80) -> str:
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    value = value.lower()
    value = re.sub(r"[^a-z0-9]+", "-", value).strip("-")
    if not value:
        return "item"
    return value[:max_length].rstrip("-")


def normalize_text(value: str) -> str:
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    value = value.lower()
    value = re.sub(r"[^a-z0-9]+", " ", value).strip()
    return re.sub(r"\s+", " ", value)


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def relative(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def write_markdown(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.rstrip() + "\n", encoding="utf-8")


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def move_path(src: Path, dst: Path) -> None:
    if not src.exists():
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        return
    shutil.move(str(src), str(dst))


def copy_file(src: Path, dst: Path) -> bool:
    if not src.exists():
        return False
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    return True


def main() -> None:
    crawl_run_path = DATA_COLLECTION_DIR / "crawl_run.csv"
    source_document_path = DATA_COLLECTION_DIR / "source_document.csv"
    source_fragment_path = DATA_COLLECTION_DIR / "source_fragment.csv"
    journey_log_path = DATA_COLLECTION_DIR / "journey_log.csv"
    journey_matrix_path = DATA_COLLECTION_DIR / "journey_matrix.csv"
    course_master_path = DATA_MASTERS_DIR / "course_sample_master.csv"
    university_master_path = DATA_MASTERS_DIR / "university_sample_master.csv"

    crawl_runs = read_csv(crawl_run_path)
    source_documents = read_csv(source_document_path)
    source_fragments = read_csv(source_fragment_path)
    journey_logs = read_csv(journey_log_path)
    journey_matrix = read_csv(journey_matrix_path)
    course_master = read_csv(course_master_path)
    university_master = read_csv(university_master_path)

    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    JOURNEYS_DIR.mkdir(parents=True, exist_ok=True)
    PROBLEMS_DIR.mkdir(parents=True, exist_ok=True)
    run_dir_by_id: dict[str, Path] = {}
    artifacts_root_replacements: dict[str, str] = {}

    for row in crawl_runs:
        if row["run_label"].startswith("ch26_"):
            row["run_label"] = row["run_label"][5:]
        if row["staging_schema_version"].startswith("ch26_"):
            row["staging_schema_version"] = row["staging_schema_version"][5:]

        run_dir = RUNS_DIR / f"{row['crawl_run_id']}_{row['run_label']}"
        run_dir_by_id[row["crawl_run_id"]] = run_dir

        old_root = row["artifacts_root"]
        if old_root:
            old_root_path = ROOT / old_root
            if old_root_path.exists() and old_root_path != run_dir:
                move_path(old_root_path, run_dir)
            else:
                run_dir.mkdir(parents=True, exist_ok=True)
            artifacts_root_replacements[old_root] = relative(run_dir)
        else:
            run_dir.mkdir(parents=True, exist_ok=True)

        row["artifacts_root"] = relative(run_dir)

    for row in source_documents:
        storage_path = row["storage_path"]
        for old_root, new_root in sorted(artifacts_root_replacements.items(), key=lambda item: len(item[0]), reverse=True):
            if storage_path == old_root or storage_path.startswith(old_root + "/"):
                row["storage_path"] = storage_path.replace(old_root, new_root, 1)
                break

    pilot_report_src = ROOT / "pilot" / "lm92_report.md"
    pilot_report_dst = DOCS_DIR / "pilot_lm92_report.md"
    if pilot_report_src.exists():
        move_path(pilot_report_src, pilot_report_dst)

    pilot_file_moves = {
        ROOT / "pilot" / "audit_matrix_lm92.csv": DATA_COLLECTION_DIR / "pilot_audit_matrix.csv",
        ROOT / "pilot" / "link_homepage_corsi_magistrali_lm92.csv": DATA_COLLECTION_DIR / "pilot_link_homepage_corsi_magistrali.csv",
        ROOT / "pilot" / "data_audit_LM-92" / "course_seed.csv": DATA_COLLECTION_DIR / "pilot_course_seed.csv",
    }
    for src, dst in pilot_file_moves.items():
        if src.exists():
            move_path(src, dst)

    legacy_pilot_dir = ROOT / "pilot"
    if legacy_pilot_dir.exists():
        for child in sorted(legacy_pilot_dir.glob("**/*"), reverse=True):
            if child.is_dir() and not any(child.iterdir()):
                child.rmdir()
        if legacy_pilot_dir.exists() and not any(legacy_pilot_dir.iterdir()):
            legacy_pilot_dir.rmdir()

    pre_j007_issues = ROOT / "tmp" / "prej007_issues"
    if pre_j007_issues.exists():
        move_path(pre_j007_issues, PROBLEMS_DIR / "pre_j007_navigation_checks" / "evidence")

    for run_id, spec in SUPPORT_BATCH_SPECS.items():
        tmp_dir = spec["tmp_dir"]
        destination = run_dir_by_id[run_id] / "batch_support"
        if tmp_dir.exists():
            move_path(tmp_dir, destination)
        else:
            destination.mkdir(parents=True, exist_ok=True)

    for tmp_child in ROOT.joinpath("tmp").glob("journey_*"):
        if tmp_child.is_dir() and not any(tmp_child.iterdir()):
            tmp_child.rmdir()

    source_document_by_id = {row["source_document_id"]: row for row in source_documents}
    source_fragments_by_document = defaultdict(list)
    for row in source_fragments:
        source_fragments_by_document[row["source_document_id"]].append(row)

    journey_logs_by_journey = defaultdict(list)
    for row in journey_logs:
        journey_logs_by_journey[row["journey_id"]].append(row)

    source_documents_by_journey = defaultdict(list)
    source_documents_by_url = defaultdict(list)
    for row in source_documents:
        if row["journey_id"]:
            source_documents_by_journey[row["journey_id"]].append(row)
        source_documents_by_url[row["url"]].append(row)
        source_documents_by_url[row["final_url"]].append(row)

    source_documents_by_university_role = defaultdict(list)
    source_documents_by_run = defaultdict(list)
    for row in source_documents:
        source_documents_by_university_role[(row["university_id"], row["page_role"])].append(row)
        source_documents_by_run[row["crawl_run_id"]].append(row)

    journey_matrix_by_id = {row["journey_id"]: row for row in journey_matrix}
    course_master_by_id = {row["sample_course_id"]: row for row in course_master}
    university_master_by_id = {row["university_id"]: row for row in university_master}

    pilot_audit_matrix_path = DATA_COLLECTION_DIR / "pilot_audit_matrix.csv"
    pilot_crosswalk_path = DATA_COLLECTION_DIR / "pilot_course_journey_crosswalk.csv"

    pilot_audit_rows = read_csv(pilot_audit_matrix_path)
    pilot_audit_by_journey = {row["journey_id"]: row for row in pilot_audit_rows}
    crosswalk_rows = read_csv(pilot_crosswalk_path)
    crosswalk_by_journey = {row["journey_id"]: row for row in crosswalk_rows}

    manifest_rows: list[dict[str, str]] = []
    artifact_counter = 1

    def add_manifest_row(
        *,
        journey_id: str,
        university_id: str,
        sample_course_id: str,
        crawl_run_id: str = "",
        journey_run_id: str = "",
        source_document_id: str = "",
        artifact_category: str,
        artifact_role: str,
        origin_path: str,
        artifact_path: str,
        artifact_status: str,
        notes: str,
    ) -> None:
        nonlocal artifact_counter
        manifest_rows.append(
            {
                "journey_artifact_id": f"JA{artifact_counter:05d}",
                "journey_id": journey_id,
                "university_id": university_id,
                "sample_course_id": sample_course_id,
                "crawl_run_id": crawl_run_id,
                "journey_run_id": journey_run_id,
                "source_document_id": source_document_id,
                "artifact_category": artifact_category,
                "artifact_role": artifact_role,
                "origin_path": origin_path,
                "artifact_path": artifact_path,
                "artifact_status": artifact_status,
                "notes": notes,
            }
        )
        artifact_counter += 1

    for run in crawl_runs:
        run_dir = run_dir_by_id[run["crawl_run_id"]]
        source_doc_count = len(source_documents_by_run[run["crawl_run_id"]])
        run_readme = textwrap.dedent(
            f"""
            # {run['crawl_run_id']} | {run['run_label']}

            - Scope: `{run['run_scope']}`
            - Started: `{run['started_at']}`
            - Finished: `{run['finished_at']}`
            - Artifact root: `{run['artifacts_root']}`
            - Source documents in run: `{source_doc_count}`
            - Notes: {run['notes']}
            """
        ).strip()
        write_markdown(run_dir / "README.md", run_readme)

    pilot_report_rel = relative(pilot_report_dst) if pilot_report_dst.exists() else ""

    for row in journey_matrix:
        journey_id = row["journey_id"]
        sample_course_id = row["sample_course_id"]
        university_id = row["university_id"]
        course_name = row["course_name"]
        journey_dir = JOURNEYS_DIR / f"{journey_id}_{sample_course_id}_{slugify(course_name, 64)}"
        metadata_dir = ensure_dir(journey_dir / "metadata")
        source_dir = ensure_dir(journey_dir / "source")
        journey_support_dir = ensure_dir(journey_dir / "journey_support")
        pilot_dir = ensure_dir(journey_dir / "pilot_reference")

        journey_log_rows = journey_logs_by_journey.get(journey_id, [])
        write_csv(metadata_dir / "journey_matrix_row.csv", list(row.keys()), [row])
        if journey_log_rows:
            write_csv(metadata_dir / "journey_log.csv", list(journey_log_rows[0].keys()), journey_log_rows)
        else:
            write_csv(metadata_dir / "journey_log.csv", list(journey_logs[0].keys()), [])
        write_csv(metadata_dir / "course_master_row.csv", list(course_master_by_id[sample_course_id].keys()), [course_master_by_id[sample_course_id]])
        write_csv(metadata_dir / "university_master_row.csv", list(university_master_by_id[university_id].keys()), [university_master_by_id[university_id]])

        selected_source_ids: set[str] = set()

        def add_source_row(source_row: dict[str, str] | None) -> None:
            if not source_row:
                return
            source_document_id = source_row["source_document_id"]
            if source_document_id in selected_source_ids:
                return
            selected_source_ids.add(source_document_id)
            parent_id = source_row["parent_source_document_id"]
            if parent_id:
                add_source_row(source_document_by_id.get(parent_id))

        for source_row in source_documents_by_journey.get(journey_id, []):
            add_source_row(source_row)

        for url in [row["journey_start_url"], row["journey_hub_url"], row["journey_target_url"]]:
            for source_row in source_documents_by_url.get(url, []):
                add_source_row(source_row)

        if not any(source_document_by_id[source_id]["page_role"] == "university_homepage" for source_id in selected_source_ids):
            for source_row in source_documents_by_university_role.get((university_id, "university_homepage"), []):
                add_source_row(source_row)
                break
        if not any(source_document_by_id[source_id]["page_role"] == "programmes_hub" for source_id in selected_source_ids):
            for source_row in source_documents_by_university_role.get((university_id, "programmes_hub"), []):
                add_source_row(source_row)
                break

        selected_source_rows = [source_document_by_id[source_id] for source_id in sorted(selected_source_ids)]
        selected_fragment_rows: list[dict[str, str]] = []
        for source_row in selected_source_rows:
            selected_fragment_rows.extend(source_fragments_by_document.get(source_row["source_document_id"], []))

        write_csv(source_dir / "source_document_rows.csv", list(source_documents[0].keys()), selected_source_rows)
        write_csv(source_dir / "source_fragment_rows.csv", list(source_fragments[0].keys()), selected_fragment_rows)

        bundle_support_count = 0
        for source_row in selected_source_rows:
            source_file = ROOT / source_row["storage_path"]
            destination_file = source_dir / source_file.name
            copied = copy_file(source_file, destination_file)
            add_manifest_row(
                journey_id=journey_id,
                university_id=university_id,
                sample_course_id=sample_course_id,
                crawl_run_id=source_row["crawl_run_id"],
                source_document_id=source_row["source_document_id"],
                artifact_category="source_document",
                artifact_role=source_row["page_role"],
                origin_path=source_row["storage_path"],
                artifact_path=relative(destination_file) if copied else "",
                artifact_status="copied" if copied else "missing",
                notes=source_row["title"],
            )
            header_candidate = source_file.with_name(source_file.stem + ".headers.txt")
            header_destination = source_dir / header_candidate.name
            header_copied = copy_file(header_candidate, header_destination)
            add_manifest_row(
                journey_id=journey_id,
                university_id=university_id,
                sample_course_id=sample_course_id,
                crawl_run_id=source_row["crawl_run_id"],
                source_document_id=source_row["source_document_id"],
                artifact_category="source_header",
                artifact_role=source_row["page_role"],
                origin_path=relative(header_candidate) if header_candidate.exists() else "",
                artifact_path=relative(header_destination) if header_copied else "",
                artifact_status="copied" if header_copied else "missing",
                notes=f"Header sidecar for {source_row['source_document_id']}",
            )

        journey_run_ids = sorted({entry["journey_run_id"] for entry in journey_log_rows if entry["journey_run_id"]})
        for journey_run_id in journey_run_ids:
            add_manifest_row(
                journey_id=journey_id,
                university_id=university_id,
                sample_course_id=sample_course_id,
                journey_run_id=journey_run_id,
                artifact_category="journey_run",
                artifact_role="log_reference",
                origin_path=relative(metadata_dir / "journey_log.csv"),
                artifact_path=relative(metadata_dir / "journey_log.csv"),
                artifact_status="generated",
                notes=f"Primary observed journey log for {journey_run_id}",
            )

        for crawl_run_id, spec in SUPPORT_BATCH_SPECS.items():
            run_support_dir = run_dir_by_id[crawl_run_id] / "batch_support"
            for filename, journey_targets in spec["journey_files"].items():
                for target_journey_id, artifact_role in journey_targets:
                    if target_journey_id != journey_id:
                        continue
                    origin_file = run_support_dir / filename
                    destination_file = journey_support_dir / f"{crawl_run_id}_{filename}"
                    copied = copy_file(origin_file, destination_file)
                    if copied:
                        bundle_support_count += 1
                    journey_run_id = journey_run_ids[0] if len(journey_run_ids) == 1 else ""
                    add_manifest_row(
                        journey_id=journey_id,
                        university_id=university_id,
                        sample_course_id=sample_course_id,
                        crawl_run_id=crawl_run_id,
                        journey_run_id=journey_run_id,
                        artifact_category="journey_support",
                        artifact_role=artifact_role,
                        origin_path=relative(origin_file) if origin_file.exists() else str(origin_file),
                        artifact_path=relative(destination_file) if copied else "",
                        artifact_status="copied" if copied else "missing",
                        notes=f"Support capture migrated from completed batch {crawl_run_id}",
                    )

        completed_status = row["measurement_status"] == "manual_v1_complete"
        if completed_status and bundle_support_count == 0:
            add_manifest_row(
                journey_id=journey_id,
                university_id=university_id,
                sample_course_id=sample_course_id,
                artifact_category="journey_support",
                artifact_role="support_archive",
                origin_path="",
                artifact_path="",
                artifact_status="missing",
                notes="Completed journey has no surviving HTML support captures beyond the structured log and source bundle.",
            )

        crosswalk_row = crosswalk_by_journey.get(journey_id)
        pilot_status = "not_applicable"
        if crosswalk_row:
            pilot_status = crosswalk_row["match_status"]
            write_csv(pilot_dir / "course_journey_crosswalk_row.csv", COLUMN_ORDER_CROSSWALK, [crosswalk_row])
            pilot_source_doc = source_document_by_id.get(crosswalk_row["pilot_source_document_id"])
            pilot_audit_row = pilot_audit_by_journey.get(journey_id)
            pilot_source_fragments_rows = source_fragments_by_document.get(
                crosswalk_row["pilot_source_document_id"], []
            )
            if pilot_source_doc:
                write_csv(pilot_dir / "pilot_source_document_row.csv", list(pilot_source_doc.keys()), [pilot_source_doc])
            else:
                write_csv(pilot_dir / "pilot_source_document_row.csv", list(source_documents[0].keys()), [])
            if pilot_audit_row:
                write_csv(pilot_dir / "pilot_audit_row.csv", list(pilot_audit_row.keys()), [pilot_audit_row])
            else:
                write_csv(pilot_dir / "pilot_audit_row.csv", list(pilot_audit_rows[0].keys()), [])
            write_csv(pilot_dir / "pilot_source_fragment_rows.csv", list(source_fragments[0].keys()), pilot_source_fragments_rows)

            raw_html_path = None
            raw_html_status = "missing"
            raw_html_note = "Original pilot raw HTML is missing from the local workspace and survives only as metadata."
            raw_html_bundle_path = None
            if pilot_source_doc:
                ext = pilot_source_doc["file_ext"] or ".html"
                exact_storage_path = pilot_source_doc["storage_path"]
                exact_raw_path = ROOT / exact_storage_path if exact_storage_path else None
                reconstructed_raw_path = RUNS_DIR / "CR023_2026-04-22_pilot-raw-html-backfill" / f"{pilot_source_doc['source_document_id']}{ext}"
                if exact_raw_path and exact_raw_path.exists():
                    raw_html_path = exact_raw_path
                    raw_html_status = "available"
                    raw_html_note = "Historical pilot raw HTML restored locally and hash-verified against the canonical pilot SHA-256."
                elif reconstructed_raw_path.exists():
                    raw_html_path = reconstructed_raw_path
                    raw_html_status = "reconstructed"
                    raw_html_note = "Current HTML fallback captured for local inspection; SHA-256 differs from the historical pilot record, so the original bytes remain unavailable."
                if raw_html_path and raw_html_path.exists():
                    raw_html_bundle_path = pilot_dir / raw_html_path.name
                    copy_file(raw_html_path, raw_html_bundle_path)
            pilot_notes = [
                f"- Crosswalk status: `{crosswalk_row['match_status']}`",
                f"- Current course: `{crosswalk_row['sample_course_id']}` / `{crosswalk_row['journey_id']}`",
                f"- Historical pilot source document: `{crosswalk_row['pilot_source_document_id']}`",
            ]
            if pilot_report_rel:
                pilot_notes.append(f"- Report path: `{pilot_report_rel}`")
            if pilot_source_doc:
                original_raw_path = pilot_source_doc["notes"]
                if "original raw path=" in original_raw_path:
                    original_raw_path = original_raw_path.split("original raw path=", 1)[1]
                pilot_notes.append(f"- Original pilot raw HTML path: `{original_raw_path}`")
            if raw_html_status == "available":
                pilot_notes.append("- Original pilot raw HTML available locally: `yes (exact hash-verified)`")
            elif raw_html_status == "reconstructed":
                pilot_notes.append("- Original pilot raw HTML available locally: `yes (reconstructed current fallback)`")
            else:
                pilot_notes.append("- Original pilot raw HTML available locally: `no`")
            if raw_html_bundle_path:
                pilot_notes.append(f"- Local pilot raw HTML bundle: `{relative(raw_html_bundle_path)}`")
            pilot_notes.append(f"- Fidelity note: {raw_html_note}")
            write_markdown(
                pilot_dir / "README.md",
                "# Pilot Reference\n\n" + "\n".join(pilot_notes),
            )
            add_manifest_row(
                journey_id=journey_id,
                university_id=university_id,
                sample_course_id=sample_course_id,
                artifact_category="pilot_reference",
                artifact_role="crosswalk",
                origin_path=relative(DATA_COLLECTION_DIR / "pilot_course_journey_crosswalk.csv"),
                artifact_path=relative(pilot_dir / "course_journey_crosswalk_row.csv"),
                artifact_status="generated",
                notes="Pilot metadata integrated as journey-level historical reference.",
            )
            add_manifest_row(
                journey_id=journey_id,
                university_id=university_id,
                sample_course_id=sample_course_id,
                artifact_category="pilot_reference",
                artifact_role="raw_html",
                origin_path=relative(raw_html_path) if raw_html_path and raw_html_path.exists() else "",
                artifact_path=relative(raw_html_bundle_path) if raw_html_bundle_path and raw_html_bundle_path.exists() else "",
                artifact_status=raw_html_status,
                notes=raw_html_note,
            )
        else:
            write_markdown(pilot_dir / "README.md", "# Pilot Reference\n\nThis journey is not part of the LM-92 pilot subset.")

        journey_readme = textwrap.dedent(
            f"""
            # {journey_id} | {course_name}

            - University: `{university_id}` — {row['university_name']}
            - Course id: `{sample_course_id}`
            - Measurement status: `{row['measurement_status']}`
            - Planned start: `{row['journey_start_url']}`
            - Planned hub: `{row['journey_hub_url']}`
            - Planned target: `{row['journey_target_url']}`
            - Source documents bundled: `{len(selected_source_rows)}`
            - Source fragments bundled: `{len(selected_fragment_rows)}`
            - Journey log events bundled: `{len(journey_log_rows)}`
            - Journey support captures bundled: `{bundle_support_count}`
            - Pilot reference status: `{pilot_status}`

            ## Folder guide

            - `metadata/` — extracted current dataset rows for this journey
            - `source/` — source-document rows, source-fragment rows, HTML snapshots, and header sidecars when available
            - `journey_support/` — migrated support captures from completed `tmp/` batches
            - `pilot_reference/` — historical LM-92 pilot reference material crosswalked to this journey
            """
        ).strip()
        write_markdown(journey_dir / "README.md", journey_readme)

        journey_manifest_rows = [row for row in manifest_rows if row["journey_id"] == journey_id]
        write_csv(journey_dir / "artifact_manifest.csv", COLUMN_ORDER_MANIFEST, journey_manifest_rows)

    write_csv(crawl_run_path, list(crawl_runs[0].keys()), crawl_runs)
    write_csv(source_document_path, list(source_documents[0].keys()), source_documents)
    write_csv(DATA_COLLECTION_DIR / "journey_artifact_manifest.csv", COLUMN_ORDER_MANIFEST, manifest_rows)

    write_markdown(
        ARTIFACTS_DIR / "README.md",
        textwrap.dedent(
            """
            # Artifacts

            - `runs/` — canonical per-run artifact roots
            - `journeys/` — per-journey bundles (`Jxxx`) containing current metadata, source snapshots, migrated support captures, and pilot references
            """
        ).strip(),
    )
    write_markdown(
        RUNS_DIR / "README.md",
        "# Run Artifacts\n\nEach subfolder corresponds to one `crawl_run_id` and stores the canonical run-level artifact root.",
    )
    write_markdown(
        JOURNEYS_DIR / "README.md",
        "# Journey Bundles\n\nEach `Jxxx` folder collects the material currently available for one sampled course journey.",
    )
    write_markdown(
        PROBLEMS_DIR / "README.md",
        "# Problems\n\nDetailed issue dossiers and supporting evidence live here. `issues.md` remains the human-readable index.",
    )


if __name__ == "__main__":
    main()
