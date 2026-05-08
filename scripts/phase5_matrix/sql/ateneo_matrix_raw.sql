-- ateneo_matrix_raw.sql
-- Phase 5 Step C — Build A (raw + derived) per ateneo — 20 righe
-- Aggregati da audit_matrix (corso) + pagine homepage da LH/WAVE.
-- Dipende da course_matrix_raw.sql per i campi derivati corso-livello.
-- Target: tmp/datagrip/university_audit_preview.sqlite
-- QA attesa: 20 righe, university_id unico, denominatori espliciti.

WITH

-- ─── Campi derivati corso-livello (ricalcolati inline) ──────────────────────

-- base corso + ateneo
course_base AS (
    SELECT
        csm.sample_course_id,
        csm.university_id,
        jm.manual_success                                                   AS journey_success,
        CAST(jm.manual_click_depth AS FLOAT)                                AS journey_click_depth,
        CAST(jm.manual_time_seconds AS FLOAT)                               AS journey_time_seconds,
        CASE WHEN jm.manual_success = '0' THEN 1 ELSE 0 END                 AS is_blocked,
        -- wave_collection_mode
        CASE WHEN wr.tool_mode = 'api' THEN 'api_primary' ELSE 'browser_fallback' END AS wave_collection_mode,
        CAST(wr.error_count AS FLOAT)                                       AS wave_error_count,
        CAST(wr.contrast_count AS FLOAT)                                    AS wave_contrast_error_count,
        CAST(lr.performance_score AS FLOAT)                                 AS lh_performance,
        CAST(lr.accessibility_score AS FLOAT)                               AS lh_accessibility,
        -- SERP top10 (core queries)
        CASE WHEN sq01.target_found_top10 = 'true' THEN 1.0 ELSE 0.0 END   AS sq01_top10,
        CASE WHEN sq02.target_found_top10 = 'true' THEN 1.0 ELSE 0.0 END   AS sq02_top10,
        CASE WHEN sq03.target_found_top10 = 'true' THEN 1.0 ELSE 0.0 END   AS sq03_top10,
        CASE WHEN sq01.target_found = 'true' OR sq02.target_found = 'true' THEN 1.0 ELSE 0.0 END AS official_result_present,
        CASE WHEN sp3.tp_above = 1 THEN 1.0 ELSE 0.0 END                   AS third_party_above,
        CAST(
            MIN(CASE WHEN sq01.target_found='true' THEN CAST(sq01.target_rank_organic AS INTEGER) END)
            OVER (PARTITION BY csm.university_id) AS TEXT)                  AS _unused,
        -- structural essential completeness rate
        CAST(ROUND((
            (CASE WHEN si.course_title_observed IS NOT NULL AND si.course_title_observed != '' THEN 1 ELSE 0 END) +
            (CASE WHEN si.degree_level_present           = 'present' THEN 1 ELSE 0 END) +
            (CASE WHEN si.study_plan_present             = 'present' THEN 1 ELSE 0 END) +
            (CASE WHEN si.admission_requirements_present = 'present' THEN 1 ELSE 0 END) +
            (CASE WHEN si.admission_procedure_present    = 'present' THEN 1 ELSE 0 END) +
            (CASE WHEN si.deadlines_present              = 'present' THEN 1 ELSE 0 END) +
            (CASE WHEN si.contacts_present               = 'present' THEN 1 ELSE 0 END)
        ) / 7.0, 4) AS FLOAT)                                               AS struct_essential_rate,
        -- structural flags
        CASE WHEN si.study_plan_location_type = 'linked_pdf'
              AND si.study_plan_location_type NOT IN ('inline_html','heading_or_summary','accordion','tab','table')
             THEN 1.0 ELSE 0.0 END                                          AS study_plan_pdf_only,
        CASE WHEN si.study_plan_location_type             = 'external_official_portal'
              OR  si.admission_requirements_location_type = 'external_official_portal'
             THEN 1.0 ELSE 0.0 END                                          AS ext_portal_dep,
        CASE WHEN (
            (CASE WHEN si.degree_level_location_type           IN ('linked_pdf','external_official_portal') THEN 1 ELSE 0 END) +
            (CASE WHEN si.study_plan_location_type             IN ('linked_pdf','external_official_portal') THEN 1 ELSE 0 END) +
            (CASE WHEN si.admission_requirements_location_type IN ('linked_pdf','external_official_portal') THEN 1 ELSE 0 END) +
            (CASE WHEN si.admission_procedure_location_type    IN ('linked_pdf','external_official_portal') THEN 1 ELSE 0 END) +
            (CASE WHEN si.deadlines_location_type              IN ('linked_pdf','external_official_portal') THEN 1 ELSE 0 END) +
            (CASE WHEN si.contacts_location_type               IN ('linked_pdf','external_official_portal') THEN 1 ELSE 0 END)
        ) >= 4 THEN 1.0 ELSE 0.0 END                                        AS struct_fragmented,
        CASE WHEN si.contacts_present = 'present' THEN 1.0 ELSE 0.0 END    AS contacts_present_flag,
        -- js_heavy: derivato da journey_matrix
        CASE WHEN jm.js_dependency_level_preaudit = 'high' THEN 1 ELSE 0 END AS js_heavy_flag,
        -- orientation fields (non in DB — NULL per ora)
        NULL                                                                AS orientation_score_norm,
        NULL                                                                AS menu_clarity_score_val,
        NULL                                                                AS onsite_search_present_flag,
        -- best serp rank per corso
        serp_br.serp_best_rank_organic
    FROM course_sample_master csm
    JOIN journey_matrix jm ON csm.sample_course_id = jm.sample_course_id
    LEFT JOIN lighthouse_results lr
        ON csm.sample_course_id = lr.sample_course_id
       AND lr.page_role = 'course_page' AND lr.strategy = 'mobile'
    LEFT JOIN wave_results wr
        ON lr.source_document_id = wr.source_document_id
       AND wr.page_role = 'course_page'
    LEFT JOIN (SELECT course_id, target_found, target_found_top10, target_rank_organic
               FROM serp_observations WHERE query_template_id = 'SQ01') sq01
        ON csm.sample_course_id = sq01.course_id
    LEFT JOIN (SELECT course_id, target_found, target_found_top10, target_rank_organic
               FROM serp_observations WHERE query_template_id = 'SQ02') sq02
        ON csm.sample_course_id = sq02.course_id
    LEFT JOIN (SELECT course_id, target_found, target_found_top10
               FROM serp_observations WHERE query_template_id = 'SQ03') sq03
        ON csm.sample_course_id = sq03.course_id
    LEFT JOIN (
        SELECT srl.course_id,
               MAX(CASE WHEN srl.is_official_university_domain='false'
                         AND so.target_found='true'
                         AND CAST(srl.organic_rank AS INTEGER) < CAST(so.target_rank_organic AS INTEGER)
                        THEN 1 ELSE 0 END) AS tp_above
        FROM serp_results_long srl
        JOIN serp_observations so ON srl.serp_observation_id = so.serp_observation_id
        WHERE srl.query_template_id IN ('SQ01','SQ02')
        GROUP BY srl.course_id
    ) sp3 ON csm.sample_course_id = sp3.course_id
    LEFT JOIN (
        SELECT course_id,
               MIN(CASE WHEN target_found='true' THEN CAST(target_rank_organic AS INTEGER) END) AS serp_best_rank_organic
        FROM serp_observations GROUP BY course_id
    ) serp_br ON csm.sample_course_id = serp_br.course_id
    LEFT JOIN structural_indicators si ON csm.sample_course_id = si.course_id
),

-- helper: mediana generica via window (SQLite 3.25+)
-- usata sotto per journey, lh, wave, serp
journey_success_only AS (
    SELECT sample_course_id, university_id, journey_click_depth, journey_time_seconds
    FROM course_base WHERE is_blocked = 0
),

-- ─── Aggregati LH homepage ───────────────────────────────────────────────────
lh_home AS (
    SELECT
        lr.university_id,
        CAST(lr.performance_score   AS FLOAT) AS lh_perf,
        CAST(lr.accessibility_score AS FLOAT) AS lh_a11y
    FROM lighthouse_results lr
    WHERE lr.page_role = 'university_homepage' AND lr.strategy = 'mobile'
),

lh_home_median AS (
    SELECT
        university_id,
        AVG(lh_perf) AS homepage_lighthouse_performance_median,
        AVG(lh_a11y) AS homepage_lighthouse_accessibility_median
    FROM (
        SELECT university_id, lh_perf, lh_a11y,
               ROW_NUMBER() OVER (PARTITION BY university_id ORDER BY lh_perf) AS rn_p,
               COUNT(*)     OVER (PARTITION BY university_id)                  AS cnt
        FROM lh_home
    )
    WHERE rn_p IN ((cnt + 1) / 2, (cnt + 2) / 2)
    GROUP BY university_id
),

-- ─── Aggregati WAVE homepage ──────────────────────────────────────────────────
wave_home AS (
    SELECT
        sd.university_id,
        CAST(wr.error_count AS FLOAT) AS wave_err
    FROM wave_results wr
    JOIN source_document sd ON wr.source_document_id = sd.source_document_id
    WHERE wr.page_role = 'university_homepage'
),

wave_home_median AS (
    SELECT
        university_id,
        AVG(wave_err) AS homepage_wave_error_count_median
    FROM (
        SELECT university_id, wave_err,
               ROW_NUMBER() OVER (PARTITION BY university_id ORDER BY wave_err) AS rn,
               COUNT(*)     OVER (PARTITION BY university_id)                   AS cnt
        FROM wave_home
    )
    WHERE rn IN ((cnt + 1) / 2, (cnt + 2) / 2)
    GROUP BY university_id
),

-- ─── Aggregati per ateneo ─────────────────────────────────────────────────────
uni_agg AS (
    SELECT
        university_id,
        COUNT(*)                                                            AS n_course_pages,
        COUNT(*)                                                            AS n_journeys_attempted,
        SUM(is_blocked)                                                     AS n_journeys_blocked,
        SUM(1 - is_blocked)                                                 AS n_journeys_success,
        SUM(js_heavy_flag)                                                  AS js_heavy_course_count,
        SUM(is_blocked)                                                     AS blocked_js_course_count,
        CAST(SUM(is_blocked) AS FLOAT) / COUNT(*)                           AS blocked_js_share,
        -- journey aggregates (success only)
        AVG(official_result_present)                                        AS serp_official_result_present_rate,
        AVG(third_party_above)                                              AS serp_third_party_above_official_rate,
        AVG(sq01_top10)                                                     AS serp_known_institution_found_top10_rate,
        AVG(sq02_top10)                                                     AS serp_user_like_found_top10_rate,
        AVG(sq03_top10)                                                     AS serp_info_seeking_found_top10_rate,
        -- structural aggregates
        AVG(struct_essential_rate)                                          AS structural_essential_completeness_rate_mean,
        AVG(study_plan_pdf_only)                                            AS structural_study_plan_pdf_only_rate,
        AVG(ext_portal_dep)                                                 AS structural_external_portal_dependency_rate,
        AVG(struct_fragmented)                                              AS structural_fragmented_information_rate,
        AVG(contacts_present_flag)                                          AS structural_contacts_present_rate,
        -- wave (include browser_fallback)
        AVG(wave_collection_mode = 'browser_fallback')                      AS n_wave_browser_fallback_rate,
        SUM(CASE WHEN wave_collection_mode='browser_fallback' THEN 1 ELSE 0 END) AS n_wave_browser_fallback,
        -- lh course aggregates
        MIN(lh_performance)                                                 AS course_lighthouse_performance_min,
        MAX(lh_performance)                                                 AS course_lighthouse_performance_max,
        -- orientation (non in DB)
        NULL                                                                AS orientation_score_norm_mean,
        NULL                                                                AS orientation_score_norm_median,
        NULL                                                                AS menu_clarity_score_mean,
        NULL                                                                AS onsite_search_present_rate
    FROM course_base
    GROUP BY university_id
),

-- ─── Mediane corso-livello (richiedono window) ────────────────────────────────
course_medians AS (
    SELECT
        university_id,
        -- journey click depth (success only)
        AVG(jcd) AS journey_click_depth_median,
        AVG(jts) AS journey_time_seconds_median,
        AVG(lhp) AS course_lighthouse_performance_median,
        AVG(lha) AS course_lighthouse_accessibility_median,
        AVG(wer) AS course_wave_error_count_median,
        AVG(wcr) AS course_wave_contrast_error_count_median
    FROM (
        SELECT
            cb.university_id,
            -- click depth median (success only)
            CASE WHEN cb.is_blocked = 0 THEN cb.journey_click_depth END AS jcd,
            CASE WHEN cb.is_blocked = 0 THEN cb.journey_time_seconds END AS jts,
            cb.lh_performance AS lhp,
            cb.lh_accessibility AS lha,
            cb.wave_error_count AS wer,
            cb.wave_contrast_error_count AS wcr,
            -- row numbers for median
            ROW_NUMBER() OVER (PARTITION BY cb.university_id ORDER BY CASE WHEN cb.is_blocked=0 THEN cb.journey_click_depth END NULLS LAST) AS rn_jcd,
            ROW_NUMBER() OVER (PARTITION BY cb.university_id ORDER BY CASE WHEN cb.is_blocked=0 THEN cb.journey_time_seconds END NULLS LAST) AS rn_jts,
            ROW_NUMBER() OVER (PARTITION BY cb.university_id ORDER BY cb.lh_performance   NULLS LAST) AS rn_lhp,
            ROW_NUMBER() OVER (PARTITION BY cb.university_id ORDER BY cb.lh_accessibility NULLS LAST) AS rn_lha,
            ROW_NUMBER() OVER (PARTITION BY cb.university_id ORDER BY cb.wave_error_count           NULLS LAST) AS rn_wer,
            ROW_NUMBER() OVER (PARTITION BY cb.university_id ORDER BY cb.wave_contrast_error_count  NULLS LAST) AS rn_wcr,
            COUNT(CASE WHEN cb.is_blocked=0 THEN 1 END) OVER (PARTITION BY cb.university_id) AS cnt_success,
            COUNT(*) OVER (PARTITION BY cb.university_id) AS cnt_all
        FROM course_base cb
    )
    WHERE rn_jcd IN ((cnt_success + 1) / 2, (cnt_success + 2) / 2)
       OR rn_lhp IN ((cnt_all + 1) / 2, (cnt_all + 2) / 2)
       OR rn_lha IN ((cnt_all + 1) / 2, (cnt_all + 2) / 2)
       OR rn_wer IN ((cnt_all + 1) / 2, (cnt_all + 2) / 2)
       OR rn_wcr IN ((cnt_all + 1) / 2, (cnt_all + 2) / 2)
    GROUP BY university_id
),

-- wave excl reduced (api_primary only)
course_wave_excl_reduced AS (
    SELECT
        cb.university_id,
        AVG(cb.wave_error_count) AS course_wave_error_count_median_excl_reduced
    FROM (
        SELECT cb2.university_id, cb2.wave_error_count,
               ROW_NUMBER() OVER (PARTITION BY cb2.university_id ORDER BY cb2.wave_error_count NULLS LAST) AS rn,
               COUNT(*)     OVER (PARTITION BY cb2.university_id) AS cnt
        FROM course_base cb2 WHERE cb2.wave_collection_mode = 'api_primary'
    ) cb
    WHERE rn IN ((cnt + 1) / 2, (cnt + 2) / 2)
    GROUP BY university_id
),

-- serp best rank median per ateneo
serp_rank_median AS (
    SELECT
        university_id,
        AVG(CAST(serp_best_rank_organic AS FLOAT)) AS serp_best_rank_organic_median
    FROM (
        SELECT cb.university_id, cb.serp_best_rank_organic,
               ROW_NUMBER() OVER (PARTITION BY cb.university_id ORDER BY CAST(cb.serp_best_rank_organic AS FLOAT) NULLS LAST) AS rn,
               COUNT(CASE WHEN cb.serp_best_rank_organic IS NOT NULL THEN 1 END) OVER (PARTITION BY cb.university_id) AS cnt
        FROM course_base cb
        WHERE cb.serp_best_rank_organic IS NOT NULL
    )
    WHERE rn IN ((cnt + 1) / 2, (cnt + 2) / 2)
    GROUP BY university_id
),

-- SERP observations count per ateneo
serp_counts AS (
    SELECT university_id, COUNT(*) AS n_serp_observations
    FROM serp_observations
    GROUP BY university_id
),

-- structural records count per ateneo
struct_counts AS (
    SELECT university_id, COUNT(*) AS n_structural_records
    FROM structural_indicators
    GROUP BY university_id
),

-- ─── Final assembly ateneo ────────────────────────────────────────────────────
final AS (
SELECT
    -- §2.1 Identità ateneo
    usm.university_id,
    usm.university_name,
    usm.macro_area,
    usm.institution_type,
    usm.city                                                            AS university_city,
    usm.university_homepage_url,
    usm.programmes_hub_url,

    -- §2.2 Denominatori espliciti
    ua.n_course_pages,
    ua.n_journeys_attempted,
    ua.n_journeys_blocked,
    ua.n_journeys_success,
    COALESCE(sc.n_serp_observations, 0)                                 AS n_serp_observations,
    COALESCE(stc.n_structural_records, 0)                               AS n_structural_records,
    ua.n_wave_browser_fallback,

    -- §2.3 Aggregati journey
    CAST(ROUND(CAST(ua.n_journeys_success AS FLOAT) / ua.n_journeys_attempted, 4) AS TEXT) AS journey_success_rate,
    CAST(ROUND(cm.journey_click_depth_median, 2) AS TEXT)               AS journey_click_depth_median,
    CAST(ROUND(cm.journey_time_seconds_median, 2) AS TEXT)              AS journey_time_seconds_median,
    ua.menu_clarity_score_mean,
    ua.onsite_search_present_rate,

    -- §2.4 Aggregati orientation (non in DB)
    ua.orientation_score_norm_mean,
    ua.orientation_score_norm_median,

    -- §2.5 Aggregati SERP
    CAST(ROUND(ua.serp_known_institution_found_top10_rate, 4) AS TEXT)  AS serp_known_institution_found_top10_rate,
    CAST(ROUND(ua.serp_user_like_found_top10_rate, 4) AS TEXT)          AS serp_user_like_found_top10_rate,
    CAST(ROUND(ua.serp_info_seeking_found_top10_rate, 4) AS TEXT)       AS serp_info_seeking_found_top10_rate,
    CAST(ROUND(ua.serp_official_result_present_rate, 4) AS TEXT)        AS serp_official_result_present_rate,
    CAST(ROUND(ua.serp_third_party_above_official_rate, 4) AS TEXT)     AS serp_third_party_above_official_rate,
    CAST(ROUND(sr.serp_best_rank_organic_median, 2) AS TEXT)            AS serp_best_rank_organic_median,

    -- §2.6 Aggregati LH (mobile)
    CAST(ROUND(lhm.homepage_lighthouse_performance_median, 4) AS TEXT)  AS homepage_lighthouse_performance_median,
    CAST(ROUND(lhm.homepage_lighthouse_accessibility_median, 4) AS TEXT) AS homepage_lighthouse_accessibility_median,
    CAST(ROUND(cm.course_lighthouse_performance_median, 4) AS TEXT)     AS course_lighthouse_performance_median,
    CAST(ROUND(cm.course_lighthouse_accessibility_median, 4) AS TEXT)   AS course_lighthouse_accessibility_median,
    CAST(ROUND(ua.course_lighthouse_performance_min, 4) AS TEXT)        AS course_lighthouse_performance_min,
    CAST(ROUND(ua.course_lighthouse_performance_max, 4) AS TEXT)        AS course_lighthouse_performance_max,

    -- §2.7 Aggregati WAVE
    CAST(ROUND(whm.homepage_wave_error_count_median, 2) AS TEXT)        AS homepage_wave_error_count_median,
    CAST(ROUND(cm.course_wave_error_count_median, 2) AS TEXT)           AS course_wave_error_count_median,
    CAST(ROUND(cwe.course_wave_error_count_median_excl_reduced, 2) AS TEXT) AS course_wave_error_count_median_excl_reduced,
    CAST(ROUND(cm.course_wave_contrast_error_count_median, 2) AS TEXT)  AS course_wave_contrast_error_count_median,

    -- §2.8 Aggregati structural
    CAST(ROUND(ua.structural_essential_completeness_rate_mean, 4) AS TEXT) AS structural_essential_completeness_rate_mean,
    CAST(ROUND(ua.structural_study_plan_pdf_only_rate, 4) AS TEXT)      AS structural_study_plan_pdf_only_rate,
    CAST(ROUND(ua.structural_external_portal_dependency_rate, 4) AS TEXT) AS structural_external_portal_dependency_rate,
    CAST(ROUND(ua.structural_fragmented_information_rate, 4) AS TEXT)   AS structural_fragmented_information_rate,
    CAST(ROUND(ua.structural_contacts_present_rate, 4) AS TEXT)         AS structural_contacts_present_rate,

    -- §2.9 JS-heavy e blocked
    ua.js_heavy_course_count,
    ua.blocked_js_course_count,
    CAST(ROUND(ua.blocked_js_share, 4) AS TEXT)                         AS blocked_js_share,

    -- §2.10 Flag interpretivi aggregati — NOT Step C (Step F)
    -- journey_high_friction_rate, weak_external_findability_rate,
    -- accessibility_risk_rate, technical_risk_rate, information_fragmentation_rate,
    -- critical_student_pathway_count, multi_phase_critical_case_count

    -- §2.11 Controllo
    'sample_v1'     AS audit_round,
    date('now')     AS audit_date,
    NULL            AS crawl_run_id,
    'draft'         AS review_status,
    NULL            AS overall_notes,
    NULL            AS provenance_notes

FROM university_sample_master usm
LEFT JOIN uni_agg         ua  ON usm.university_id = ua.university_id
LEFT JOIN course_medians  cm  ON usm.university_id = cm.university_id
LEFT JOIN course_wave_excl_reduced cwe ON usm.university_id = cwe.university_id
LEFT JOIN lh_home_median  lhm ON usm.university_id = lhm.university_id
LEFT JOIN wave_home_median whm ON usm.university_id = whm.university_id
LEFT JOIN serp_rank_median sr  ON usm.university_id = sr.university_id
LEFT JOIN serp_counts      sc  ON usm.university_id = sc.university_id
LEFT JOIN struct_counts    stc ON usm.university_id = stc.university_id
)

SELECT * FROM final
ORDER BY university_id;
