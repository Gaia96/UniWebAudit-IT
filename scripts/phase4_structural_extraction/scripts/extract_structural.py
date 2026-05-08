#!/usr/bin/env python3
"""
extract_structural.py — Phase 4 Step 5 (auto-first pass).

Reads:
    structural_extraction/extraction_manifest.csv
    structural_extraction/keyword_dictionary.yaml

For each manifest row, parses the artifact at expected_artifact_path and emits
candidate values for every indicator in the dictionary, applying the
location_type / local_findability / confidence rules from the methodology.

Outputs (staging only — not data/collection/):
    structural_extraction/staging/structural_indicators.staging.csv
    structural_extraction/staging/structural_evidence_long.staging.csv
    structural_extraction/logs/extract_structural.log

Run:
    python3 structural_extraction/scripts/extract_structural.py
    python3 structural_extraction/scripts/extract_structural.py --strun STRUN_001 --only C001,C002

Dependencies: beautifulsoup4, lxml, PyYAML.

NOTE on extensibility: this script is deliberately conservative. It records a
candidate row per indicator per course, even when not_observed, so that the
review queue (Step 6) sees every essential. Heuristics live in helper functions
and are tunable through keyword_dictionary.yaml without code changes.
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

REPO_ROOT = Path(__file__).resolve().parents[2]
MANIFEST = REPO_ROOT / "structural_extraction/extraction_manifest.csv"
DICT_PATH = REPO_ROOT / "structural_extraction/keyword_dictionary.yaml"
STAGING_DIR = REPO_ROOT / "structural_extraction/staging"
LOG_DIR = REPO_ROOT / "structural_extraction/logs"

WIDE_FIELDS = [
    "course_id", "university_id", "source_document_id", "target_url",
    "page_role", "extraction_run_id", "extracted_at", "render_mode",
    "course_title_observed",
]
INDICATORS_WIDE_PAIR = [
    "degree_level", "degree_class", "cfu", "duration", "academic_year",
    "location", "language", "study_plan", "admission_requirements",
    "admission_procedure", "deadlines", "fees_or_costs", "career_outcomes",
    "contacts", "official_regulation", "quality_or_satisfaction",
    "accessibility_services",
]

LONG_FIELDS = [
    "extraction_run_id", "course_id", "university_id", "source_document_id",
    "indicator_id", "indicator_label", "priority", "observed", "location_type",
    "local_findability", "evidence_text", "evidence_url", "evidence_selector",
    "evidence_document_type", "extraction_method", "confidence", "notes",
]


def load_yaml(path: Path) -> dict:
    try:
        import yaml
    except ImportError:
        logging.error("PyYAML not installed. See structural_extraction/requirements.txt")
        sys.exit(3)
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_manifest() -> list[dict[str, str]]:
    with MANIFEST.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def soupify(html_path: Path):
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        logging.error("beautifulsoup4 not installed. See structural_extraction/requirements.txt")
        sys.exit(3)
    html = html_path.read_text(encoding="utf-8", errors="replace")
    return BeautifulSoup(html, "lxml")


# ---------------------------------------------------------------------------
# Heuristics
# ---------------------------------------------------------------------------

def keyword_hit(text: str, patterns: Iterable[str]) -> str | None:
    text_lower = text.lower()
    for pat in patterns or []:
        if pat.lower() in text_lower:
            return pat
    return None


def regex_hit(text: str, patterns: Iterable[str]) -> str | None:
    for pat in patterns or []:
        try:
            m = re.search(pat, text, flags=re.IGNORECASE)
            if m:
                return m.group(0)
        except re.error:
            continue
    return None


def dt_label_match(label: str, keywords: Iterable[str], heading_signals: Iterable[str]) -> bool:
    """True if a short <dt>/<th> label semantically matches an indicator.

    Matches when: label is a prefix of any keyword, OR any keyword is a prefix
    of label (covers "Anno Accademico 2025/26" vs "anno accademico"), OR any
    heading_signal regex matches the label. Requires label >= 4 chars to avoid
    spurious matches on single-word cells.
    """
    if not label or len(label) < 4:
        return False
    lo = label.lower().strip(":")
    for kw in keywords or []:
        kl = kw.lower()
        if kl.startswith(lo) or lo.startswith(kl):
            return True
    for pat in heading_signals or []:
        try:
            if re.search(pat, label, flags=re.IGNORECASE):
                return True
        except re.error:
            continue
    return False


def detect_indicator(soup, indicator: dict, target_url: str) -> dict:
    """Return a candidate evidence row for one indicator on one page.

    The function does not assert truth; it emits the best candidate it can
    find with its confidence label. Review queue (Step 6) finalizes essentials.
    """
    iid = indicator["indicator_id"]
    keywords = indicator.get("keywords", [])
    heading_signals = indicator.get("heading_signals", [])
    selector_hints = indicator.get("selector_hints", [])
    pdf_label_hints = indicator.get("pdf_label_hints", [])

    candidate = {
        "observed": "not_observed",
        "location_type": "not_observed",
        "local_findability": "not_found",
        "evidence_text": "",
        "evidence_url": "",
        "evidence_selector": "",
        "evidence_document_type": "",
        "confidence": "not_observed",
        "notes": "",
    }

    # 1) Heading match (highest signal -> high confidence)
    for tag in soup.find_all(re.compile("^h[1-6]$")):
        text = tag.get_text(" ", strip=True)
        if regex_hit(text, heading_signals) or keyword_hit(text, keywords):
            candidate.update({
                "observed": "present",
                "location_type": "heading_or_summary",
                "local_findability": "direct",
                "evidence_text": text[:200],
                "evidence_url": target_url,
                "evidence_selector": tag.name,
                "evidence_document_type": "html",
                "confidence": "high",
            })
            return candidate

    # 1.5) Structured metadata: label+value pairs in CMS-generated HTML.
    # Italian university pages commonly expose course metadata as short label
    # elements (strong, b, dt, th, div.field-label, span.views-label) followed
    # by value siblings or value-containing parents — without using the longer
    # keyword phrases that the body-text scan requires.
    # We use three strategies (A/B/C) per candidate label element.
    LABEL_TAGS = ["strong", "b", "dt", "th", "span", "div", "label", "p"]
    for el in soup.find_all(LABEL_TAGS):
        # Only leaf-ish elements (at most one level of inline children)
        deep_children = [c for c in el.find_all() if c.name not in (
            "strong", "b", "em", "i", "span", "br", "abbr", "small")]
        if deep_children:
            continue
        label_text = el.get_text(" ", strip=True)
        if not label_text or len(label_text) > 80:
            continue
        if not dt_label_match(label_text, keywords, heading_signals):
            continue

        # Strategy A: parent element already contains label + value
        parent = el.parent
        if parent:
            ptext = parent.get_text(" ", strip=True)
            if len(ptext) > len(label_text) + 3 and len(ptext) < 300:
                loc = "table" if parent.name in ("td", "th", "tr") else "heading_or_summary"
                candidate.update({
                    "observed": "present",
                    "location_type": loc,
                    "local_findability": "direct",
                    "evidence_text": ptext[:200],
                    "evidence_url": target_url,
                    "evidence_selector": f"{el.name}@{parent.name}",
                    "evidence_document_type": "html",
                    "confidence": "high",
                })
                return candidate

        # Strategy B: next sibling of label element
        sib = el.find_next_sibling()
        if sib:
            val = sib.get_text(" ", strip=True)
            if val and 2 < len(val) < 150:
                candidate.update({
                    "observed": "present",
                    "location_type": "heading_or_summary",
                    "local_findability": "direct",
                    "evidence_text": f"{label_text}: {val}"[:200],
                    "evidence_url": target_url,
                    "evidence_selector": f"{el.name}+{sib.name}",
                    "evidence_document_type": "html",
                    "confidence": "high",
                })
                return candidate

        # Strategy C: next sibling of parent element
        if parent:
            psib = parent.find_next_sibling()
            if psib:
                val = psib.get_text(" ", strip=True)
                if val and 2 < len(val) < 150:
                    candidate.update({
                        "observed": "present",
                        "location_type": "heading_or_summary",
                        "local_findability": "direct",
                        "evidence_text": f"{label_text}: {val}"[:200],
                        "evidence_url": target_url,
                        "evidence_selector": f"{parent.name}>{el.name}+{psib.name}",
                        "evidence_document_type": "html",
                        "confidence": "high",
                    })
                    return candidate

    # 1.5b) aria-label attribute matching (e.g. UNIPI: <span aria-label="Lingua">Inglese Italiano</span>).
    for el in soup.find_all(attrs={"aria-label": True}):
        al = el.get("aria-label", "")
        if dt_label_match(al, keywords, heading_signals):
            val = el.get_text(" ", strip=True)
            if val and len(val) > 1 and len(val) < 150:
                candidate.update({
                    "observed": "present",
                    "location_type": "heading_or_summary",
                    "local_findability": "direct",
                    "evidence_text": f"{al}: {val}"[:200],
                    "evidence_url": target_url,
                    "evidence_selector": f"[aria-label={al}]",
                    "evidence_document_type": "html",
                    "confidence": "high",
                })
                return candidate

    # 1.5c) CSS class name containing a keyword (Drupal views-field pattern, e.g.
    # class="views-field-field-lingua-di-erogazione").  We look for the nearest
    # text-bearing descendant as the value.
    for kw in keywords or []:
        kw_slug = kw.lower().replace(" ", "-")
        if len(kw_slug) < 5:
            continue
        for el in soup.find_all(class_=re.compile(re.escape(kw_slug), re.I)):
            val = el.get_text(" ", strip=True)
            if val and 1 < len(val) < 150:
                candidate.update({
                    "observed": "present",
                    "location_type": "heading_or_summary",
                    "local_findability": "direct",
                    "evidence_text": val[:200],
                    "evidence_url": target_url,
                    "evidence_selector": f".{kw_slug}",
                    "evidence_document_type": "html",
                    "confidence": "high",
                })
                return candidate

    # 1.6) <table> rows with two cells — first cell as label, second as value.
    for table in soup.find_all("table"):
        for row in table.find_all("tr"):
            cells = row.find_all(["th", "td"])
            if len(cells) < 2:
                continue
            label = cells[0].get_text(" ", strip=True)
            if not label or len(label) > 80:
                continue
            if dt_label_match(label, keywords, heading_signals):
                val = cells[1].get_text(" ", strip=True)
                if val:
                    candidate.update({
                        "observed": "present",
                        "location_type": "table",
                        "local_findability": "direct",
                        "evidence_text": f"{label}: {val}"[:200],
                        "evidence_url": target_url,
                        "evidence_selector": "table th+td",
                        "evidence_document_type": "html",
                        "confidence": "high",
                    })
                    return candidate

    # 2) Selector hints (tab/accordion/table containers)
    for sel in selector_hints:
        try:
            for el in soup.select(sel):
                text = el.get_text(" ", strip=True)[:200]
                if not text:
                    continue
                if keyword_hit(text, keywords) or regex_hit(text, heading_signals):
                    loc = "tab" if "tab" in sel else (
                        "accordion" if "accordion" in sel or "details" in sel else "inline_html")
                    candidate.update({
                        "observed": "present",
                        "location_type": loc,
                        "local_findability": "direct" if loc == "inline_html" else "one_click",
                        "evidence_text": text,
                        "evidence_url": target_url,
                        "evidence_selector": sel,
                        "evidence_document_type": "html",
                        "confidence": "medium",
                    })
                    return candidate
        except Exception:
            continue

    # 3) Anchor labels: find <a> whose text matches keywords/pdf_label_hints
    for a in soup.find_all("a", href=True):
        atext = a.get_text(" ", strip=True)
        if not atext:
            continue
        href = a["href"]
        if href.lower().endswith(".pdf") or "/pdf" in href.lower():
            if keyword_hit(atext, pdf_label_hints) or keyword_hit(atext, keywords):
                candidate.update({
                    "observed": "present",
                    "location_type": "linked_pdf",
                    "local_findability": "document_link",
                    "evidence_text": atext[:200],
                    "evidence_url": href,
                    "evidence_selector": "a[pdf]",
                    "evidence_document_type": "pdf",
                    "confidence": "medium",
                })
                return candidate
        if keyword_hit(atext, keywords):
            # External vs internal? rough host check.
            ext = href.startswith("http") and not (target_url.split("/")[2] in href if "//" in target_url else False)
            candidate.update({
                "observed": "present",
                "location_type": "external_official_portal" if ext else "linked_official_page",
                "local_findability": "portal_link" if ext else "one_click",
                "evidence_text": atext[:200],
                "evidence_url": href,
                "evidence_selector": "a",
                "evidence_document_type": "html",
                "confidence": "medium",
            })
            return candidate

    # 4) Body keyword hit (low confidence, likely ambiguous)
    body_text = soup.get_text(" ", strip=True)
    hit = keyword_hit(body_text, keywords)
    if hit:
        candidate.update({
            "observed": "present",
            "location_type": "ambiguous",
            "local_findability": "unclear",
            "evidence_text": hit,
            "evidence_url": target_url,
            "evidence_selector": "body",
            "evidence_document_type": "html",
            "confidence": "low",
            "notes": "keyword found in page text without structural anchor",
        })

    return candidate


def extract_course_title(soup) -> str:
    if soup.title and soup.title.string:
        return soup.title.string.strip()[:300]
    h1 = soup.find("h1")
    if h1:
        return h1.get_text(" ", strip=True)[:300]
    return ""


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--strun", default="STRUN_001")
    ap.add_argument("--only", default="")
    args = ap.parse_args()

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    STAGING_DIR.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[logging.FileHandler(LOG_DIR / "extract_structural.log", mode="w"),
                  logging.StreamHandler()],
    )

    if not DICT_PATH.exists():
        logging.error("Missing %s. Author the keyword dictionary at Step 3 first.",
                      DICT_PATH.relative_to(REPO_ROOT))
        return 2

    dictionary = load_yaml(DICT_PATH)
    indicators: list[dict] = dictionary.get("indicators", [])
    if not indicators:
        logging.error("No indicators in %s", DICT_PATH)
        return 2

    rows = load_manifest()
    if args.only:
        wanted = {c.strip() for c in args.only.split(",") if c.strip()}
        rows = [r for r in rows if r["course_id"] in wanted]
    if not rows:
        logging.error("No manifest rows to process.")
        return 2

    wide_path = STAGING_DIR / "structural_indicators.staging.csv"
    long_path = STAGING_DIR / "structural_evidence_long.staging.csv"

    wide_fields = list(WIDE_FIELDS)
    for ind in INDICATORS_WIDE_PAIR:
        wide_fields.extend([f"{ind}_present", f"{ind}_location_type"])
    wide_fields.extend(["overall_extraction_confidence", "notes"])

    wide_rows: list[dict[str, str]] = []
    long_rows: list[dict[str, str]] = []
    extracted_at = datetime.now(timezone.utc).isoformat()

    for r in rows:
        cid = r["course_id"]
        artifact = REPO_ROOT / (r["rendered_artifact_path"] if r["render_mode"] == "browser_rendered"
                                and r.get("rendered_capture_status") == "captured"
                                else r["static_html_path"])
        if not artifact.exists():
            logging.error("[%s] artifact missing: %s", cid, artifact)
            continue
        logging.info("[%s] parsing %s", cid, artifact.relative_to(REPO_ROOT))
        soup = soupify(artifact)
        title = extract_course_title(soup)

        wide: dict[str, str] = {f: "" for f in wide_fields}
        wide.update({
            "course_id": cid,
            "university_id": r["university_id"],
            "source_document_id": r["source_document_id"],
            "target_url": r["target_url"],
            "page_role": "course_page",
            "extraction_run_id": args.strun,
            "extracted_at": extracted_at,
            "render_mode": r["render_mode"],
            "course_title_observed": title,
        })

        # course_title indicator (special-cased — present iff title non-empty)
        if title:
            long_rows.append({
                "extraction_run_id": args.strun,
                "course_id": cid,
                "university_id": r["university_id"],
                "source_document_id": r["source_document_id"],
                "indicator_id": "course_title",
                "indicator_label": "Course title",
                "priority": "essential",
                "observed": "present",
                "location_type": "heading_or_summary",
                "local_findability": "direct",
                "evidence_text": title,
                "evidence_url": r["target_url"],
                "evidence_selector": "title|h1",
                "evidence_document_type": "html",
                "extraction_method": "auto",
                "confidence": "high",
                "notes": "",
            })

        confidences: list[str] = []
        for indicator in indicators:
            iid = indicator["indicator_id"]
            if iid == "course_title":
                continue  # special-cased above
            cand = detect_indicator(soup, indicator, r["target_url"])
            confidences.append(cand["confidence"])
            long_rows.append({
                "extraction_run_id": args.strun,
                "course_id": cid,
                "university_id": r["university_id"],
                "source_document_id": r["source_document_id"],
                "indicator_id": iid,
                "indicator_label": indicator.get("label", iid),
                "priority": indicator.get("priority", "important"),
                "observed": cand["observed"],
                "location_type": cand["location_type"],
                "local_findability": cand["local_findability"],
                "evidence_text": cand["evidence_text"],
                "evidence_url": cand["evidence_url"],
                "evidence_selector": cand["evidence_selector"],
                "evidence_document_type": cand["evidence_document_type"],
                "extraction_method": "auto",
                "confidence": cand["confidence"],
                "notes": cand["notes"],
            })
            if iid in INDICATORS_WIDE_PAIR:
                wide[f"{iid}_present"] = (
                    "present" if cand["observed"] == "present" else "not_observed"
                )
                wide[f"{iid}_location_type"] = cand["location_type"]

        worst = "high"
        rank = {"high": 0, "medium": 1, "low": 2, "not_observed": 3, "not_applicable": 4}
        for c in confidences:
            if rank.get(c, 99) > rank.get(worst, 99):
                worst = c
        wide["overall_extraction_confidence"] = worst
        wide_rows.append(wide)

    with wide_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=wide_fields)
        w.writeheader()
        w.writerows(wide_rows)
    with long_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=LONG_FIELDS)
        w.writeheader()
        w.writerows(long_rows)

    logging.info("Wrote %s (%d rows) and %s (%d rows)",
                 wide_path.relative_to(REPO_ROOT), len(wide_rows),
                 long_path.relative_to(REPO_ROOT), len(long_rows))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
