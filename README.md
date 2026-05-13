# UniWebAudit-IT

This repository is a research companion package for the paper draft
*University Websites as Orientation Infrastructures: A Systematic Audit of
Navigability, Discoverability, Accessibility and Information Exposure in
Italian Universities*.

The package preserves the empirical material used to inspect and support the
paper's findings on Italian university websites as orientation infrastructure
for prospective students. It covers 20 universities and 41 degree programmes in
communication, media and neighbouring areas.

## Scope

The audit keeps four constructs analytically distinct:

- **Navigability**: structured homepage-to-course-page journeys, including path
  outcome, click depth, elapsed time, path archetype, internal search use and
  supporting evidence.
- **Discoverability**: controlled search-engine result observations for three
  query types per programme, with rank, match type and SERP evidence.
- **Accessibility / technical quality**: Lighthouse mobile audits and WAVE
  accessibility evaluations for homepages and course pages.
- **Information exposure**: structural extraction from course pages for
  decision-relevant fields such as title, degree level, academic year, study
  plan, admission information, deadlines and contacts.

Some measurements are automated or tool-assisted. Others are structured manual
observations, especially the navigation journeys and SERP collection. The
package therefore preserves evidence and provenance rather than claiming to be a
fully reproducible execution environment.

## Repository Structure

```text
UniWebAudit-IT/
  README.md
  CITATION.cff
  LICENSE.md
  data/
    masters/
    collection/
    analysis/
  artifacts/
    journeys/
    runs/
  scripts/
```

### `data/`

Canonical and derived CSV tables used for the paper.

- `data/masters/`: sample definition and query templates.
  - `university_sample_master.csv`: 20 institutions.
  - `course_sample_master.csv`: 41 degree programmes.
  - `serp_query_templates.csv`: the three controlled SERP query templates.
- `data/collection/`: phase-level collected or promoted data.
  - Journey data: `journey_matrix.csv`, `journey_log.csv`,
    `journey_artifact_manifest.csv`.
  - Technical and accessibility data: `lighthouse_results.csv`,
    `wave_results.csv`, `wave_items_long.csv`.
  - SERP data: `serp_observations.csv`, `serp_results_long.csv`.
  - Structural extraction data: `structural_indicators.csv`,
    `structural_evidence_long.csv`.
  - Source/provenance tables: `crawl_run.csv`, `source_document.csv`,
    `source_fragment.csv`.
  - Structured manual review tables: `manual_menu_clarity.csv`,
    `manual_review_orientation.csv`.
- `data/analysis/`: integrated analytical tables.
  - `audit_matrix.csv`: course-level matrix, 41 rows.
  - `audit_matrix_page.csv`: page-level matrix, 61 rows.
  - `audit_matrix_ateneo.csv`: institution-level matrix, 20 rows.

### `artifacts/`

Evidence archive for inspecting the empirical basis of the CSV values.

- `artifacts/journeys/`: per-course evidence bundles, including captured HTML,
  headers, extracted fragments, journey metadata and per-journey manifests.
- `artifacts/runs/`: run-level evidence grouped by `crawl_run_id` or batch ID,
  including journey capture runs, SERP screenshots, Lighthouse reports and
  structural extraction artifacts.

The large `CR034_lighthouse_mobile_v1` directory contains the preserved
Lighthouse output files. SERP batches are preserved under `SERP_B001` through
`SERP_B008`. `STRUN_001` contains structural extraction evidence.

### `scripts/`

Selected scripts, manifests and provenance inputs used to produce or promote
the dataset tables. This folder is intentionally not a full development
environment.

- `phase1_journey_audit/`: parsing and merge utilities for journey/course-page
  indicators.
- `phase2_lhci_collect/`: Lighthouse manifest and collection script.
- `phase2_wave/`: WAVE collection/extraction scripts, configuration, target
  manifest and preserved `WVRUN_001` raw JSON outputs.
- `phase3_serp/`: SERP batch creation, validation, import and coverage scripts,
  plus final manually compiled batch files for `SERP_B001` through `SERP_B008`.
- `phase4_structural_extraction/`: structural extraction scripts, keyword
  dictionary, extraction manifest, review queue and staging files.
- `phase5_matrix/`: scripts, SQL and thresholds used to build the integrated
  audit matrices.
- `project_utilities/`: small project-level utilities retained for provenance.

## Provenance Model

Values in `data/collection/` and `data/analysis/` are linked to collection runs,
source documents and evidence artifacts where available. The main join points
are:

- `crawl_run_id`: collection or processing run identifier.
- `source_document_id`: captured or evaluated source document identifier.
- `journey_id` / `sample_course_id` / `university_id`: sample and journey
  identifiers.
- `journey_artifact_manifest.csv`: links journey records to stored files in
  `artifacts/`.

The package retains raw or near-raw evidence for inspection: HTML captures,
headers, screenshots, raw Lighthouse reports, WAVE JSON-derived outputs, SERP
screenshots and structural extraction evidence.

## Reproducibility Notes

This release supports inspection, traceability and partial reruns of processing
steps. It does not provide a sealed computational environment or a guarantee
that live re-execution will reproduce identical results.

Important constraints:

- University websites are dynamic and may have changed after collection.
- SERP observations are inherently time-sensitive and may vary by date, locale,
  browser state and personalization controls.
- Lighthouse and WAVE results depend on tool versions, network conditions,
  rendering behaviour and availability of external services.
- WAVE API collection may require credentials or service access not included in
  this package.
- Manual observations follow structured protocols, but they remain
  observer-mediated. The package preserves the recorded observations and
  supporting evidence.

For these reasons, the strongest reproducibility claim is provenance-based:
reported values can be inspected against the included data tables and evidence
bundles.

## Running the scripts

The `scripts/` folder is organised by phase and is not a single executable
pipeline. Each phase can be attempted independently, against the CSV inputs in
`data/masters/` and `data/collection/`. There is no top-level orchestrator and
no shared dependency manifest: requirements are listed per phase below.

**General requirements**

- Python 3.10 or newer.
- A separate virtual environment is recommended (`python3 -m venv .venv && source .venv/bin/activate`).
- Scripts read and write paths relative to the repository root; run them from
  the `UniWebAudit-IT/` directory.

**Per-phase requirements**

- `phase1_journey_audit/` — Python standard library only.
- `phase2_lhci_collect/` — Python standard library, plus Node.js and the
  Lighthouse CI CLI (`npm install -g @lhci/cli`). The Python script is a
  wrapper that shells out to `lhci collect` and `lhci upload --target=filesystem`.
- `phase2_wave/` — `pip install requests pyyaml`. Requires a WAVE WebAIM API key
  in the `WAVE_API_KEY` environment variable (or a `.env` file at the package
  root). The browser-fallback flow is manual and does not require the API key.
- `phase3_serp/` — Python standard library only. SERP batch files were compiled
  manually under controlled conditions; the scripts validate, summarise and
  import them.
- `phase4_structural_extraction/` — see `scripts/phase4_structural_extraction/requirements.txt`
  (`beautifulsoup4`, `lxml`, `PyYAML`, `playwright`). After installing, run
  `python -m playwright install chromium` to fetch the browser binary used by
  `browser_render_capture.py`.
- `phase5_matrix/` — Python standard library only (uses `sqlite3` from stdlib).
  SQL files in `phase5_matrix/sql/` are designed for the preview SQLite built
  by `project_utilities/refresh_datagrip_sqlite.py`.

**Caveats**

- Some scripts assume specific run identifiers (`crawl_run_id`, batch IDs) and
  manifest entries already exist; they are designed for incremental collection,
  not for a clean re-execution from scratch.
- External services (WAVE API, search engines, university websites) may have
  changed in ways that affect rerun results. See **Reproducibility Notes** above.
- Several SERP and journey steps are manual by design and have no executable
  counterpart in `scripts/`.

## Methodological Disclaimers

The dataset is a point-in-time audit of a purposive sample. It should not be read
as a complete census of Italian university websites, a legal accessibility
certification, or a replacement for expert and user-based accessibility testing.

Automated accessibility tools identify only a subset of possible WCAG issues.
The paper treats Lighthouse and WAVE outputs as diagnostic signals, not as full
conformance assessments.

Search-engine observations were collected under controlled conditions, but
search results are dynamic. Rank and match-type findings should be interpreted
as documented observations from the collection window, not as stable properties
of the indexed web.

## Citation

Use `CITATION.cff` for machine-readable citation metadata. The companion paper
is currently under review; the citation record will be updated with venue, pages
and DOI upon acceptance.

## License and Third-Party Content

Original research data and documentation are released under
[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). Author-created source
code, scripts, SQL, and configuration files in `scripts/` are released under the
MIT License. See `LICENSE.md`.

Evidence artifacts may contain third-party material from university websites,
Google Search result pages, Lighthouse render captures, and WAVE outputs.
Screenshots are included only for research/documentation purposes. Third-party
content remains property of respective owners. Google and the Google logo are
trademarks of Google LLC.

WAVE-derived files and WAVE-derived columns in the analysis matrices may be
subject to WebAIM/WAVE redistribution restrictions. Before public redistribution
of those materials, review `THIRD_PARTY_NOTICES.md` and obtain permission or
exclude the affected WAVE-derived files/columns from the release.
