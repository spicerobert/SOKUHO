-- ============================================================
-- fact_sales.value_source：PDF＝報表原值；DERIVED＝依月累計差補的單日（Jack 2026-10-22）
-- 補值規則在 etl/loader.py 的 _DERIVE_SQL。只加欄位，不動既有資料；可重複執行。
-- ============================================================
USE PosInsight;
GO

IF COL_LENGTH('dbo.fact_sales', 'value_source') IS NULL
    ALTER TABLE dbo.fact_sales ADD value_source VARCHAR(8) NOT NULL
        CONSTRAINT df_fact_sales_value_source DEFAULT 'PDF'
        CONSTRAINT chk_fact_sales_value_source CHECK (value_source IN ('PDF', 'DERIVED'));
GO
