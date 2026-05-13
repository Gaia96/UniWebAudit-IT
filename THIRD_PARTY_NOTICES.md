# Third-Party Notices and Service-Terms Review

Last checked: 2026-05-13.

This note is a practical release checklist, not legal advice. It records the
third-party content and external-service constraints identified in the repository.

## Summary

- No automated Google Search scraper or SERP API client was found in the scripts.
  SERP files appear to be manually compiled observations with screenshot
  evidence under `artifacts/runs/SERP_B*/serp/`.
- University source HTML and rendered screenshots are third-party evidence
  artifacts captured from public university web pages for research traceability.
- Lighthouse is run locally through the Lighthouse CI CLI, but the resulting
  reports and screenshots may embed third-party page content.
- WAVE is the main redistribution-risk item: the repository includes WAVE API
  collection code, raw WAVE JSON, summary CSVs, item-level CSVs, and analytical
  columns derived from WAVE counts.

## Google Search Screenshots

Relevant files:

- `artifacts/runs/SERP_B*/serp/*.png`
- SERP observation/result tables that cite those evidence screenshots.

Google's Search screenshot guidance covers use of Search screenshots in a
project. Its general rules say the interface should be shown realistically,
should not be modified, and should not imply Google endorsement. The guidance
also asks for a trademark attribution under images featuring Google Search and
notes that third-party content visible inside Google screenshots remains the
responsibility of the user. For print educational or instructional uses, such as
journals and other informative materials, Google says permission is not required
for Search page and result-page screenshots.

Repository notice:

> Screenshots are included only for research/documentation purposes.
> Third-party content remains property of respective owners.

Additional attribution used in `LICENSE.md`:

> Google and the Google logo are trademarks of Google LLC.

Sources:

- https://about.google/brand-resource-center/products-and-services/search-guidelines/
- https://policies.google.com/terms

## Google Search Collection Method

The repository's SERP scripts create, validate, and import manually collected
batch files. They do not issue automated requests to Google Search. This matters
because Google's Terms of Service restrict abusive uses and automated access to
service content in violation of machine-readable instructions, and
`https://www.google.com/robots.txt` disallows `/search` for general crawlers.

Public release posture:

- Keep SERP screenshots as research documentation only.
- Do not describe the screenshots or search-result excerpts as CC-licensed
  material.
- Avoid promotional or endorsement-implying uses.

Sources:

- https://policies.google.com/terms
- https://www.google.com/robots.txt

## WAVE / WebAIM

Relevant files:

- `scripts/phase2_wave/scripts/wave_collect.py`
- `scripts/phase2_wave/scripts/wave_extract.py`
- `scripts/phase2_wave/scripts/wave_browser_import.py`
- `scripts/phase2_wave/config/wave_config.yaml`
- `scripts/phase2_wave/data/raw/**`
- `data/collection/wave_results.csv`
- `data/collection/wave_items_long.csv`
- WAVE-derived columns in `data/analysis/audit_matrix.csv`,
  `data/analysis/audit_matrix_page.csv`, and
  `data/analysis/audit_matrix_ateneo.csv`

The local WAVE configuration uses the WebAIM WAVE API endpoint with
`reporttype: 4`, which returns counts plus item/location detail. The WAVE terms
state that permission is required before selling or redistributing WAVE reports
or data derived directly from WAVE, including counts and error listings. The API
documentation also describes API-key usage and asks users to limit calls to no
more than two simultaneous requests.

Public release posture:

- Obtain written permission from WebAIM before redistributing WAVE-derived raw
  JSON, WAVE summary/item CSVs, or WAVE-derived analytical columns; or
- Exclude those files/columns from the public release and keep only the WAVE
  collection/extraction scripts under MIT.

Sources:

- https://wave.webaim.org/terms
- https://wave.webaim.org/api/details

## University Website Evidence

Relevant files:

- `artifacts/journeys/**/source/*.html`
- `artifacts/journeys/**/source/*.headers.txt`
- `artifacts/journeys/**/journey_support/*.html`
- `artifacts/runs/CR*/**/*.html`
- `artifacts/runs/STRUN_001/source_rendered/*.html`
- `artifacts/runs/STRUN_001/screenshots/*.png`

These files are preserved as point-in-time research evidence. They may contain
university website text, marks, layout, scripts, or media. The repository's open
licenses do not grant rights in that third-party content.

Public release posture:

- Treat these files as research/documentation evidence, not as CC-licensed
  reusable web content.
- Keep provenance metadata so readers can inspect how values were derived.
- If a host requests removal of captured content, consider replacing the artifact
  with metadata, hashes, and minimal excerpts sufficient for provenance.
