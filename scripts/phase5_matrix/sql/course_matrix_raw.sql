-- course_matrix_raw.sql
-- Phase 5 Step C — Build A (raw + derived) per corso — 41 righe
-- NON include flag interpretivi (Step F) né missingness taxonomy (Step D).
-- Target: tmp/datagrip/university_audit_preview.sqlite
-- QA attesa: 41 righe, sample_course_id unico, nessun blocked_js mancante.

WITH

-- 1. Base: identità corso + ateneo
base AS (
    SELECT
        csm.sample_course_id,
        csm.university_id,
        csm.course_name,
        csm.degree_type,
        csm.course_class,
        csm.disciplinary_cluster,
        csm.course_page_url,
        usm.university_name,
        usm.macro_area,
        usm.institution_type,
        usm.city                    AS university_city,
        usm.university_homepage_url,
        usm.programmes_hub_url
    FROM course_sample_master csm
    JOIN university_sample_master usm ON csm.university_id = usm.university_id
),

-- 2. Pagina canonicale corso (source_document via Lighthouse — stessa scelta di structural_indicators)
canonical_page AS (
    SELECT
        lr.sample_course_id,
        lr.source_document_id,
        lr.crawl_run_id             AS lhci_run_id,
        sd.final_url                AS course_page_final_url
    FROM lighthouse_results lr
    JOIN source_document sd ON lr.source_document_id = sd.source_document_id
    WHERE lr.page_role = 'course_page'
      AND lr.strategy  = 'mobile'
),

-- 3. Journey (una riga per corso — tutti i corsi hanno esattamente un journey_matrix)
journey AS (
    SELECT
        jm.sample_course_id,
        jm.journey_id,
        jm.journey_start_url,
        jm.journey_target_url,
        jm.manual_success           AS journey_success,
        jm.manual_click_depth       AS journey_click_depth,
        jm.manual_time_seconds      AS journey_time_seconds,
        jm.planned_primary_path,
        jm.internal_search_used,
        jm.direct_cta_used,
        jm.js_dependency_level_preaudit,
        jm.target_platform_family,
        jm.notes                    AS journey_notes
    FROM journey_matrix jm
),

-- 4. Journey run ID (primary_orientation + use_for_matrix=1)
journey_run AS (
    SELECT
        journey_id,
        MAX(journey_run_id) AS journey_run_id
    FROM journey_log
    WHERE use_for_matrix = '1'
      AND run_role = 'primary_orientation'
    GROUP BY journey_id
),

-- 5. WAVE per pagina corso
wave_course AS (
    SELECT
        wr.source_document_id,
        wr.target_id,
        wr.crawl_run_id             AS wave_crawl_run_id,
        wr.error_count              AS wave_error_count,
        wr.contrast_count           AS wave_contrast_error_count,
        wr.tool_mode
    FROM wave_results wr
    WHERE wr.page_role = 'course_page'
),

-- 6. WAVE item counts pivotati per pagina corso
wave_items_pivoted AS (
    SELECT
        wi.target_id,
        CAST(
            SUM(CASE WHEN wi.item_id IN ('alt_null','alt_missing')
                     THEN CAST(wi.item_count AS INTEGER) ELSE 0 END)
        AS TEXT) AS missing_alt_count,
        CAST(
            SUM(CASE WHEN wi.item_id = 'link_empty'
                     THEN CAST(wi.item_count AS INTEGER) ELSE 0 END)
        AS TEXT) AS empty_link_count,
        CAST(
            SUM(CASE WHEN wi.item_id = 'label_missing'
                     THEN CAST(wi.item_count AS INTEGER) ELSE 0 END)
        AS TEXT) AS form_label_issue_count
    FROM wave_items_long wi
    WHERE wi.category = 'error'
    GROUP BY wi.target_id
),

-- 7. Lighthouse per pagina corso
lh_course AS (
    SELECT
        lr.sample_course_id,
        lr.performance_score        AS lighthouse_performance,
        lr.accessibility_score      AS lighthouse_accessibility,
        lr.best_practices_score     AS lighthouse_best_practices,
        lr.seo_score                AS lighthouse_seo
    FROM lighthouse_results lr
    WHERE lr.page_role = 'course_page'
      AND lr.strategy  = 'mobile'
),

-- 8. SERP SQ01 (known_institution)
serp_sq01 AS (
    SELECT
        so.course_id,
        so.query_string             AS google_query_exact,
        so.target_rank_organic      AS google_rank_exact,
        so.target_found             AS sq01_found,
        so.target_found_top10       AS sq01_top10
    FROM serp_observations so
    WHERE so.query_template_id = 'SQ01'
),

-- 9. SERP SQ02 (user_like_institutional)
serp_sq02 AS (
    SELECT
        so.course_id,
        so.query_string             AS google_query_generic,
        so.target_rank_organic      AS google_rank_generic,
        so.target_found             AS sq02_found,
        so.target_found_top10       AS sq02_top10
    FROM serp_observations so
    WHERE so.query_template_id = 'SQ02'
),

-- 10. SERP SQ03 (information_seeking)
serp_sq03 AS (
    SELECT
        so.course_id,
        so.target_found             AS sq03_found,
        so.target_found_top10       AS sq03_top10
    FROM serp_observations so
    WHERE so.query_template_id = 'SQ03'
),

-- 11. Best rank organico e crawl_run_id SERP (su tutte le query del corso)
serp_agg AS (
    SELECT
        so.course_id,
        MIN(CASE WHEN so.target_found = 'true'
                 THEN CAST(so.target_rank_organic AS INTEGER) END) AS serp_best_rank_organic,
        MAX(so.crawl_run_id)                                       AS serp_crawl_run_id
    FROM serp_observations so
    GROUP BY so.course_id
),

-- 12. Mediana rank tra query in cui il target è trovato (max 3 valori per corso)
serp_median AS (
    SELECT
        course_id,
        AVG(CAST(target_rank_organic AS FLOAT)) AS serp_median_rank_found
    FROM (
        SELECT
            course_id, target_rank_organic,
            ROW_NUMBER() OVER (PARTITION BY course_id ORDER BY CAST(target_rank_organic AS INTEGER)) AS rn,
            COUNT(*)     OVER (PARTITION BY course_id)                                               AS cnt
        FROM serp_observations
        WHERE target_found = 'true'
    )
    WHERE rn IN ((cnt + 1) / 2, (cnt + 2) / 2)
    GROUP BY course_id
),

-- 13. Third-party above official (SQ01 + SQ02): non-official result con rank < rank target
serp_3p AS (
    SELECT
        srl.course_id,
        MAX(CASE
            WHEN srl.is_official_university_domain = 'false'
             AND so.target_found = 'true'
             AND CAST(srl.organic_rank AS INTEGER) < CAST(so.target_rank_organic AS INTEGER)
            THEN 1 ELSE 0
        END) AS third_party_above_official
    FROM serp_results_long srl
    JOIN serp_observations so ON srl.serp_observation_id = so.serp_observation_id
    WHERE srl.query_template_id IN ('SQ01', 'SQ02')
    GROUP BY srl.course_id
),

-- 14. Structural indicators Phase 4
struct AS (
    SELECT * FROM structural_indicators
),

-- 15. Evidence path: source document HTML per pagina corso nel bundle journey
evidence AS (
    SELECT
        jam.journey_id,
        MIN(jam.artifact_path) AS evidence_path
    FROM journey_artifact_manifest jam
    WHERE jam.artifact_category = 'source_document'
      AND jam.artifact_role = 'course_page'
    GROUP BY jam.journey_id
),

-- 16. Assembly con tutti i campi raw + derived (no flag interpretivi)
assembled AS (
SELECT
    -- ─── §1.1 Identità ────────────────────────────────────────────────────────
    'definitive'                                                        AS phase,
    'sample_v1'                                                         AS audit_round,
    date('now')                                                         AS audit_date,
    NULL                                                                AS crawl_run_id,
    b.university_id,
    b.university_name,
    b.macro_area,
    b.institution_type,
    b.university_city,
    b.university_homepage_url,
    b.programmes_hub_url,
    b.sample_course_id,
    b.course_name,
    b.course_class,
    NULL                                                                AS department,
    b.course_page_url,
    cp.course_page_final_url,
    -- course_platform_type: target_platform_family da journey_matrix (proxy; non in course_sample_master)
    j.target_platform_family                                            AS course_platform_type,
    -- js_heavy_flag: derivato da js_dependency_level_preaudit (campo diretto assente da course_sample_master)
    CASE WHEN j.js_dependency_level_preaudit = 'high' THEN '1' ELSE '0' END AS js_heavy_flag,

    -- ─── §1.2 Journey ────────────────────────────────────────────────────────
    j.journey_start_url,
    j.journey_target_url,
    j.journey_success,
    j.journey_click_depth,
    j.journey_time_seconds,
    -- journey_path_type derivato da campi booleani journey (campo diretto assente)
    CASE
        WHEN j.journey_success = '0'                                          THEN 'failed'
        WHEN j.internal_search_used = '1' AND j.direct_cta_used = '1'        THEN 'mixed'
        WHEN j.internal_search_used = '1'                                     THEN 'onsite_search'
        WHEN j.direct_cta_used = '1'                                          THEN 'cta'
        WHEN j.planned_primary_path LIKE '%programmes_hub%'                   THEN 'programmes_hub'
        ELSE 'menu'
    END                                                                 AS journey_path_type,
    j.journey_notes,

    -- ─── §1.3 Navigability/IA (non in DB — null; Step D assegna taxonomy) ───
    NULL AS breadcrumb_present,
    NULL AS breadcrumb_depth_proxy,
    NULL AS menu_clarity_score,
    NULL AS onsite_search_present,

    -- ─── §1.4 Orientation (non in DB — null) ─────────────────────────────────
    NULL AS orientation_description,
    NULL AS orientation_requirements,
    NULL AS orientation_deadlines,
    NULL AS orientation_fees,
    NULL AS orientation_contacts,
    NULL AS orientation_multilingual,
    NULL AS orientation_study_plan,
    NULL AS orientation_careers,
    NULL AS orientation_score_raw,
    NULL AS orientation_score_norm,

    -- ─── §1.5 Discoverability page-level (non in DB — null) ──────────────────
    NULL AS title_text,
    NULL AS title_quality_score,
    NULL AS meta_description_present,
    NULL AS meta_description_quality_score,
    NULL AS canonical_present,
    NULL AS structured_data_course,
    NULL AS structured_data_breadcrumb,
    NULL AS indexability_status,

    -- ─── §1.6 SERP raw ───────────────────────────────────────────────────────
    sq01.google_query_exact,
    sq01.google_rank_exact,
    sq02.google_query_generic,
    sq02.google_rank_generic,
    CASE WHEN sq01.sq01_found = 'true' OR sq02.sq02_found = 'true'
         THEN '1' ELSE '0' END                                          AS official_result_present,
    CAST(COALESCE(sp3.third_party_above_official, 0) AS TEXT)           AS third_party_above_official,
    NULL                                                                AS ai_search_note,

    -- ─── §1.7 SERP derived ────────────────────────────────────────────────────
    CASE WHEN sq01.sq01_top10 = 'true' THEN '1' ELSE '0' END           AS serp_known_institution_found_top10,
    CASE WHEN sq02.sq02_top10 = 'true' THEN '1' ELSE '0' END           AS serp_user_like_found_top10,
    CASE WHEN sq03.sq03_top10 = 'true' THEN '1' ELSE '0' END           AS serp_info_seeking_found_top10,
    CASE WHEN sq01.sq01_top10 = 'true' OR  sq02.sq02_top10 = 'true'
         THEN '1' ELSE '0' END                                          AS serp_any_core_query_found_top10,
    CASE WHEN sq01.sq01_top10 = 'true' AND sq02.sq02_top10 = 'true'
         THEN '1' ELSE '0' END                                          AS serp_all_core_queries_found_top10,
    CAST(sa.serp_best_rank_organic AS TEXT)                             AS serp_best_rank_organic,
    CAST(ROUND(sm.serp_median_rank_found, 2) AS TEXT)                   AS serp_median_rank_found,
    CASE WHEN sq01.sq01_top10 != 'true' AND sq02.sq02_top10 != 'true'
         THEN '1' ELSE '0' END                                          AS serp_missing_all_core_queries,
    sa.serp_crawl_run_id,

    -- ─── §1.8 WAVE / Accessibilità ────────────────────────────────────────────
    NULL AS lang_declared,
    NULL AS skip_link_present,
    NULL AS accessibility_statement_present,
    NULL AS h1_present,
    NULL AS heading_structure_score,
    wi.missing_alt_count,
    wi.empty_link_count,
    wi.form_label_issue_count,
    wc.wave_error_count,
    wc.wave_contrast_error_count,
    CASE WHEN wc.tool_mode = 'api' THEN 'api_primary' ELSE 'browser_fallback' END AS wave_collection_mode,
    CASE WHEN wc.tool_mode = 'api' THEN 'standard'    ELSE 'reduced'          END AS wave_metric_comparability,
    wc.wave_crawl_run_id,

    -- ─── §1.9 Lighthouse ─────────────────────────────────────────────────────
    lc.lighthouse_performance,
    lc.lighthouse_accessibility,
    lc.lighthouse_best_practices,
    lc.lighthouse_seo,
    'mobile'                                                            AS lighthouse_strategy,
    cp.lhci_run_id,

    -- ─── §1.10 Structural raw (Phase 4) ──────────────────────────────────────
    -- course_title: observed come testo; _present derivato; _location_type/_local_findability assenti da Phase 4
    CASE WHEN s.course_title_observed IS NOT NULL AND s.course_title_observed != ''
         THEN 'present' ELSE 'not_observed' END                         AS course_title_present,
    NULL                                                                AS course_title_location_type,
    NULL                                                                AS course_title_local_findability,
    s.degree_level_present,
    s.degree_level_location_type,
    NULL                                                                AS degree_level_local_findability,
    s.degree_class_present,
    s.degree_class_location_type,
    NULL                                                                AS degree_class_local_findability,
    s.cfu_present,
    s.cfu_location_type,
    NULL                                                                AS cfu_local_findability,
    s.duration_present,
    s.duration_location_type,
    NULL                                                                AS duration_local_findability,
    s.academic_year_present,
    s.academic_year_location_type,
    NULL                                                                AS academic_year_local_findability,
    s.location_present,
    s.location_location_type,
    NULL                                                                AS location_local_findability,
    s.language_present,
    s.language_location_type,
    NULL                                                                AS language_local_findability,
    s.study_plan_present,
    s.study_plan_location_type,
    NULL                                                                AS study_plan_local_findability,
    s.admission_requirements_present,
    s.admission_requirements_location_type,
    NULL                                                                AS admission_requirements_local_findability,
    s.admission_procedure_present,
    s.admission_procedure_location_type,
    NULL                                                                AS admission_procedure_local_findability,
    s.deadlines_present,
    s.deadlines_location_type,
    NULL                                                                AS deadlines_local_findability,
    s.fees_or_costs_present,
    s.fees_or_costs_location_type,
    NULL                                                                AS fees_or_costs_local_findability,
    s.career_outcomes_present,
    s.career_outcomes_location_type,
    NULL                                                                AS career_outcomes_local_findability,
    s.contacts_present,
    s.contacts_location_type,
    NULL                                                                AS contacts_local_findability,
    s.official_regulation_present,
    s.official_regulation_location_type,
    NULL                                                                AS official_regulation_local_findability,
    s.quality_or_satisfaction_present,
    s.quality_or_satisfaction_location_type,
    NULL                                                                AS quality_or_satisfaction_local_findability,
    s.accessibility_services_present,
    s.accessibility_services_location_type,
    NULL                                                                AS accessibility_services_local_findability,
    s.overall_extraction_confidence,

    -- ─── §1.11 Structural derived ─────────────────────────────────────────────
    -- Essential 7: course_title, degree_level, study_plan, admission_requirements,
    --              admission_procedure, deadlines, contacts
    CASE WHEN
        (CASE WHEN s.course_title_observed IS NOT NULL AND s.course_title_observed != '' THEN 1 ELSE 0 END) = 1
        AND s.degree_level_present          = 'present'
        AND s.study_plan_present            = 'present'
        AND s.admission_requirements_present= 'present'
        AND s.admission_procedure_present   = 'present'
        AND s.deadlines_present             = 'present'
        AND s.contacts_present              = 'present'
    THEN '1' ELSE '0' END                                               AS structural_essential_info_complete,

    CAST(ROUND((
        (CASE WHEN s.course_title_observed IS NOT NULL AND s.course_title_observed != '' THEN 1 ELSE 0 END) +
        (CASE WHEN s.degree_level_present           = 'present' THEN 1 ELSE 0 END) +
        (CASE WHEN s.study_plan_present             = 'present' THEN 1 ELSE 0 END) +
        (CASE WHEN s.admission_requirements_present = 'present' THEN 1 ELSE 0 END) +
        (CASE WHEN s.admission_procedure_present    = 'present' THEN 1 ELSE 0 END) +
        (CASE WHEN s.deadlines_present              = 'present' THEN 1 ELSE 0 END) +
        (CASE WHEN s.contacts_present               = 'present' THEN 1 ELSE 0 END)
    ) / 7.0, 4) AS TEXT)                                                AS structural_essential_completeness_rate,

    CASE WHEN s.study_plan_present = 'present' THEN '1' ELSE '0' END   AS structural_study_plan_present,

    -- study_plan_direct: proxy da location_type (local_findability assente da Phase 4)
    CASE
        WHEN s.study_plan_present != 'present' THEN '0'
        WHEN s.study_plan_location_type IN ('inline_html','heading_or_summary','accordion','tab','table') THEN '1'
        WHEN s.study_plan_location_type IN ('linked_pdf','external_official_portal','download','linked_official_page') THEN '0'
        ELSE NULL
    END                                                                 AS structural_study_plan_direct,

    CASE
        WHEN s.study_plan_location_type = 'linked_pdf'
         AND s.study_plan_location_type NOT IN ('inline_html','heading_or_summary','accordion','tab','table')
        THEN '1' ELSE '0'
    END                                                                 AS structural_study_plan_pdf_only,

    CASE WHEN s.admission_requirements_present = 'present'
          OR  s.admission_procedure_present    = 'present'
         THEN '1' ELSE '0' END                                          AS structural_admission_info_present,

    CASE WHEN s.contacts_present = 'present' THEN '1' ELSE '0' END     AS structural_contacts_present,

    -- fragmented: ≥ 4 dei 6 Essential con location_type (course_title escluso: no location_type in Phase 4)
    CASE WHEN (
        (CASE WHEN s.degree_level_location_type           IN ('linked_pdf','external_official_portal') THEN 1 ELSE 0 END) +
        (CASE WHEN s.study_plan_location_type             IN ('linked_pdf','external_official_portal') THEN 1 ELSE 0 END) +
        (CASE WHEN s.admission_requirements_location_type IN ('linked_pdf','external_official_portal') THEN 1 ELSE 0 END) +
        (CASE WHEN s.admission_procedure_location_type    IN ('linked_pdf','external_official_portal') THEN 1 ELSE 0 END) +
        (CASE WHEN s.deadlines_location_type              IN ('linked_pdf','external_official_portal') THEN 1 ELSE 0 END) +
        (CASE WHEN s.contacts_location_type               IN ('linked_pdf','external_official_portal') THEN 1 ELSE 0 END)
    ) >= 4 THEN '1' ELSE '0' END                                        AS structural_fragmented_information,

    CASE WHEN s.study_plan_location_type             = 'external_official_portal'
          OR  s.admission_requirements_location_type = 'external_official_portal'
         THEN '1' ELSE '0' END                                          AS structural_external_portal_dependency,

    -- ─── §1.12 Flag interpretivi — NOT in Step C (Step F, dopo thresholds.yaml approved) ──
    -- journey_high_friction, journey_blocked, weak_external_findability,
    -- accessibility_risk, technical_risk, information_fragmentation,
    -- critical_student_pathway, multi_phase_critical_case

    -- ─── §1.13 Provenance ────────────────────────────────────────────────────
    jr.journey_run_id,
    -- lhci_run_id già in §1.9
    wc.wave_crawl_run_id                                                AS wave_crawl_run_id_prov,
    sa.serp_crawl_run_id                                                AS serp_crawl_run_id_prov,
    s.extraction_run_id                                                 AS structural_extraction_run_id,
    cp.source_document_id,
    cp.course_page_final_url                                            AS canonical_course_url,
    ev.evidence_path,

    -- ─── §1.14 Controllo ─────────────────────────────────────────────────────
    NULL    AS overall_notes,
    'draft' AS review_status,
    NULL    AS provenance_notes

FROM base b
LEFT JOIN canonical_page     cp  ON b.sample_course_id = cp.sample_course_id
LEFT JOIN journey             j   ON b.sample_course_id = j.sample_course_id
LEFT JOIN journey_run         jr  ON j.journey_id       = jr.journey_id
LEFT JOIN wave_course         wc  ON cp.source_document_id = wc.source_document_id
LEFT JOIN wave_items_pivoted  wi  ON wc.target_id          = wi.target_id
LEFT JOIN lh_course           lc  ON b.sample_course_id = lc.sample_course_id
LEFT JOIN serp_sq01           sq01 ON b.sample_course_id = sq01.course_id
LEFT JOIN serp_sq02           sq02 ON b.sample_course_id = sq02.course_id
LEFT JOIN serp_sq03           sq03 ON b.sample_course_id = sq03.course_id
LEFT JOIN serp_agg            sa  ON b.sample_course_id = sa.course_id
LEFT JOIN serp_median         sm  ON b.sample_course_id = sm.course_id
LEFT JOIN serp_3p             sp3 ON b.sample_course_id = sp3.course_id
LEFT JOIN struct               s   ON b.sample_course_id = s.course_id
LEFT JOIN evidence            ev  ON j.journey_id       = ev.journey_id
)

SELECT * FROM assembled
ORDER BY sample_course_id;
