USE PosInsight;
GO

IF OBJECT_ID('dim_gift_category_mapping', 'U') IS NULL
CREATE TABLE dim_gift_category_mapping (
    id                  INT             IDENTITY(1,1) PRIMARY KEY,
    source_category     NVARCHAR(30)    NOT NULL,
    canonical_group     NVARCHAR(20)    NOT NULL,   -- GIFT_LOW / GIFT_HIGH / GIFT_LARGE
    threshold_floor     INT             NULL,
    threshold_ceiling   INT             NULL,
    sort_order          TINYINT         NOT NULL,
    CONSTRAINT uq_gift_mapping_source UNIQUE (source_category),
    CONSTRAINT chk_gift_group CHECK (canonical_group IN ('GIFT_LOW', 'GIFT_HIGH', 'GIFT_LARGE'))
);
GO

CREATE OR ALTER VIEW vw_gift_canonical_monthly AS
SELECT
    f.report_year,
    f.report_month,
    f.period_type,
    m.canonical_group,
    m.threshold_floor,
    m.threshold_ceiling,
    SUM(f.sales_result) AS sales_result,
    SUM(f.composition_curr_pct) AS composition_curr_pct,
    SUM(f.composition_prev_pct) AS composition_prev_pct,
    AVG(f.sales_yoy_pct) AS sales_yoy_pct
FROM fact_kouseihi_category f
JOIN dim_gift_category_mapping m
  ON m.source_category = f.category
WHERE f.period_type = 'MONTHLY'
GROUP BY
    f.report_year,
    f.report_month,
    f.period_type,
    m.canonical_group,
    m.threshold_floor,
    m.threshold_ceiling;
GO

CREATE OR ALTER VIEW vw_gift_combined_monthly AS
SELECT
    report_year,
    report_month,
    period_type,
    CAST('GIFT_COMBINED' AS NVARCHAR(20)) AS canonical_group,
    SUM(sales_result) AS sales_result,
    SUM(composition_curr_pct) AS composition_curr_pct,
    SUM(composition_prev_pct) AS composition_prev_pct
FROM vw_gift_canonical_monthly
WHERE canonical_group IN ('GIFT_LOW', 'GIFT_HIGH')
GROUP BY report_year, report_month, period_type;
GO
