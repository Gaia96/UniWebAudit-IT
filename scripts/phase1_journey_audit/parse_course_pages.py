#!/usr/bin/env python3
"""
parse_course_pages.py — Phase 1 supplementary parser

Extracts page-level indicators from saved HTML files for all 41 course pages.

Outputs:
  data/collection/parsed_course_indicators.csv  — auto fields (no human review needed)
  data/collection/manual_review_orientation.csv — pre-filled sheet for human review

After human review of manual_review_orientation.csv, run:
  python3 phase1_journey_audit/merge_indicators.py
to merge both files and feed Step C SQL.

Usage:
  python3 phase1_journey_audit/parse_course_pages.py
"""

import csv
import json
import re
from pathlib import Path

try:
    from bs4 import BeautifulSoup, Tag
except ImportError:
    raise SystemExit("ERROR: pip install beautifulsoup4 lxml")

ROOT = Path(__file__).resolve().parents[1]
SD_CSV = ROOT / "data" / "collection" / "source_document.csv"
COURSE_CSV = ROOT / "phase5_matrix" / "_tmp" / "course_raw.csv"
OUT_AUTO = ROOT / "data" / "collection" / "parsed_course_indicators.csv"
OUT_MANUAL = ROOT / "data" / "collection" / "manual_review_orientation.csv"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _soup(path: Path) -> BeautifulSoup:
    # lxml is faster and more lenient than html.parser on malformed university HTML
    with path.open(encoding="utf-8", errors="replace") as fh:
        return BeautifulSoup(fh, "lxml")


def _text(tag) -> str:
    return tag.get_text(strip=True) if tag else ""


def _binary(condition: bool) -> str:
    return "1" if condition else "0"


# ---------------------------------------------------------------------------
# Auto-extractable fields
# ---------------------------------------------------------------------------

def parse_lang(soup: BeautifulSoup) -> str:
    html = soup.find("html")
    if html and html.get("lang", "").strip():
        return "1"
    return "0"


def parse_title(soup: BeautifulSoup) -> tuple[str, str]:
    """Returns (title_text, title_quality_score_heuristic)."""
    tag = soup.find("title")
    text = _text(tag)
    if not text:
        return ("", "0")
    # Base score 1; each satisfied criterion adds 1 point (max 4)
    score = 1
    text_lower = text.lower()
    # +1 if the title mentions the institution name — helps SEO and user orientation
    if any(w in text_lower for w in ["università", "universita", "unibo", "unipd", "politecnico",
                                      "università", "sapienza", "bologna", "padova", "firenze",
                                      "milano", "torino", "napoli", "roma"]):
        score += 1
    # +1 if the degree type is explicit in the title
    if any(w in text_lower for w in ["laurea", "magistrale", "triennale", "ciclo unico", "lmcu"]):
        score += 1
    # +1 if the title is long enough to be descriptive (< 20 chars is usually just a site name)
    if len(text) >= 20:
        score += 1
    score = min(score, 4)
    return (text, str(score))


def parse_meta_description(soup: BeautifulSoup) -> tuple[str, str]:
    """Returns (meta_description_present, meta_description_quality_score_heuristic)."""
    tag = soup.find("meta", attrs={"name": re.compile(r"^description$", re.I)})
    if not tag:
        return ("0", "0")
    content = tag.get("content", "").strip()
    if not content:
        return ("0", "0")
    length = len(content)
    # Google typically truncates after ~160 chars; < 50 is too short to be useful
    if length < 50:
        quality = "1"
    elif length <= 160:
        quality = "3"  # ideal range
    else:
        quality = "2"  # present but likely truncated in SERPs
    return ("1", quality)


def parse_canonical(soup: BeautifulSoup) -> str:
    tag = soup.find("link", rel=lambda r: r and "canonical" in r)
    return _binary(tag is not None and bool(tag.get("href", "").strip()))


def parse_structured_data(soup: BeautifulSoup) -> tuple[str, str]:
    """Returns (structured_data_course, structured_data_breadcrumb)."""
    has_course = False
    has_breadcrumb = False
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "")
            items = data if isinstance(data, list) else [data]
            for item in items:
                typ = item.get("@type", "")
                if isinstance(typ, list):
                    typ_set = {t.lower() for t in typ}
                else:
                    typ_set = {typ.lower()}
                if "course" in typ_set:
                    has_course = True
                if "breadcrumblist" in typ_set:
                    has_breadcrumb = True
        except (json.JSONDecodeError, AttributeError):
            continue
    return (_binary(has_course), _binary(has_breadcrumb))


def parse_indexability(soup: BeautifulSoup) -> str:
    robots = soup.find("meta", attrs={"name": re.compile(r"^robots$", re.I)})
    if robots:
        content = robots.get("content", "").lower()
        if "noindex" in content:
            return "non_indexable"
        if content.strip():
            return "indexable"
        return "unclear"
    return "indexable"


def parse_skip_link(soup: BeautifulSoup) -> str:
    # Skip links must be among the very first anchors to be useful for keyboard users
    for a in soup.find_all("a", href=True)[:10]:
        href = a.get("href", "")
        if href.startswith("#") and len(href) > 1:
            text = _text(a).lower()
            if any(w in text for w in ["salta", "skip", "contenuto", "content", "main", "menu"]):
                return "1"
            # also accept if href target is #main, #content, #maincontent
            if any(anchor in href.lower() for anchor in ["main", "content", "skip", "salta"]):
                return "1"
    return "0"


def parse_h1(soup: BeautifulSoup) -> str:
    h1 = soup.find("h1")
    return _binary(bool(h1 and _text(h1)))


def parse_heading_structure(soup: BeautifulSoup) -> str:
    """
    0 = no H1 or no headings at all
    1 = H1 present but hierarchy broken (skips levels, multiple H1)
    2 = H1 + H2 present, minor issues
    3 = H1 → H2 → H3 proper nesting, no skips
    """
    # Only non-empty heading tags count
    headings = [(int(h.name[1]), _text(h)) for h in soup.find_all(re.compile(r"^h[1-6]$"))
                if _text(h)]
    if not headings:
        return "0"
    levels = [h[0] for h in headings]
    h1_count = levels.count(1)
    if h1_count == 0:
        return "0"
    # A level skip (e.g. H1 → H3) violates WCAG heading order
    prev = 1
    skipped = False
    for lv in levels:
        if lv > prev + 1:
            skipped = True
            break
        if lv >= 1:
            prev = lv
    if h1_count > 1 or skipped:
        if max(levels) >= 2:
            return "1"
        return "0"
    if max(levels) >= 3:
        return "3"
    if max(levels) >= 2:
        return "2"
    return "1"


def parse_breadcrumb(soup: BeautifulSoup) -> str:
    # nav aria-label breadcrumb
    for nav in soup.find_all("nav"):
        label = nav.get("aria-label", "").lower()
        if "breadcrumb" in label or "percorso" in label:
            return "1"
    # ol/ul with role or class breadcrumb
    for el in soup.find_all(["ol", "ul"]):
        cls = " ".join(el.get("class", [])).lower()
        role = el.get("role", "").lower()
        if "breadcrumb" in cls or "breadcrumb" in role:
            return "1"
    # structured data breadcrumb already checked separately; use here too
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "")
            items = data if isinstance(data, list) else [data]
            for item in items:
                typ = item.get("@type", "")
                if isinstance(typ, str) and "breadcrumblist" in typ.lower():
                    return "1"
        except (json.JSONDecodeError, AttributeError):
            continue
    return "0"


def parse_accessibility_statement(soup: BeautifulSoup) -> str:
    patterns = re.compile(
        r"accessibilit[aà]|dichiarazione.*accessibilit|agid|accessibilit.*sito",
        re.I
    )
    for a in soup.find_all("a", href=True):
        text = _text(a)
        href = a.get("href", "")
        if patterns.search(text) or patterns.search(href):
            return "1"
    return "0"


def parse_missing_alt(soup: BeautifulSoup) -> str:
    count = 0
    for img in soup.find_all("img"):
        alt = img.get("alt")
        if alt is None:
            # alt="" is valid for decorative images; only the complete absence of the attribute is a WCAG error
            count += 1
    return str(count)


def parse_empty_links(soup: BeautifulSoup) -> str:
    count = 0
    for a in soup.find_all("a", href=True):
        text = _text(a)
        aria = a.get("aria-label", "").strip()
        title = a.get("title", "").strip()
        img_alt = ""
        img = a.find("img")
        if img:
            img_alt = img.get("alt", "").strip()
        if not text and not aria and not title and not img_alt:
            count += 1
    return str(count)


def parse_form_label_issues(soup: BeautifulSoup) -> str:
    # Exclude non-interactive input types that don't need a label
    inputs = soup.find_all("input", type=lambda t: t not in ("hidden", "submit", "button", "reset", "image"))
    if not inputs:
        return "not_applicable"
    issues = 0
    for inp in inputs:
        inp_id = inp.get("id", "")
        aria_label = inp.get("aria-label", "").strip()
        aria_labeled_by = inp.get("aria-labelledby", "").strip()
        placeholder = inp.get("placeholder", "").strip()  # noqa: F841 — kept for readability
        has_label = False
        if inp_id:
            if soup.find("label", attrs={"for": inp_id}):
                has_label = True
        if aria_label or aria_labeled_by:
            has_label = True
        # placeholder is NOT a substitute for a label per WCAG 2.1 SC 1.3.1
        if not has_label:
            issues += 1
    return str(issues)


# ---------------------------------------------------------------------------
# Orientation keyword pre-detection (Italian)
# ---------------------------------------------------------------------------

# Italian keyword sets used to pre-detect whether each orientation topic is mentioned on the page.
# Results are shown to the reviewer as "1_keyword_hit" / "0_no_hit" — they override if wrong.
ORIENTATION_KEYWORDS = {
    "orientation_description": [
        "obiettivi", "percorso formativo", "il corso", "il laureato", "la laurea",
        "prepara", "forma ", "competenze", "profilo", "sbocchi", "caratteristiche"
    ],
    "orientation_requirements": [
        "requisiti", "prerequisiti", "ammissione", "accesso", "iscrizione", "iscriversi",
        "ofa", "conoscenze richieste", "test", "selezione"
    ],
    "orientation_deadlines": [
        "scadenz", "deadline", "entro il", "entro il ", "dal ", " al ", "immatricolazione",
        "iscrizioni aperte", "chiusura", "termine"
    ],
    "orientation_fees": [
        "tasse", "contributi", "retta", "costo", "tariffe", "pagamento", "rata",
        "esonero", "borsa di studio", "importo", "diritto allo studio"
    ],
    "orientation_contacts": [
        "contatt", "email", "tel", "telefon", "orari di ricevimento", "segreteria",
        "referente", "tutor", "presidenza", "commissione"
    ],
    "orientation_multilingual": [
        "english", "in english", "taught in", "lingua inglese", "bilingual",
        "international", "erasmus"
    ],
    "orientation_study_plan": [
        "piano di studi", "piano degli studi", "offerta didattica", "insegnamenti",
        "esami", "curricula", "manifesto degli studi", "programma"
    ],
    "orientation_careers": [
        "sbocchi", "professionali", "occupazione", "lavoro", "professione",
        "mercato del lavoro", "occupabilità", "career", "sbocchi occupazionali"
    ],
}


def detect_orientation(soup: BeautifulSoup) -> dict[str, str]:
    body_text = soup.get_text(" ", strip=True).lower()
    result = {}
    for field, keywords in ORIENTATION_KEYWORDS.items():
        found = any(kw in body_text for kw in keywords)
        # Prefixed strings let the reviewer see both the automated signal and the final decision side-by-side
        result[field] = "1_keyword_hit" if found else "0_no_hit"
    return result


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def load_source_docs() -> dict[str, str]:
    """Returns {source_document_id: storage_path}."""
    with SD_CSV.open() as fh:
        return {r["source_document_id"]: r["storage_path"]
                for r in csv.DictReader(fh)}


def load_course_rows() -> list[dict]:
    with COURSE_CSV.open() as fh:
        return list(csv.DictReader(fh))


AUTO_FIELDS = [
    "sample_course_id", "source_document_id", "storage_path",
    "lang_declared", "title_text", "title_quality_score_heuristic",
    "meta_description_present", "meta_description_quality_score_heuristic",
    "canonical_present", "structured_data_course", "structured_data_breadcrumb",
    "indexability_status", "skip_link_present", "h1_present",
    "heading_structure_score_heuristic", "breadcrumb_present",
    "accessibility_statement_present",
    "missing_alt_count", "empty_link_count", "form_label_issue_count",
    "parse_warnings",
]

MANUAL_FIELDS = [
    "sample_course_id", "course_name", "university_name", "storage_path",
    # heuristic pre-fills (user validates)
    "title_quality_score_heuristic", "meta_description_quality_score_heuristic",
    "heading_structure_score_heuristic",
    # orientation keyword hits (user reviews and sets final binary)
    "orientation_description_keyword", "orientation_description_FINAL",
    "orientation_requirements_keyword", "orientation_requirements_FINAL",
    "orientation_deadlines_keyword", "orientation_deadlines_FINAL",
    "orientation_fees_keyword", "orientation_fees_FINAL",
    "orientation_contacts_keyword", "orientation_contacts_FINAL",
    "orientation_multilingual_keyword", "orientation_multilingual_FINAL",
    "orientation_study_plan_keyword", "orientation_study_plan_FINAL",
    "orientation_careers_keyword", "orientation_careers_FINAL",
    # manual-only
    "onsite_search_present",
    "menu_clarity_score",
    "reviewer_notes",
]


def main() -> None:
    sd_map = load_source_docs()
    courses = load_course_rows()

    auto_rows: list[dict] = []
    manual_rows: list[dict] = []

    for course in courses:
        cid = course["sample_course_id"]
        sdid = course["source_document_id"]
        sp = sd_map.get(sdid, "")
        html_path = ROOT / sp if sp else None

        warnings = []
        auto: dict[str, str] = {
            "sample_course_id": cid,
            "source_document_id": sdid,
            "storage_path": sp,
        }

        if not html_path or not html_path.exists():
            warnings.append("HTML_NOT_FOUND")
            for f in AUTO_FIELDS[3:-1]:
                auto[f] = "not_collected"
            auto["parse_warnings"] = "|".join(warnings)
            auto_rows.append(auto)
            manual_rows.append(_empty_manual(course, sp))
            continue

        try:
            soup = _soup(html_path)
        except Exception as e:
            warnings.append(f"PARSE_ERROR:{e}")
            for f in AUTO_FIELDS[3:-1]:
                auto[f] = "not_collected"
            auto["parse_warnings"] = "|".join(warnings)
            auto_rows.append(auto)
            manual_rows.append(_empty_manual(course, sp))
            continue

        title_text, title_q = parse_title(soup)
        meta_pres, meta_q = parse_meta_description(soup)
        sd_course, sd_breadcrumb = parse_structured_data(soup)

        auto["lang_declared"] = parse_lang(soup)
        auto["title_text"] = title_text
        auto["title_quality_score_heuristic"] = title_q
        auto["meta_description_present"] = meta_pres
        auto["meta_description_quality_score_heuristic"] = meta_q
        auto["canonical_present"] = parse_canonical(soup)
        auto["structured_data_course"] = sd_course
        auto["structured_data_breadcrumb"] = sd_breadcrumb
        auto["indexability_status"] = parse_indexability(soup)
        auto["skip_link_present"] = parse_skip_link(soup)
        auto["h1_present"] = parse_h1(soup)
        auto["heading_structure_score_heuristic"] = parse_heading_structure(soup)
        auto["breadcrumb_present"] = parse_breadcrumb(soup)
        auto["accessibility_statement_present"] = parse_accessibility_statement(soup)
        auto["missing_alt_count"] = parse_missing_alt(soup)
        auto["empty_link_count"] = parse_empty_links(soup)
        auto["form_label_issue_count"] = parse_form_label_issues(soup)
        auto["parse_warnings"] = ""

        auto_rows.append(auto)

        # Manual sheet
        orientation = detect_orientation(soup)
        manual: dict[str, str] = {
            "sample_course_id": cid,
            "course_name": course.get("course_name", ""),
            "university_name": course.get("university_name", ""),
            "storage_path": sp,
            "title_quality_score_heuristic": title_q,
            "meta_description_quality_score_heuristic": meta_q,
            "heading_structure_score_heuristic": auto["heading_structure_score_heuristic"],
        }
        for field, kw_val in orientation.items():
            manual[f"{field}_keyword"] = kw_val
            # pre-fill FINAL from keyword hit (1_keyword_hit → 1, 0_no_hit → 0)
            manual[f"{field}_FINAL"] = "1" if kw_val.startswith("1") else "0"

        manual["onsite_search_present"] = ""
        manual["menu_clarity_score"] = ""
        manual["reviewer_notes"] = ""
        manual_rows.append(manual)

        print(f"  {cid} ✓  lang={auto['lang_declared']} h1={auto['h1_present']} "
              f"meta={meta_pres} canonical={auto['canonical_present']} "
              f"sd_course={sd_course} breadcrumb={auto['breadcrumb_present']}")

    # Write
    OUT_AUTO.parent.mkdir(parents=True, exist_ok=True)

    with OUT_AUTO.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=AUTO_FIELDS, extrasaction="ignore")
        w.writeheader()
        w.writerows(auto_rows)

    with OUT_MANUAL.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=MANUAL_FIELDS, extrasaction="ignore")
        w.writeheader()
        w.writerows(manual_rows)

    print(f"\nWritten: {OUT_AUTO}")
    print(f"Written: {OUT_MANUAL}")
    print(f"\nNext: fill in {OUT_MANUAL.name}")
    print("  - Review *_FINAL columns (from keyword detection)")
    print("  - Fill onsite_search_present (0/1 per course)")
    print("  - Fill menu_clarity_score (0-3 per course)")
    print("  - Adjust *_heuristic scores where heuristic is wrong")
    print("Then: python3 phase1_journey_audit/merge_indicators.py")


def _empty_manual(course: dict, sp: str) -> dict:
    m: dict[str, str] = {
        "sample_course_id": course["sample_course_id"],
        "course_name": course.get("course_name", ""),
        "university_name": course.get("university_name", ""),
        "storage_path": sp,
        "title_quality_score_heuristic": "",
        "meta_description_quality_score_heuristic": "",
        "heading_structure_score_heuristic": "",
    }
    for field in ORIENTATION_KEYWORDS:
        m[f"{field}_keyword"] = ""
        m[f"{field}_FINAL"] = ""
    m["onsite_search_present"] = ""
    m["menu_clarity_score"] = ""
    m["reviewer_notes"] = "HTML_NOT_FOUND"
    return m


if __name__ == "__main__":
    main()
