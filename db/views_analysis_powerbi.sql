USE PosInsight;
GO

CREATE OR ALTER VIEW vw_gift_monthly_with_macro AS
SELECT *
FROM vw_gift_analysis_dataset;
GO

CREATE OR ALTER VIEW vw_gift_annual_summary AS
SELECT
    report_year,
    canonical_group,
    SUM(sales_result) AS annual_sales,
    AVG(sales_yoy_pct) AS annual_avg_yoy,
    AVG(cci_index) AS avg_cci,
    AVG(gdp_yoy_pct) AS avg_gdp_yoy
FROM vw_gift_analysis_dataset
GROUP BY report_year, canonical_group;
GO

CREATE OR ALTER VIEW vw_gift_peak_calendar AS
WITH ranked AS (
    SELECT
        report_year,
        canonical_group,
        report_month,
        sales_result,
        ROW_NUMBER() OVER (PARTITION BY report_year, canonical_group ORDER BY sales_result DESC) AS rn
    FROM vw_gift_analysis_dataset
)
SELECT
    report_year,
    canonical_group,
    report_month,
    sales_result
FROM ranked
WHERE rn <= 3;
GO
