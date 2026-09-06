-- CAREER-INTELLIGENCE-V2.4
--
-- Create Lingjia Gardner's broad-market discovery search profiles for the
-- existing Stepstone and Bundesagentur sensor connectors.
--
-- This migration changes DB-backed search configuration only. It does not run
-- ingestion, fetch provider data, create employer-origin candidates, promote
-- sources, rank jobs, change Product V1 authority or touch application flow.

WITH profile_seed(profile_name, source_name, theme_key, page_size) AS (
    VALUES
        ('lingjia_market_stepstone_autonomy_robotics', 'stepstone', 'autonomy_robotics', 15),
        ('lingjia_market_stepstone_technical_program_product', 'stepstone', 'technical_program_product', 15),
        ('lingjia_market_stepstone_ai_data_transformation', 'stepstone', 'ai_data_transformation', 15),
        ('lingjia_market_stepstone_strategy_operations', 'stepstone', 'strategy_operations', 15),
        ('lingjia_market_stepstone_mobility_platform_deployment', 'stepstone', 'mobility_platform_deployment', 15),
        ('lingjia_market_ba_autonomy_robotics', 'bundesagentur_fuer_arbeit', 'autonomy_robotics', 15),
        ('lingjia_market_ba_technical_program_product', 'bundesagentur_fuer_arbeit', 'technical_program_product', 15),
        ('lingjia_market_ba_ai_data_transformation', 'bundesagentur_fuer_arbeit', 'ai_data_transformation', 15),
        ('lingjia_market_ba_strategy_operations', 'bundesagentur_fuer_arbeit', 'strategy_operations', 15),
        ('lingjia_market_ba_mobility_platform_deployment', 'bundesagentur_fuer_arbeit', 'mobility_platform_deployment', 15)
)
INSERT INTO search_profiles (
    profile_name,
    source_name,
    search_term,
    search_location,
    search_radius_km,
    offer_type,
    page_size,
    is_active,
    recurring_ingestion_enabled
)
SELECT
    profile_name,
    source_name,
    NULL,
    NULL,
    NULL,
    1,
    page_size,
    TRUE,
    TRUE
FROM profile_seed
ON CONFLICT (profile_name)
DO UPDATE SET
    source_name = EXCLUDED.source_name,
    search_term = EXCLUDED.search_term,
    search_location = EXCLUDED.search_location,
    search_radius_km = EXCLUDED.search_radius_km,
    offer_type = EXCLUDED.offer_type,
    page_size = EXCLUDED.page_size,
    is_active = EXCLUDED.is_active,
    recurring_ingestion_enabled = EXCLUDED.recurring_ingestion_enabled;

WITH terms(theme_key, search_term) AS (
    VALUES
        ('autonomy_robotics', 'autonomous mobility'),
        ('autonomy_robotics', 'autonomous driving'),
        ('autonomy_robotics', 'robotics program manager'),
        ('autonomy_robotics', 'robotics product manager'),
        ('autonomy_robotics', 'intelligent mobility systems'),
        ('autonomy_robotics', 'ADAS strategy'),
        ('technical_program_product', 'technical program manager'),
        ('technical_program_product', 'senior product manager platform'),
        ('technical_program_product', 'product operations manager'),
        ('technical_program_product', 'program manager data platform'),
        ('technical_program_product', 'principal product manager AI'),
        ('technical_program_product', 'delivery lead technology'),
        ('ai_data_transformation', 'AI transformation lead'),
        ('ai_data_transformation', 'data transformation manager'),
        ('ai_data_transformation', 'AI product manager'),
        ('ai_data_transformation', 'data strategy lead'),
        ('ai_data_transformation', 'analytics platform manager'),
        ('ai_data_transformation', 'machine learning platform lead'),
        ('strategy_operations', 'strategy operations technology'),
        ('strategy_operations', 'chief of staff technology'),
        ('strategy_operations', 'executive operations mobility'),
        ('strategy_operations', 'transformation program lead'),
        ('strategy_operations', 'business operations AI'),
        ('strategy_operations', 'strategic projects manager'),
        ('mobility_platform_deployment', 'mobility platform manager'),
        ('mobility_platform_deployment', 'fleet operations technology'),
        ('mobility_platform_deployment', 'mobility ecosystem strategy'),
        ('mobility_platform_deployment', 'deployment program manager'),
        ('mobility_platform_deployment', 'charging infrastructure product'),
        ('mobility_platform_deployment', 'transport data platform')
),
profile_theme(profile_name, theme_key) AS (
    VALUES
        ('lingjia_market_stepstone_autonomy_robotics', 'autonomy_robotics'),
        ('lingjia_market_stepstone_technical_program_product', 'technical_program_product'),
        ('lingjia_market_stepstone_ai_data_transformation', 'ai_data_transformation'),
        ('lingjia_market_stepstone_strategy_operations', 'strategy_operations'),
        ('lingjia_market_stepstone_mobility_platform_deployment', 'mobility_platform_deployment'),
        ('lingjia_market_ba_autonomy_robotics', 'autonomy_robotics'),
        ('lingjia_market_ba_technical_program_product', 'technical_program_product'),
        ('lingjia_market_ba_ai_data_transformation', 'ai_data_transformation'),
        ('lingjia_market_ba_strategy_operations', 'strategy_operations'),
        ('lingjia_market_ba_mobility_platform_deployment', 'mobility_platform_deployment')
)
INSERT INTO search_terms (
    search_profile_id,
    search_term,
    is_active
)
SELECT
    sp.id,
    terms.search_term,
    TRUE
FROM profile_theme
JOIN search_profiles sp
  ON sp.profile_name = profile_theme.profile_name
JOIN terms
  ON terms.theme_key = profile_theme.theme_key
ON CONFLICT (search_profile_id, search_term)
DO UPDATE SET
    is_active = EXCLUDED.is_active;
