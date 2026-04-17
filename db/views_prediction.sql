USE PosInsight;
GO

CREATE OR ALTER VIEW vw_prediction_inputs AS
SELECT
    a.report_year,
    a.report_month,
    a.monthly_total_sales,
    a.total_yoy_pct,
    a.gift_5000_sales,
    a.gift_5000_yoy_pct,
    a.gift_floor_category,
    a.gift_floor_sales,
    a.gift_floor_yoy_pct,
    a.gram_cookies_sales,
    a.fb_sales,
    a.customer_count,
    a.unit_price,
    a.avg_daily_sales,
    a.dept_store_sales,
    a.retail_food_index,
    a.cci_index,
    a.cpi_yoy_pct,
    a.cpi_food_yoy_pct,
    a.avg_wage_yoy_pct,
    a.twd_jpy_rate,
    a.twd_usd_rate,
    a.unemployment_rate,
    a.inbound_tourists,
    a.bsi_index,
    a.has_lunar_new_year,
    a.lunar_new_year_day,
    a.has_mid_autumn,
    a.mid_autumn_day,
    a.working_days,
    a.calendar_days,
    a.weekend_days,
    a.gdp_yoy_pct,
    a.private_consumption_real_yoy_pct,
    a.department_store_yoy_pct,
    a.retail_trade_yoy_pct,
    a.gift_market_sentiment_index,
    a.stock_wealth_effect_index,
    a.sokuho_mtd_sales,
    a.sokuho_customers
FROM vw_analysis_monthly a;
GO

CREATE OR ALTER VIEW vw_kouseihi_vs_sokuho_reconcile AS
SELECT
    a.report_year,
    a.report_month,
    a.monthly_total_sales AS kouseihi_monthly_total_sales,
    a.sokuho_mtd_sales,
    CASE
        WHEN a.monthly_total_sales IS NULL OR a.monthly_total_sales = 0 THEN NULL
        ELSE ABS(a.monthly_total_sales - a.sokuho_mtd_sales) * 100.0 / a.monthly_total_sales
    END AS diff_pct
FROM vw_analysis_monthly a;
GO
