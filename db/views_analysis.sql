USE PosInsight;
GO

CREATE OR ALTER VIEW vw_analysis_monthly AS
WITH kpi_monthly AS (
    SELECT
        report_year,
        report_month,
        customer_count,
        unit_price,
        avg_daily_sales
    FROM fact_kouseihi_kpi
    WHERE period_type = 'MONTHLY'
),
sokuho_month_end AS (
    SELECT
        YEAR(fs.report_date) AS report_year,
        MONTH(fs.report_date) AS report_month,
        fs.sales_result AS sokuho_mtd_sales,
        fs.customer_count AS sokuho_customers
    FROM fact_sales fs
    JOIN dim_store ds ON ds.store_id = fs.store_id
    WHERE ds.store_name = 'GRAND TOTAL'
      AND RTRIM(fs.record_type) = 'MTD'
      AND fs.report_date = EOMONTH(fs.report_date)
)
SELECT
    total.report_year,
    total.report_month,
    total.sales_result AS monthly_total_sales,
    total.sales_yoy_pct AS total_yoy_pct,
    gift_5000.sales_result AS gift_5000_sales,
    gift_5000.sales_yoy_pct AS gift_5000_yoy_pct,
    gift_floor.category AS gift_floor_category,
    gift_floor.sales_result AS gift_floor_sales,
    gift_floor.sales_yoy_pct AS gift_floor_yoy_pct,
    gram.sales_result AS gram_cookies_sales,
    fb.sales_result AS fb_sales,
    total.composition_curr_pct AS total_composition_curr_pct,
    gift_5000.composition_curr_pct AS gift_5000_composition_curr_pct,
    gift_floor.composition_curr_pct AS gift_floor_composition_curr_pct,
    kpi.customer_count,
    kpi.unit_price,
    kpi.avg_daily_sales,
    macro.dept_store_sales,
    macro.retail_food_index,
    macro.cci_index,
    macro.cpi_yoy_pct,
    macro.cpi_food_yoy_pct,
    macro.avg_wage_yoy_pct,
    macro.unemployment_rate,
    macro.twd_jpy_rate,
    macro.twd_usd_rate,
    macro.inbound_tourists,
    macro.bsi_index,
    macro.has_lunar_new_year,
    macro.lunar_new_year_day,
    macro.has_mid_autumn,
    macro.mid_autumn_day,
    macro.working_days,
    macro.calendar_days,
    macro.weekend_days,
    macro.gdp_yoy_pct,
    macro.private_consumption_real_yoy_pct,
    macro.department_store_yoy_pct,
    macro.retail_trade_yoy_pct,
    macro.gift_market_sentiment_index,
    macro.stock_wealth_effect_index,
    sokuho.sokuho_mtd_sales,
    sokuho.sokuho_customers
FROM fact_kouseihi_category total
LEFT JOIN fact_kouseihi_category gift_5000
       ON gift_5000.report_year = total.report_year
      AND gift_5000.report_month = total.report_month
      AND gift_5000.period_type = 'MONTHLY'
      AND gift_5000.category = 'GIFT_5000_UP'
LEFT JOIN fact_kouseihi_category gift_floor
       ON gift_floor.report_year = total.report_year
      AND gift_floor.report_month = total.report_month
      AND gift_floor.period_type = 'MONTHLY'
      AND gift_floor.category IN ('GIFT_760_DOWN', 'GIFT_850_DOWN', 'GIFT_900_DOWN')
LEFT JOIN fact_kouseihi_category gram
       ON gram.report_year = total.report_year
      AND gram.report_month = total.report_month
      AND gram.period_type = 'MONTHLY'
      AND gram.category = 'GRAM_COOKIES'
LEFT JOIN fact_kouseihi_category fb
       ON fb.report_year = total.report_year
      AND fb.report_month = total.report_month
      AND fb.period_type = 'MONTHLY'
      AND fb.category = 'FB'
LEFT JOIN kpi_monthly kpi
       ON kpi.report_year = total.report_year
      AND kpi.report_month = total.report_month
LEFT JOIN dim_macro_indicators macro
       ON macro.report_year = total.report_year
      AND macro.report_month = total.report_month
LEFT JOIN sokuho_month_end sokuho
       ON sokuho.report_year = total.report_year
      AND sokuho.report_month = total.report_month
WHERE total.period_type = 'MONTHLY'
  AND total.category = 'TOTAL';
GO

CREATE OR ALTER VIEW vw_gift_analysis_dataset AS
SELECT
    g.report_year,
    g.report_month,
    g.canonical_group,
    g.sales_result,
    g.sales_yoy_pct,
    g.composition_curr_pct,
    g.composition_prev_pct,
    g.threshold_floor,
    g.threshold_ceiling,
    m.dept_store_sales,
    m.retail_food_index,
    m.cci_index,
    m.cpi_yoy_pct,
    m.cpi_food_yoy_pct,
    m.avg_wage_yoy_pct,
    m.unemployment_rate,
    m.twd_jpy_rate,
    m.twd_usd_rate,
    m.inbound_tourists,
    m.bsi_index,
    m.has_lunar_new_year,
    m.lunar_new_year_day,
    m.has_mid_autumn,
    m.mid_autumn_day,
    m.working_days,
    m.calendar_days,
    m.gdp_yoy_pct,
    m.private_consumption_real_yoy_pct,
    m.department_store_yoy_pct,
    m.retail_trade_yoy_pct,
    m.gift_market_sentiment_index,
    m.stock_wealth_effect_index
FROM vw_gift_canonical_monthly g
LEFT JOIN dim_macro_indicators m
       ON m.report_year = g.report_year
      AND m.report_month = g.report_month
WHERE g.period_type = 'MONTHLY'

UNION ALL

SELECT
    c.report_year,
    c.report_month,
    c.canonical_group,
    c.sales_result,
    NULL AS sales_yoy_pct,
    c.composition_curr_pct,
    c.composition_prev_pct,
    NULL AS threshold_floor,
    NULL AS threshold_ceiling,
    m.dept_store_sales,
    m.retail_food_index,
    m.cci_index,
    m.cpi_yoy_pct,
    m.cpi_food_yoy_pct,
    m.avg_wage_yoy_pct,
    m.unemployment_rate,
    m.twd_jpy_rate,
    m.twd_usd_rate,
    m.inbound_tourists,
    m.bsi_index,
    m.has_lunar_new_year,
    m.lunar_new_year_day,
    m.has_mid_autumn,
    m.mid_autumn_day,
    m.working_days,
    m.calendar_days,
    m.gdp_yoy_pct,
    m.private_consumption_real_yoy_pct,
    m.department_store_yoy_pct,
    m.retail_trade_yoy_pct,
    m.gift_market_sentiment_index,
    m.stock_wealth_effect_index
FROM vw_gift_combined_monthly c
LEFT JOIN dim_macro_indicators m
       ON m.report_year = c.report_year
      AND m.report_month = c.report_month
WHERE c.period_type = 'MONTHLY';
GO
