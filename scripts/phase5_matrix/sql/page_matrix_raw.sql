-- page_matrix_raw.sql
-- Phase 5 Step C — Build A (raw) per pagina — 61 righe (20 homepage + 41 course_page)
-- Chiave: (source_document_id, page_role)
-- Target: tmp/datagrip/university_audit_preview.sqlite
-- QA attesa: 61 righe, coppia (source_document_id, page_role) unica.

WITH

-- 1. Tutte le 61 pagine auditate via Lighthouse (mobile)
lh_all AS (
    SELECT
        lr.source_document_id,
        lr.university_id,
        lr.sample_course_id,
        lr.page_role,
        lr.tested_url,
        lr.final_url,
        lr.crawl_run_id                 AS lhci_run_id,
        lr.performance_score            AS lighthouse_performance,
        lr.accessibility_score          AS lighthouse_accessibility,
        lr.best_practices_score         AS lighthouse_best_practices,
        lr.seo_score                    AS lighthouse_seo,
        lr.first_contentful_paint_ms,
        lr.largest_contentful_paint_ms,
        lr.total_blocking_time_ms,
        lr.cumulative_layout_shift,
        lr.speed_index_ms,
        lr.strategy                     AS lighthouse_strategy
    FROM lighthouse_results lr
    WHERE lr.strategy = 'mobile'
),

-- 2. WAVE per tutte le 61 pagine
wave_all AS (
    SELECT
        wr.source_document_id,
        wr.crawl_run_id                 AS wave_crawl_run_id,
        wr.error_count                  AS wave_error_count,
        wr.contrast_count               AS wave_contrast_error_count,
        wr.alert_count                  AS wave_alert_count,
        wr.feature_count                AS wave_feature_count,
        wr.structure_count              AS wave_structure_count,
        wr.aria_count                   AS wave_aria_count,
        wr.allitemcount                 AS wave_allitemcount,
        wr.aimscore                     AS wave_aimscore,
        wr.tool_mode
    FROM wave_results wr
),

-- 3. Assembly page matrix
assembled AS (
SELECT
    -- ─── §3.1 Identità pagina ──────────────────────────────────────────────
    -- page_audit_id costruito come PA_HOME_UNIxx o PA_COURSE_Cxxx
    CASE
        WHEN lh.page_role = 'university_homepage'
            THEN 'PA_HOME_'  || lh.university_id
        WHEN lh.page_role = 'course_page'
            THEN 'PA_COURSE_' || lh.sample_course_id
        ELSE 'PA_' || lh.source_document_id
    END                                                                 AS page_audit_id,
    lh.university_id,
    lh.sample_course_id,
    lh.page_role,
    lh.tested_url,
    lh.final_url,
    lh.source_document_id,

    -- ─── §3.2 Lighthouse (mobile) ─────────────────────────────────────────
    lh.lighthouse_performance,
    lh.lighthouse_accessibility,
    lh.lighthouse_best_practices,
    lh.lighthouse_seo,
    lh.first_contentful_paint_ms,
    lh.largest_contentful_paint_ms,
    lh.total_blocking_time_ms,
    lh.cumulative_layout_shift,
    lh.speed_index_ms,
    lh.lighthouse_strategy,
    lh.lhci_run_id,

    -- ─── §3.3 WAVE ────────────────────────────────────────────────────────
    wa.wave_error_count,
    wa.wave_contrast_error_count,
    wa.wave_alert_count,
    wa.wave_feature_count,
    wa.wave_structure_count,
    wa.wave_aria_count,
    wa.wave_allitemcount,
    wa.wave_aimscore,
    CASE WHEN wa.tool_mode = 'api' THEN 'api_primary' ELSE 'browser_fallback' END AS wave_collection_mode,
    CASE WHEN wa.tool_mode = 'api' THEN 'standard'    ELSE 'reduced'          END AS wave_metric_comparability,
    wa.wave_crawl_run_id,

    -- ─── §3.4 Parsing SEO/A11y page-level (non in DB — null) ──────────────
    NULL AS title_text,
    NULL AS title_quality_score,
    NULL AS meta_description_present,
    NULL AS canonical_present,
    NULL AS lang_declared,
    NULL AS skip_link_present,
    NULL AS h1_present,
    NULL AS heading_structure_score,
    NULL AS accessibility_statement_present,

    -- ─── §3.5 Controllo ───────────────────────────────────────────────────
    'sample_v1'     AS audit_round,
    date('now')     AS audit_date,
    NULL            AS crawl_run_id,
    'draft'         AS review_status,
    NULL            AS notes

FROM lh_all lh
LEFT JOIN wave_all wa ON lh.source_document_id = wa.source_document_id
)

SELECT * FROM assembled
ORDER BY
    CASE page_role WHEN 'university_homepage' THEN 0 ELSE 1 END,
    university_id,
    sample_course_id;
