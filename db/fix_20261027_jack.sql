-- Jack 2026-10-27 的兩筆資料修正（可重跑）。套用：只跑本檔，不要跑整份 schema.sql。

-- 1. Costco 2025-06-25：非門市通路不補單日（etl/loader.py _DERIVE_SQL 已限 store_type='store'），
--    改回 PDF 原值 0；803,264 由 vw_daily_store_sales.adjustment 呈現。DERIVED 只改過這三欄，其餘仍是 PDF 原值。
UPDATE fs SET sales_result = 0, sales_incl_result = ISNULL(fs.transfer_amount, 0), value_source = 'PDF'
FROM fact_sales fs JOIN dim_store ds ON ds.store_id = fs.store_id
WHERE ds.store_code = '4010' AND fs.report_date = '2025-06-25' AND fs.record_type = 'DAILY' AND fs.value_source = 'DERIVED';

-- 2. 台中三越 2020-12-13：PDF 上店名印成「0」，解析器丟了這列，原本以 12/14 反推單日、沒有 MTD。
--    數字照 SOKUHO 2020.12.13.pdf 第 1 頁抄；source_file 另取名，--force 重匯該日時不會被刪。
DECLARE @tc SMALLINT = (SELECT store_id FROM dim_store WHERE store_code = '1025');
DECLARE @src NVARCHAR(100) = N'SOKUHO 2020.12.13.pdf（手補：店名印成 0）';

UPDATE fact_sales
SET sales_result = 13405, sales_budget_pct = 103.96, sales_yoy_pct = 108.66,
    customer_count = 36, customer_yoy_pct = 138.46, unit_price = 372, unit_price_yoy_pct = 78.47,
    transfer_amount = 0, sales_incl_result = 13405, sales_incl_budget_pct = 103.96, sales_incl_yoy_pct = 108.66,
    source_file = @src, value_source = 'PDF'
WHERE store_id = @tc AND report_date = '2020-12-13' AND record_type = 'DAILY';

INSERT INTO fact_sales (report_date, store_id, record_type, sales_result, sales_budget_pct, sales_yoy_pct,
                        customer_count, customer_yoy_pct, unit_price, unit_price_yoy_pct,
                        transfer_amount, sales_incl_result, sales_incl_budget_pct, sales_incl_yoy_pct,
                        source_file, value_source)
SELECT '2020-12-13', @tc, 'MTD', 164116, 81.47, 84.59, 312, 104.35, 526, 81.06, 0, 164116, 81.47, 84.59, @src, 'PDF'
WHERE NOT EXISTS (SELECT 1 FROM fact_sales WHERE store_id = @tc AND report_date = '2020-12-13' AND record_type = 'MTD');
