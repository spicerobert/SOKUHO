# 系統設計文件（SDD）
## KOUSEIHI ETL ＆ 多維度營收分析預測系統

| 欄位 | 內容 |
|------|------|
| 版本 | v1.0 |
| 日期 | 2026-04-16 |
| 作者 | Robert |
| 狀態 | 第一階段完成（任務一已完成，等待第二階段） |
| 資料庫 | PosInsight（與 SOKUHO 共用） |

---

## 目錄

1. [專案範疇](#1-專案範疇)
2. [任務一：KOUSEIHI ETL](#2-任務一kouseihi-etl)
   - 2.1 資料來源分析
   - 2.2 資料庫 Schema 設計
   - 2.3 ETL 管線設計
   - 2.4 實作待辦清單
   - 2.5 測試與驗收規格
3. [任務二：營收分析與預測](#3-任務二營收分析與預測)
   - 3.1 資料整合設計
   - 3.2 外部總體經濟指標清單
   - 3.3 分析架構
   - 3.4 預測模型設計
   - 3.5 實作待辦清單
   - 3.6 測試與驗收規格
4. [整體驗收流程](#4-整體驗收流程)
5. [附錄](#5-附錄)

---

## 1. 專案範疇

### 背景

SOKUHO 已將每日銷售速報匯入 `PosInsight` 資料庫（2020-2025 年份資料）。KOUSEIHI 為**年度按月份拆解的商品類別銷售構成比報表**，以每年一份 PDF 的形式存放（目前共 2021~2025 年，5 份）。

### 目標

| # | 目標 | 負責任務 |
|---|------|---------|
| 1 | 將 KOUSEIHI PDF 的月別商品類別銷售資料匯入同一資料庫 | 任務一 |
| 2 | 以過去五年內外部資料交叉分析，找出關鍵影響因子 | 任務二 |
| 3 | 建立可預測年度重要銷售檔期及年度營收成長的模型 | 任務二 |
| 4 | 透過 PowerBI View 供報表查詢 | 兩者皆有 |

### 約束條件

- 不修改 OneDrive 上的原始 PDF 檔名
- 與 SOKUHO 共用同一 `PosInsight` SQL Server 資料庫
- 使用相同開發環境（Python + uv + .venv）
- ETL 設計須具備冪等性（重跑不重複寫入）

---

## 2. 任務一：KOUSEIHI ETL

### 2.1 資料來源分析

#### 2.1.1 檔案清單

| 檔名 | 報告年份 | 製表日期（預估） |
|------|---------|---------------|
| `202112-KOUSEIHI Company.pdf` | 2021 | 2022/01 |
| `202212-KOUSEIHI Company.pdf` | 2022 | 2023/01 |
| `202312-KOUSEIHI Company.pdf` | 2023 | 2024/01 |
| `202412-KOUSEIHI Company.pdf` | 2024 | 2025/01 |
| `202512-KOUSEIHI Company.pdf` | 2025 | 2026/01 |

> 命名規則：`YYYYMM-KOUSEIHI Company.pdf`，其中 MM 固定為 `12`（年度彙總報表，並非月報）

#### 2.1.2 PDF 結構規格

**報表標頭**
```
詩特莉食品股份有限公司
Monthly Sales Distribution
部門別：Company  YYYY/12
頁　次：1/1
製表日期：YYYY+1/01/XX
```

**主表欄位**（共 15 個時間欄）

| 索引 | 欄位名 | 說明 |
|------|--------|------|
| 0 | 1月 | 一月 |
| 1 | 2月 | 二月 |
| 2 | 3月 | 三月 |
| 3 | 4月 | 四月 |
| 4 | 5月 | 五月 |
| 5 | 6月 | 六月 |
| 6 | 上期 | H1 小計（1~6 月合計） |
| 7 | 7月 | 七月 |
| 8 | 8月 | 八月 |
| 9 | 9月 | 九月 |
| 10 | 10月 | 十月 |
| 11 | 11月 | 十一月 |
| 12 | 12月 | 十二月 |
| 13 | 下期 | H2 小計（7~12 月合計） |
| 14 | 合計 | 年度合計 |

**商品類別（8 類，依序出現）**

| 代碼 | PDF 顯示名稱 | 說明 |
|------|-------------|------|
| `GRAM_COOKIES` | GRAM COOKIES | 餅乾類 |
| `GIFT_760_DOWN` | GIFT 760↓ | 禮盒 760 元以下（2021~2022） |
| `GIFT_760_UP` | GIFT 760↑ | 禮盒 760~5000 元（2021~2022） |
| `GIFT_850_DOWN` | GIFT 850↓ | 禮盒 850 元以下（2023） |
| `GIFT_850_UP` | GIFT 850↑ | 禮盒 850~5000 元（2023） |
| `GIFT_900_DOWN` | GIFT 900↓ | 禮盒 900 元以下（2024~2025） |
| `GIFT_900_UP` | GIFT 900↑ | 禮盒 900~5000 元（2024~2025） |
| `GIFT_5000_UP` | GIFT 5000↑ | 禮盒 5000 元以上 |
| `DRY_CAKE` | DRY CAKE | 蛋糕類 |
| `FB` | F&B | 餐飲類 |
| `OTHER` | OTHER | 其他 |
| `TOTAL` | TOTAL | 全類別合計 |

**每個類別 4 個 metric 列（依序）**

| 列序 | 指標名 | 欄位名 | 說明 |
|------|--------|--------|------|
| 1 | 賣上 | `sales_result` | 銷售金額（TWD） |
| 2 | 前年比 | `sales_yoy_pct` | 同期前年比（%，100 = 持平） |
| 3 | 本年構成 | `composition_curr_pct` | 本年度類別佔比（%） |
| 4 | 前年構成 | `composition_prev_pct` | 前年同期類別佔比（%） |

**底部 KPI 區塊**（TOTAL 列之後）

| KPI 名稱 | PDF 顯示名稱 | 欄位 | 列數 |
|---------|-------------|------|------|
| 客數 | CUSTOMER COUNT | `customer_count`（本年）、`customer_yoy_pct`（前年比） | 2 列 |
| 客單價 | CUS UNIT PRICE | `unit_price`（本年）、`unit_price_yoy_pct`（前年比） | 2 列 |
| 週轉率 | TURNOVER | `turnover_curr`（本年）、`turnover_prev`（前年） | 2 列 |
| 月銷售日數 | DAY IN MONTH | `day_in_month_curr`（本年）、`day_in_month_prev`（前年） | 2 列 |
| 日平均銷售 | AVERAGE DAILY SALES | `avg_daily_sales`（本年）、`avg_daily_sales_yoy_pct`（前年比） | 2 列 |

#### 2.1.3 資料量估計

- 每年 PDF → category 記錄：8 類別 × 15 時期 = **120 筆**
- 每年 PDF → KPI 記錄：5 KPI × 15 時期 = **75 筆**
- 5 年合計：~975 筆（含兩張表）

---

### 2.2 資料庫 Schema 設計

#### 2.2.1 `fact_kouseihi_category`

```sql
CREATE TABLE fact_kouseihi_category (
    id                      INT             IDENTITY(1,1)   PRIMARY KEY,

    -- 時間維度
    report_year             SMALLINT        NOT NULL,           -- e.g. 2025
    report_month            TINYINT         NULL,               -- 1~12; NULL 代表小計/合計期間
    period_type             NVARCHAR(8)     NOT NULL,           -- 'MONTHLY'|'H1'|'H2'|'ANNUAL'

    -- 商品類別
    category                NVARCHAR(30)    NOT NULL,           -- 使用代碼, e.g. 'GIFT_900_DOWN'

    -- 核心指標
    sales_result            DECIMAL(18,0)   NULL,               -- 賣上（TWD）
    sales_yoy_pct           DECIMAL(7,1)    NULL,               -- 前年比（%）
    composition_curr_pct    DECIMAL(5,1)    NULL,               -- 本年構成（%）
    composition_prev_pct    DECIMAL(5,1)    NULL,               -- 前年構成（%）

    -- ETL 後設資料
    source_file             NVARCHAR(100)   NOT NULL,
    loaded_at               DATETIME2       NOT NULL DEFAULT GETDATE(),

    CONSTRAINT uq_kouseihi_category
        UNIQUE (report_year, report_month, period_type, category),
    CONSTRAINT chk_kouseihi_period_type
        CHECK (period_type IN ('MONTHLY', 'H1', 'H2', 'ANNUAL')),
    CONSTRAINT chk_kouseihi_category
        CHECK (category IN ('GRAM_COOKIES',
                            'GIFT_760_DOWN','GIFT_760_UP',
                            'GIFT_850_DOWN','GIFT_850_UP',
                            'GIFT_900_DOWN','GIFT_900_UP',
                            'GIFT_5000_UP','DRY_CAKE','FB','OTHER','TOTAL'))
);
```

#### 2.2.2 `fact_kouseihi_kpi`

```sql
CREATE TABLE fact_kouseihi_kpi (
    id                      INT             IDENTITY(1,1)   PRIMARY KEY,

    -- 時間維度
    report_year             SMALLINT        NOT NULL,
    report_month            TINYINT         NULL,
    period_type             NVARCHAR(8)     NOT NULL,

    -- 客數
    customer_count          INT             NULL,
    customer_yoy_pct        DECIMAL(7,1)    NULL,

    -- 客單價
    unit_price              DECIMAL(10,0)   NULL,
    unit_price_yoy_pct      DECIMAL(7,1)    NULL,

    -- 週轉率
    turnover_curr           DECIMAL(4,1)    NULL,
    turnover_prev           DECIMAL(4,1)    NULL,

    -- 月銷售日數
    day_in_month_curr       SMALLINT        NULL,
    day_in_month_prev       SMALLINT        NULL,

    -- 日平均銷售
    avg_daily_sales         DECIMAL(14,0)   NULL,
    avg_daily_sales_yoy_pct DECIMAL(7,1)    NULL,

    -- ETL 後設資料
    source_file             NVARCHAR(100)   NOT NULL,
    loaded_at               DATETIME2       NOT NULL DEFAULT GETDATE(),

    CONSTRAINT uq_kouseihi_kpi
        UNIQUE (report_year, report_month, period_type),
    CONSTRAINT chk_kouseihi_kpi_period
        CHECK (period_type IN ('MONTHLY', 'H1', 'H2', 'ANNUAL'))
);
```

#### 2.2.3 `etl_kouseihi_log`

```sql
CREATE TABLE etl_kouseihi_log (
    log_id          INT             IDENTITY(1,1)   PRIMARY KEY,
    source_file     NVARCHAR(100)   NOT NULL,
    report_year     SMALLINT        NOT NULL,
    category_rows   INT             NOT NULL DEFAULT 0,
    kpi_rows        INT             NOT NULL DEFAULT 0,
    status          NVARCHAR(20)    NOT NULL,   -- 'SUCCESS'|'FAILED'|'SKIPPED'
    error_message   NVARCHAR(MAX)   NULL,
    run_at          DATETIME2       NOT NULL DEFAULT GETDATE()
);
```

#### 2.2.4 PowerBI Views

```sql
-- 月度商品類別銷售（不含小計/合計，僅月別資料）
CREATE OR ALTER VIEW vw_kouseihi_monthly_category AS
SELECT
    report_year,
    report_month,
    category,
    sales_result,
    sales_yoy_pct,
    composition_curr_pct,
    composition_prev_pct
FROM fact_kouseihi_category
WHERE period_type = 'MONTHLY';

-- 年度合計（全年彙總，含 KPI）
CREATE OR ALTER VIEW vw_kouseihi_annual AS
SELECT
    c.report_year,
    c.category,
    c.sales_result          AS annual_sales,
    c.sales_yoy_pct         AS annual_yoy_pct,
    c.composition_curr_pct,
    k.customer_count        AS annual_customers,
    k.unit_price            AS annual_unit_price,
    k.avg_daily_sales
FROM fact_kouseihi_category c
LEFT JOIN fact_kouseihi_kpi k
       ON k.report_year  = c.report_year
      AND k.period_type  = 'ANNUAL'
WHERE c.period_type = 'ANNUAL';

-- H1/H2 對比
CREATE OR ALTER VIEW vw_kouseihi_half_year AS
SELECT
    report_year,
    period_type,
    category,
    sales_result,
    sales_yoy_pct
FROM fact_kouseihi_category
WHERE period_type IN ('H1', 'H2');
```

#### 2.2.5 索引

```sql
CREATE INDEX ix_kouseihi_cat_year_month
    ON fact_kouseihi_category (report_year, report_month, period_type)
    INCLUDE (category, sales_result, sales_yoy_pct);

CREATE INDEX ix_kouseihi_kpi_year
    ON fact_kouseihi_kpi (report_year, period_type)
    INCLUDE (customer_count, unit_price, avg_daily_sales);
```

---

### 2.3 ETL 管線設計

#### 2.3.1 模組架構

```
kouseihi/                     ← 新建套件目錄（仿照 etl/ 結構）
  __init__.py
  pdf_parser.py               ← pdfplumber 解析，回傳結構化 dict
  transformer.py              ← 驗證、正規化、轉 DataFrame
  loader.py                   ← MERGE 寫入 SQL Server，記錄 etl_kouseihi_log
main_kouseihi.py              ← CLI 入口點
db/
  schema_kouseihi.sql         ← 新增三張表 + Views 的 DDL
  schema_kouseihi_indexes.sql ← 索引定義
```

#### 2.3.2 `pdf_parser.py` 設計規格

**公開 API**

```python
def parse_pdf(pdf_path: str | Path) -> dict:
    """
    解析單份 KOUSEIHI PDF。
    回傳 {
        'report_year': int,
        'source_file': str,
        'categories': list[dict],   # 120 筆 category records
        'kpis': list[dict],         # 75 筆 KPI records
    }
    """
```

**解析邏輯**

1. **年份擷取**：從檔名 `YYYYMM-KOUSEIHI Company.pdf` 解析 `report_year = int(YYYY)`
2. **表格擷取**：用 `pdfplumber` 以 `"lines"` strategy 擷取第 1 頁全部表格列
3. **資料列識別**：過濾標頭列（含 "月" 字樣或非數值列）
4. **類別區塊切割**：
   - 共 8 個類別，每類別 4 列（賣上、前年比、本年構成、前年構成）
   - 前 32 列（8×4）= 主表類別資料
   - 後續列 = KPI 資料區
5. **時間欄對應**：按固定欄順序（索引 0~14）對應月份，使用以下 mapping：

```python
PERIOD_MAP = [
    (1,  'MONTHLY'),   # 1月
    (2,  'MONTHLY'),   # 2月
    (3,  'MONTHLY'),   # 3月
    (4,  'MONTHLY'),   # 4月
    (5,  'MONTHLY'),   # 5月
    (6,  'MONTHLY'),   # 6月
    (None, 'H1'),      # 上期
    (7,  'MONTHLY'),   # 7月
    (8,  'MONTHLY'),   # 8月
    (9,  'MONTHLY'),   # 9月
    (10, 'MONTHLY'),   # 10月
    (11, 'MONTHLY'),   # 11月
    (12, 'MONTHLY'),   # 12月
    (None, 'H2'),      # 下期
    (None, 'ANNUAL'),  # 合計
]
```

6. **類別名稱正規化**：

```python
CATEGORY_NORMALIZE = {
    'GRAM COOKIES':  'GRAM_COOKIES',
    'GIFT 760↓':     'GIFT_760_DOWN',
    'GIFT 760↑':     'GIFT_760_UP',
    'GIFT 850↓':     'GIFT_850_DOWN',
    'GIFT 850↑':     'GIFT_850_UP',
    'GIFT 900↓':     'GIFT_900_DOWN',
    'GIFT 900↑':     'GIFT_900_UP',
    'GIFT\n760↓':    'GIFT_760_DOWN',   # merged-cell variant
    'GIFT\n760↑':    'GIFT_760_UP',
    'GIFT\n850↓':    'GIFT_850_DOWN',
    'GIFT\n850↑':    'GIFT_850_UP',
    'GIFT\n900↓':    'GIFT_900_DOWN',
    'GIFT\n900↑':    'GIFT_900_UP',
    'GIFT 5000↑':    'GIFT_5000_UP',
    'GIFT\n5000↑':   'GIFT_5000_UP',
    'DRY CAKE':      'DRY_CAKE',
    'F&B':           'FB',
    'OTHER':         'OTHER',
    'TOTAL':         'TOTAL',
}
```

7. **KPI 區塊解析**：第 33 列起，每 KPI 有 2 列（本年、前年/前年比），按 KPI 名稱識別行首（`CUSTOMER`, `CUS UNIT`, `TURNOVER`, `DAY IN`, `AVERAGE`）

**回傳格式（category record）**

```python
{
    'report_year':          int,
    'report_month':         int | None,
    'period_type':          str,        # 'MONTHLY'|'H1'|'H2'|'ANNUAL'
    'category':             str,        # 正規化代碼
    'sales_result':         float | None,
    'sales_yoy_pct':        float | None,
    'composition_curr_pct': float | None,
    'composition_prev_pct': float | None,
    'source_file':          str,
}
```

**回傳格式（KPI record）**

```python
{
    'report_year':              int,
    'report_month':             int | None,
    'period_type':              str,
    'customer_count':           int | None,
    'customer_yoy_pct':         float | None,
    'unit_price':               float | None,
    'unit_price_yoy_pct':       float | None,
    'turnover_curr':            float | None,
    'turnover_prev':            float | None,
    'day_in_month_curr':        int | None,
    'day_in_month_prev':        int | None,
    'avg_daily_sales':          float | None,
    'avg_daily_sales_yoy_pct':  float | None,
    'source_file':              str,
}
```

#### 2.3.3 `transformer.py` 設計規格

**驗證清單**

| 驗證項目 | 通過條件 | 失敗行為 |
|---------|---------|---------|
| 類別完整性 | 每份 PDF 解析出恰好 8 個不重複類別 | `ERROR` log，停止載入 |
| 時期完整性 | 每份 PDF 每個 category 有 15 筆（12M+H1+H2+ANNUAL） | `WARNING` log，繼續 |
| sales_result 非負 | `sales_result >= 0` 或 NULL | `WARNING` log |
| YoY 合理範圍 | `0 < sales_yoy_pct < 500` | `WARNING` log，保留 |
| 構成比總和校驗 | MONTHLY 期，8 類別 `composition_curr_pct` 之 TOTAL ≈ 100（±0.5） | `WARNING` log |
| TOTAL 內部一致 | TOTAL 賣上 ≈ sum(各類別 賣上)（允差 ±1%） | `WARNING` log |
| H1/H2/ANNUAL 一致性 | ANNUAL 賣上 = H1 + H2（允差 ±1%） | `WARNING` log |

#### 2.3.4 `loader.py` 設計規格

- 冪等性：以 `etl_kouseihi_log` 的 `source_file` + `status='SUCCESS'` 判斷是否已載入
- 使用 `MERGE` 語句（同 SOKUHO 模式）
- `--force` 旗標：強制重跑（即使已成功載入）
- 事務邊界：一份 PDF 的 category 表 + KPI 表 + log 為一個 transaction

#### 2.3.5 `main_kouseihi.py` CLI 規格

```
uv run python main_kouseihi.py                    # 全部掃描，跳過已載入
uv run python main_kouseihi.py --year 2025        # 單年
uv run python main_kouseihi.py --force            # 強制重跑所有
uv run python main_kouseihi.py --dry-run          # 驗證不寫入
```

---

### 2.4 實作待辦清單

以下為 course agent 的實作順序，每項含**驗收條件**。

---

#### STEP 1：建立資料庫 Schema

**檔案**：`db/schema_kouseihi.sql`

**待辦**：
- [ ] 撰寫 `fact_kouseihi_category` DDL（包含 CONSTRAINT）
- [ ] 撰寫 `fact_kouseihi_kpi` DDL
- [ ] 撰寫 `etl_kouseihi_log` DDL
- [ ] 撰寫三個 PowerBI Views DDL
- [ ] 撰寫索引 DDL
- [ ] 在本機 SQL Server 執行並確認物件建立成功

**驗收條件**：
```sql
-- 執行後應返回 3 行
SELECT TABLE_NAME FROM INFORMATION_SCHEMA.TABLES
WHERE TABLE_NAME IN ('fact_kouseihi_category','fact_kouseihi_kpi','etl_kouseihi_log');

-- 執行後應返回 3 行
SELECT TABLE_NAME FROM INFORMATION_SCHEMA.VIEWS
WHERE TABLE_NAME IN ('vw_kouseihi_monthly_category','vw_kouseihi_annual','vw_kouseihi_half_year');
```

---

#### STEP 2：實作 `kouseihi/pdf_parser.py`

**待辦**：
- [ ] 實作 `parse_date_from_filename()`（從 `YYYYMM-` 格式取年份）
- [ ] 實作 `_extract_table_rows()`（pdfplumber 擷取全頁數值列）
- [ ] 實作 `_parse_category_block()`（切割 8 個類別 × 4 列）
- [ ] 實作 `_parse_kpi_block()`（解析底部 5 個 KPI）
- [ ] 實作 `_normalize_category()`（類別名稱正規化）
- [ ] 實作 `parse_pdf()`（組合回傳 dict）
- [ ] 對 `202512-KOUSEIHI Company.pdf` 執行並印出結果

**驗收條件**：
```
對 202512-KOUSEIHI Company.pdf 執行 parse_pdf() 應輸出：
- categories: 長度 120（8 類別 × 15 時期）
- kpis: 長度 75（5 KPI × 15 時期）
- 無任何 WARNING log 出現
- TOTAL + ANNUAL + sales_result = 377,054,372（對照 PDF 合計欄）
```

---

#### STEP 3：實作 `kouseihi/transformer.py`

**待辦**：
- [ ] 實作 `records_to_dataframes()`（轉 category_df 和 kpi_df）
- [ ] 實作所有驗證邏輯（詳見 2.3.3）
- [ ] 對全部 5 份 PDF 執行驗證，確認無 ERROR

**驗收條件**：
```
5 份 PDF 全部通過驗證，無 ERROR 級別 log
TOTAL ANNUAL sales_result 5 年對照表（人工比對 PDF 封面合計數字）：
  2021: 由 PDF 確認
  2022: 由 PDF 確認
  2023: 由 PDF 確認
  2024: 由 PDF 確認
  2025: 377,054,372
```

---

#### STEP 4：實作 `kouseihi/loader.py`

**待辦**：
- [ ] 實作 `is_already_loaded()`（查 etl_kouseihi_log）
- [ ] 實作 `load_category_df()`（MERGE into fact_kouseihi_category）
- [ ] 實作 `load_kpi_df()`（MERGE into fact_kouseihi_kpi）
- [ ] 實作 `log_result()`（寫入 etl_kouseihi_log）
- [ ] 實作 `load_file()`（整合 check → load → log，含 transaction）

**驗收條件**：
```
第一次執行：status = SUCCESS，category_rows = 120，kpi_rows = 75
第二次執行（不加 --force）：status = SKIPPED，rows = 0
加上 --force 重跑：status = SUCCESS，資料庫無重複列
查詢 fact_kouseihi_category：COUNT(*) = 120（單年）
```

---

#### STEP 5：實作 `main_kouseihi.py`

**待辦**：
- [ ] 實作 CLI（argparse）：支援 `--year`、`--force`、`--dry-run`
- [ ] 實作 PDF 資料夾掃描邏輯
- [ ] 整合 parser → transformer → loader 管線
- [ ] 加入彩色 console log 輸出（SUCCESS / SKIPPED / FAILED）

**驗收條件**：
```bash
# 全量跑 5 年，應全部 SUCCESS
uv run python main_kouseihi.py

# 再跑一次，應全部 SKIPPED
uv run python main_kouseihi.py

# Dry-run 不應寫入任何記錄
uv run python main_kouseihi.py --dry-run

# 查詢資料庫
SELECT COUNT(*) FROM fact_kouseihi_category;  -- 應 = 600（5年×120）
SELECT COUNT(*) FROM fact_kouseihi_kpi;        -- 應 = 375（5年×75）
SELECT status, COUNT(*) FROM etl_kouseihi_log GROUP BY status;  -- 應全為 SUCCESS
```

---

### 2.5 測試與驗收規格（任務一）

#### T1-1 單一 PDF 解析正確性

對 `202512-KOUSEIHI Company.pdf` 逐一驗證以下數值（與 PDF 人工比對）：

| 驗證項目 | 預期值 | 來源 |
|---------|--------|------|
| TOTAL ANNUAL sales_result | 377,054,372 | PDF 合計欄 |
| TOTAL H1 sales_result | 150,860,163 | PDF 上期欄 |
| TOTAL H2 sales_result | 226,194,209 | PDF 下期欄 |
| TOTAL 1月 sales_result | 42,079,182 | PDF 1月欄 |
| GIFT_5000_UP ANNUAL sales_result | 235,261,468 | PDF 合計欄 |
| TOTAL ANNUAL customer_count | 281,985 | PDF KPI 區 |
| TOTAL ANNUAL unit_price | 1,337 | PDF KPI 區 |
| TOTAL H1 sales_yoy_pct | 109.8 | PDF 前年比欄 |

#### T1-2 五年資料一致性

```sql
-- 5 年都應有資料
SELECT report_year, COUNT(*) as rows
FROM fact_kouseihi_category
WHERE period_type = 'ANNUAL' AND category = 'TOTAL'
GROUP BY report_year
ORDER BY report_year;
-- 期待：2021~2025 各 1 列

-- 各年 TOTAL ANNUAL 應大於 0
SELECT report_year, sales_result
FROM fact_kouseihi_category
WHERE period_type = 'ANNUAL' AND category = 'TOTAL'
ORDER BY report_year;
```

#### T1-3 冪等性測試

```bash
# 連跑 3 次，資料庫筆數不增加
uv run python main_kouseihi.py --force
uv run python main_kouseihi.py --force
uv run python main_kouseihi.py --force
# 查詢：COUNT(*) 應固定為 600
```

#### T1-4 Dry-run 測試

```bash
uv run python main_kouseihi.py --dry-run
# 查詢 etl_kouseihi_log：不應有任何新 log 記錄
```

---

## 3. 任務二：禮盒類別相關性分析

### 3.0 分析聚焦說明

**分析範圍**：僅針對 KOUSEIHI 中屬於「GIFT」的類別進行深度相關性分析，其他類別（GRAM COOKIES、DRY CAKE、F&B、OTHER）暫不納入本次預測模型。

**分析依據**：GIFT 系列合計占公司年度總銷售約 **70~80%**（各年稍異，可從 `fact_kouseihi_category` 的 `composition_curr_pct` 驗證），是影響年度營收最關鍵的商品線。

**四個分析物件**：

| 分析群 ID | 組成 | 分類基準 | 說明 |
|---------|------|---------|------|
| `GIFT_LOW` | 年度低牌價禮盒 | **商品牌價**（各年門檻見 3.1） | 單品定價在門檻以下 |
| `GIFT_HIGH` | 年度高牌價禮盒 | **商品牌價**（門檻至 5000 TWD） | 單品定價在門檻以上、5000 以下 |
| `GIFT_COMBINED` | `GIFT_LOW` + `GIFT_HIGH` | — | 低牌價 + 高牌價的「不分群」禮盒銷售合計 |
| `GIFT_LARGE` | `GIFT_5000_UP` | **整筆訂單總額** | 單次交易總金額 ≥ 5000 TWD 的「大單」，與個別商品牌價無關 |

> **分類邏輯說明**：
> - `GIFT_LOW` / `GIFT_HIGH` 反映的是**消費者選購哪個價位的商品**，由商品牌價決定。
> - `GIFT_LARGE` 反映的是**單次採購行為的規模**：無論是買一件高價品或多件中低價品，只要一筆訂單總額達 5000 TWD 就歸入此類，業務上俗稱「大單」。
> - `GIFT_COMBINED` 排除大單，僅合計按牌價分類的兩個群，用以觀察整體禮盒牌價市場（不區分低高端門檻）的外部驅動力。

---

### 3.1 禮盒類別正規化策略

#### 3.1.1 年度牌價帶演進（GIFT_LOW / GIFT_HIGH）

> `GIFT_LARGE`（GIFT_5000_UP）的分類基準為**整筆訂單總額**，不受牌價門檻調整影響，5 年定義一致。

| 年份 | 低牌價（GIFT_LOW） | 高牌價（GIFT_HIGH） | 牌價門檻調整幅度 |
|------|-----------------|------------------|--------------| 
| 2021 | GIFT_760_DOWN（單品牌價 ≤760） | GIFT_760_UP（760< 牌價 ≤5000） | 基準年 |
| 2022 | GIFT_760_DOWN（單品牌價 ≤760） | GIFT_760_UP（760< 牌價 ≤5000） | 未調整 |
| 2023 | GIFT_850_DOWN（單品牌價 ≤850） | GIFT_850_UP（850< 牌價 ≤5000） | +12%（760→850） |
| 2024 | GIFT_900_DOWN（單品牌價 ≤900） | GIFT_900_UP（900< 牌價 ≤5000） | +6%（850→900） |
| 2025 | GIFT_900_DOWN（單品牌價 ≤900） | GIFT_900_UP（900< 牌價 ≤5000） | 未調整 |

> **重要**：牌價門檻調漲反映通貨膨脹與原料成本上升，跨年比較時須將「結構性斷點」納入特徵，而非視為資料錯誤。2023 年 760→850（+12%）調漲會造成 GIFT_LOW 銷售金額的人為跳升（相同銷售量對應更高金額），須在模型中以 `price_floor_normalized` 特徵明確控制。

#### 3.1.2 `dim_gift_category_mapping`（正規化映射表）

```sql
CREATE TABLE dim_gift_category_mapping (
    id                  INT             IDENTITY(1,1)   PRIMARY KEY,
    year_from           SMALLINT        NOT NULL,
    year_to             SMALLINT        NOT NULL,
    raw_category        NVARCHAR(30)    NOT NULL,
    canonical_group     NVARCHAR(20)    NOT NULL,   -- 'GIFT_LOW'|'GIFT_HIGH'|'GIFT_LARGE'
    price_floor         DECIMAL(8,0)    NOT NULL,   -- 區間下限（含）
    price_ceiling       DECIMAL(8,0)    NULL,        -- 區間上限（含，NULL=無上限）
    threshold_note      NVARCHAR(100)   NULL,        -- 備注說明

    CONSTRAINT uq_gift_map UNIQUE (year_from, year_to, raw_category),
    CONSTRAINT chk_canonical_group
        CHECK (canonical_group IN ('GIFT_LOW', 'GIFT_HIGH', 'GIFT_LARGE'))
);
```

**Seed 資料（7 列）**—需由 `db/seed_gift_mapping.sql` 植入：

| year_from | year_to | raw_category | canonical_group | price_floor | price_ceiling |
|-----------|---------|-------------|----------------|-------------|---------------|
| 2021 | 2022 | GIFT_760_DOWN | GIFT_LOW | 0 | 760 |
| 2021 | 2022 | GIFT_760_UP | GIFT_HIGH | 761 | 5000 |
| 2023 | 2023 | GIFT_850_DOWN | GIFT_LOW | 0 | 850 |
| 2023 | 2023 | GIFT_850_UP | GIFT_HIGH | 851 | 5000 |
| 2024 | 2025 | GIFT_900_DOWN | GIFT_LOW | 0 | 900 |
| 2024 | 2025 | GIFT_900_UP | GIFT_HIGH | 901 | 5000 |
| 2021 | 2025 | GIFT_5000_UP | GIFT_LARGE | 5001 | NULL |

#### 3.1.3 正規化 View 設計

**`vw_gift_canonical_monthly`**（三群個別分析用）

```sql
CREATE OR ALTER VIEW vw_gift_canonical_monthly AS
SELECT
    k.report_year,
    k.report_month,
    k.period_type,
    m.canonical_group,
    m.price_floor       AS threshold_floor,
    m.price_ceiling     AS threshold_ceiling,
    k.sales_result,
    k.sales_yoy_pct,
    k.composition_curr_pct,
    k.composition_prev_pct,
    k.source_file
FROM fact_kouseihi_category k
JOIN dim_gift_category_mapping m
  ON k.category = m.raw_category
 AND k.report_year BETWEEN m.year_from AND m.year_to;
```

**`vw_gift_combined_monthly`**（GIFT_COMBINED 合計用）

```sql
CREATE OR ALTER VIEW vw_gift_combined_monthly AS
SELECT
    report_year,
    report_month,
    period_type,
    'GIFT_COMBINED'             AS canonical_group,
    SUM(sales_result)           AS sales_result,
    NULL                        AS sales_yoy_pct,   -- 由 Python 計算加權 YoY
    SUM(composition_curr_pct)   AS composition_curr_pct,
    SUM(composition_prev_pct)   AS composition_prev_pct
FROM vw_gift_canonical_monthly
WHERE canonical_group IN ('GIFT_LOW', 'GIFT_HIGH')
GROUP BY report_year, report_month, period_type;
```

> `sales_yoy_pct` 在此 View 設為 NULL，由 Python 分析腳本計算：`combined_yoy = 本年合計 / 前年合計 × 100`，以避免錯誤的加權平均。

---

### 3.2 外部總體經濟指標規格

#### 3.2.1 指標清單（14 項，禮盒分析專用）

按各分析群相關性標記（★★★ = 高度相關，★★ = 中度，★ = 參考）：

> GIFT_LOW / GIFT_HIGH 驅動力來自**個人消費牌價偏好**；GIFT_LARGE 驅動力來自**整筆訂單規模**（企業/團體大量採購行為）。

| # | 指標名 | GIFT_LOW | GIFT_HIGH | GIFT_LARGE（大單）| 機構 | 說明 |
|---|--------|---------|---------|-----------|------|------|
| 1 | 百貨公司+購物中心月銷售額 | ★★★ | ★★★ | ★★ | 主計處 | 最直接的競業通路指標 |
| 2 | 零售業食品飲料類指數 | ★★★ | ★★ | ★ | 主計處 | 類似商品市場規模 |
| 3 | 消費者信心指數（CCI） | ★★★ | ★★★ | ★★ | 台大 RCEC | 消費者整體信心 |
| 4 | CPI 總指數年增率 | ★★ | ★★ | ★ | 主計處 | 整體物價壓力 |
| 5 | CPI 食品飲料類年增率 | ★★★ | ★★ | ★ | 主計處 | 禮盒原料成本 |
| 6 | 受雇員工平均薪資 YoY | ★★ | ★★★ | ★★ | 主計處 | 薪資成長影響購買力 |
| 7 | 失業率 | ★★★ | ★★ | ★★ | 主計處 | 就業穩定性 |
| 8 | TWD/JPY 月均匯率 | ★ | ★★★ | ★★ | 台灣銀行 | 日系高價禮品進口成本 |
| 9 | TWD/USD 月均匯率 | ★ | ★★ | ★★ | 台灣銀行 | 進口原料成本 |
| 10 | 入境旅客人數 | ★★ | ★★★ | ★★ | 交通部觀光局 | 觀光客購禮行為 |
| 11 | 工商景氣信心指數（BSI） | ★ | ★★ | ★★★ | 工商協進會 | 企業採購大額禮盒 |
| 12 | 農曆春節旗標 | ★★★ | ★★★ | ★★★ | 自建 | 最大節日效應 |
| 13 | 中秋節旗標 | ★★★ | ★★★ | ★★★ | 自建 | 第二大禮盒節日 |
| 14 | 月工作天數 | ★★ | ★★ | ★★ | 人事行政總處 | 門市營業機會數 |

#### 3.2.2 `dim_macro_indicators` Schema（含全部 14 項）

```sql
CREATE TABLE dim_macro_indicators (
    id                      INT             IDENTITY(1,1)   PRIMARY KEY,
    report_year             SMALLINT        NOT NULL,
    report_month            TINYINT         NOT NULL,

    -- [1][2] 通路指標
    dept_store_sales        DECIMAL(18,0)   NULL,  -- 百貨公司+購物中心月銷售額（千元）
    retail_food_index       DECIMAL(8,2)    NULL,  -- 零售業食品飲料類指數

    -- [3] 消費信心
    cci_index               DECIMAL(8,2)    NULL,  -- 消費者信心指數（台大 RCEC）

    -- [4][5] 物價
    cpi_yoy_pct             DECIMAL(6,2)    NULL,  -- CPI 總指數年增率（%）
    cpi_food_yoy_pct        DECIMAL(6,2)    NULL,  -- CPI 食品飲料類年增率（%）

    -- [6][7] 薪資與就業
    avg_wage_yoy_pct        DECIMAL(6,2)    NULL,  -- 受雇員工平均薪資年增率（%）
    unemployment_rate       DECIMAL(5,2)    NULL,  -- 失業率（%）

    -- [8][9] 匯率
    twd_jpy_rate            DECIMAL(8,4)    NULL,  -- TWD/JPY 月均
    twd_usd_rate            DECIMAL(8,4)    NULL,  -- TWD/USD 月均

    -- [10] 觀光
    inbound_tourists        INT             NULL,  -- 入境旅客人數（人次）

    -- [11] 企業景氣（季別插值）
    bsi_index               DECIMAL(6,2)    NULL,  -- 工商景氣信心指數（>50=擴張）

    -- [12][13] 農曆行事曆
    has_lunar_new_year      BIT             NOT NULL DEFAULT 0,
    lunar_new_year_day      TINYINT         NULL,   -- 春節落在幾號（NULL=當月無春節）
    has_mid_autumn          BIT             NOT NULL DEFAULT 0,
    mid_autumn_day          TINYINT         NULL,   -- 中秋落在幾號

    -- [14] 工作天
    working_days            TINYINT         NULL,
    calendar_days           TINYINT         NULL,

    data_source             NVARCHAR(500)   NULL,
    updated_at              DATETIME2       NOT NULL DEFAULT GETDATE(),

    CONSTRAINT uq_macro_year_month UNIQUE (report_year, report_month)
);
```

#### 3.2.3 歷史資料收集指南（2021~2025，60 個月）

所有原始資料統一存放於 `data/macro_raw/`，格式為 `year,month,value`。

| # | CSV 檔名 | 資料機構 | 取得步驟摘要 |
|---|---------|---------|------------|
| 1 | `dept_store_sales.csv` | 主計處 | 「工業及服務業調查」→「批發零售及餐飲業統計」→「百貨公司及購物中心營業額」月別 Excel |
| 2 | `retail_food_index.csv` | 主計處 | 同上，選「食品飲料類」細項 |
| 3 | `cci.csv` | 台大國發所 RCEC | 搜尋「台大消費者信心指數」，官網有歷史資料下載頁 |
| 4 | `cpi_total.csv` | 主計處 | 政府資料開放平臺搜尋「消費者物價指數月別資料」CSV |
| 5 | `cpi_food.csv` | 主計處 | 同上，選取「食品飲料及菸草」次類指數 YoY |
| 6 | `avg_wage_yoy.csv` | 主計處 | 政府資料開放平臺搜尋「工業及服務業薪資統計」月別；自行計算 YoY |
| 7 | `unemployment.csv` | 主計處 | 政府資料開放平臺搜尋「人力資源調查統計月別」 |
| 8 | `twd_jpy.csv` | 台灣銀行 | 「外匯牌告匯率歷史查詢」→每月計算均值 |
| 9 | `twd_usd.csv` | 台灣銀行 | 同上 |
| 10 | `inbound_tourists.csv` | 交通部觀光局 | 「觀光局統計資料庫」→「來台旅客統計」月別 CSV |
| 11 | `bsi.csv` | 台灣工商協進會 | 搜尋「工商景氣信心調查 BSI」；每季發布，月別以同季數值填入 |
| 12~13 | `lunar_calendar.csv` | 自動生成 | Python `lunardate` 套件計算春節（農曆正月初一）與中秋（農曆八月十五）陽曆日期 |
| 14 | `working_days.csv` | 人事行政總處 | 「政府行政機關辦公日曆表」年度 JSON；計算各月工作天數（扣除假日補班） |

**注意事項**：
- 入境旅客 2021~2022 因 COVID 邊境管制，數值接近 0，為正常現象
- BSI 為季度調查，同季三個月填入相同值（季別插值）
- 農曆春節月份：預期 2021/2、2022/2、2023/1、2024/2、2025/1

---

### 3.3 分析資料集整合 View

#### 3.3.1 `vw_gift_analysis_dataset`（核心分析 View）

```sql
CREATE OR ALTER VIEW vw_gift_analysis_dataset AS
-- 三個個別群（LOW / HIGH / LARGE）
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
    -- 外部指標（14 項）
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
    m.calendar_days
FROM vw_gift_canonical_monthly g
LEFT JOIN dim_macro_indicators m
       ON m.report_year  = g.report_year
      AND m.report_month = g.report_month
WHERE g.period_type = 'MONTHLY'

UNION ALL

-- GIFT_COMBINED（合計群）
SELECT
    c.report_year,
    c.report_month,
    c.canonical_group,
    c.sales_result,
    NULL        AS sales_yoy_pct,      -- Python 側計算
    c.composition_curr_pct,
    c.composition_prev_pct,
    NULL        AS threshold_floor,
    NULL        AS threshold_ceiling,
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
    m.calendar_days
FROM vw_gift_combined_monthly c
LEFT JOIN dim_macro_indicators m
       ON m.report_year  = c.report_year
      AND m.report_month = c.report_month
WHERE c.period_type = 'MONTHLY';
```

#### 3.3.2 資料量估計

| 分析群 | 月度筆數（5年） |
|--------|--------------|
| GIFT_LOW | 60 |
| GIFT_HIGH | 60 |
| GIFT_LARGE | 60 |
| GIFT_COMBINED | 60 |
| **合計** | **240** |

---

### 3.4 四群分析架構

#### 3.4.1 相關性假說矩陣

分析前先設定假說，驗收時以實際相關係數方向確認：

> **欄位說明**：GIFT_LOW / GIFT_HIGH 受個人消費牌價偏好驅動；GIFT_LARGE 受**整筆採購行為規模**驅動（企業團購、節日大量採購），與牌價高低無直接關係。

| 外部指標 | GIFT_LOW | GIFT_HIGH | GIFT_COMBINED | GIFT_LARGE（大單行為）|
|---------|---------|---------|--------------|---------------------|
| 百貨公司銷售額 | 正向 | 正向 | 正向 | 正向（大單多在百貨通路）|
| 消費者信心（CCI） | 正向 | 正向 | 正向 | **弱正向**（大單由企業主導，CCI 代表個人）|
| CPI 食品 YoY | 負向（購買力↓）| 弱負向 | 負向 | 中性（企業採購對物價較不敏感）|
| 平均薪資 YoY | 正向 | 強正向 | 正向 | 弱正向（薪資影響個人購買力，對大單影響較小）|
| 失業率 | 負向 | 弱負向 | 負向 | **弱相關**（企業採購不受個人失業影響）|
| TWD/JPY 匯率 | 弱相關 | 負向（日貨進口貴）| 弱負向 | 弱負向 |
| 入境旅客 | 中性 | 正向（觀光客個人購禮）| 弱正向 | **弱正向**（旅遊團體大單）|
| BSI 景氣信心 | 弱正向 | 正向 | 正向 | **強正向**（企業景氣↑→企業採購大單↑）|
| 春節月份旗標 | **強正向** | **強正向** | **強正向** | **強正向**（春節企業員工禮、客戶禮→大單集中）|
| 中秋月份旗標 | **強正向** | **強正向** | **強正向** | **強正向**（中秋企業採購禮盒→大單集中）|

#### 3.4.2 分析流程（6 階段）

```
Phase 1：資料準備
  1a. 正規化 Schema + Seed Data（STEP 6）
  1b. 外部指標 CSV 收集（STEP 7）
  1c. 外部指標匯入 SQL（STEP 8）
  1d. 整合 View 建立（STEP 9）

Phase 2：探索性分析（EDA）
  2a. 四群月度時序圖（2021~2025，標示春節/中秋）
  2b. 門檻調漲影響視覺化（2023、2024 斷點）
  2c. STL 季節性分解（各群分別）
  2d. 四群 YoY 趨勢對比圖

Phase 3：相關性分析（核心）
  3a. Pearson + Spearman 相關矩陣（四群 vs 14 項指標）
  3b. Lag 相關分析（t-0, t-1, t-2, t-3 落後效應）
  3c. 偏相關分析（控制春節/中秋後的淨效應）
  3d. 四群並列比較熱圖（同指標、四群相關係數對比）

Phase 4：特徵工程
  4a. Lag features（前 1/3/12 個月銷售）
  4b. Rolling mean（3M、6M）
  4c. 行事曆編碼（月份 sin/cos、春節/中秋旗標）
  4d. 門檻正規化特徵（price_floor 標準化）
  4e. 跨群比例特徵（LOW/HIGH 比值、LARGE 佔 COMBINED 比）

Phase 5：特徵重要性與預測模型
  5a. Random Forest（四群分別建模）
  5b. OLS 迴歸（輸出係數與 p-value）
  5c. TimeSeriesSplit 交叉驗證（n_splits=3）
  5d. 2025 測試集評估（MAPE）

Phase 6：彙整報告
  6a. 各群關鍵因子排行
  6b. 高峰銷售月份識別與節日效應量化
  6c. 門檻調漲影響結論
  6d. PowerBI View 交付
```

#### 3.4.3 產出物清單

| 輸出物 | 路徑 | 說明 |
|-------|------|------|
| 四群相關係數熱圖 | `outputs/corr_heatmap_4groups.png` | 14 指標 × 4 群，含顯著性標記 |
| 四群 STL 分解圖 | `outputs/stl_{group}.png` | 各群 1 張 |
| Lag 相關圖 | `outputs/lag_corr_{group}.png` | 各群分別 |
| 特徵重要性圖 | `outputs/feature_importance_{group}.png` | 各群分別 |
| OLS 摘要 | `outputs/ols_{group}.txt` | 含係數與 p-value |
| 門檻斷點分析 | `outputs/threshold_impact.png` | 2023/2024 調漲前後比較 |
| 分析報告 | `docs/analysis_report.md` | 完整文字報告 |
| PowerBI Views | `db/views_analysis_powerbi.sql` | 3 個 View |

---

### 3.5 預測模型設計

#### 3.5.1 目標變數（四群各自建立模型）

| 模型 ID | 預測目標 | 類型 |
|---------|---------|------|
| M1_LOW | GIFT_LOW 月銷售額 | 回歸 |
| M2_HIGH | GIFT_HIGH 月銷售額 | 回歸 |
| M3_COMBINED | GIFT_COMBINED 月銷售額 | 回歸 |
| M4_LARGE | GIFT_LARGE 月銷售額 | 回歸 |
| M5_PEAK | 各群年度前 3 高峰月份識別 | 多標籤分類 |

#### 3.5.2 特徵集

```
通用特徵（四群共用）：
  行事曆：
    month_sin, month_cos           # 月份週期編碼（sin/cos）
    has_lunar_new_year             # 春節旗標
    lunar_new_year_day             # 春節日期（月內位置）
    has_mid_autumn                 # 中秋旗標
    lead_1_lunar_new_year          # 下月是否有春節（提前備貨效應）
    working_days, calendar_days

  外部經濟特徵：
    dept_store_sales_yoy           # 百貨公司銷售 YoY（自行計算）
    retail_food_index
    cci_index, lag_cci_1m          # CCI 及落後 1 月版本
    cpi_food_yoy_pct
    avg_wage_yoy_pct
    unemployment_rate
    twd_jpy_rate, twd_usd_rate
    inbound_tourists
    bsi_index, lag_bsi_1m          # BSI 及落後 1 月版本

  歷史銷售特徵（各群自己的 lag）：
    sales_lag_1m                   # 前 1 個月銷售
    sales_lag_3m                   # 前 3 個月銷售
    sales_lag_12m                  # 前年同月銷售
    sales_rolling_3m_mean          # 3 個月滾動均值
    sales_rolling_6m_mean          # 6 個月滾動均值

  結構性特徵：
    price_floor_normalized         # 當年門檻下限標準化（處理調漲斷點）

群特有特徵：
  GIFT_LOW:    low_high_ratio     （LOW 佔 LOW+HIGH 的比例）
  GIFT_HIGH:   twd_jpy_lag_1m    （日幣匯率落後 1 月）
  GIFT_LARGE:  bsi_lag_1m        （BSI 落後效應對企業採購更顯著）
  GIFT_COMBINED: large_share     （LARGE 佔總 GIFT 比例）
```

#### 3.5.3 模型清單與評估

| 模型 | 用途 | 評估指標 |
|------|------|---------|
| Random Forest | 預測 + 特徵重要性 | MAPE、R² |
| XGBoost | 對比基準 | MAPE、R² |
| OLS（statsmodels） | 可解釋性係數分析 | R²、p-value |

訓練/驗證切割：
- 訓練集：2021~2023（36 個月）
- 驗證集：2024（12 個月）
- 測試集：2025（12 個月）— 最終評估，保留不碰

---

### 3.6 實作待辦清單

---

#### STEP 6：禮盒類別正規化 Schema 與 Seed Data

**檔案**：`db/schema_analysis.sql`（新增 `dim_gift_category_mapping` DDL）、`db/seed_gift_mapping.sql`

**待辦**：
- [ ] 撰寫 `dim_gift_category_mapping` DDL
- [ ] 撰寫 7 列 Seed INSERT 語句（`db/seed_gift_mapping.sql`）
- [ ] 在 SQL Server 執行，確認 7 列資料正確
- [ ] 撰寫 `vw_gift_canonical_monthly` View DDL
- [ ] 撰寫 `vw_gift_combined_monthly` View DDL

**驗收條件**：
```sql
-- Seed 正確：7 列
SELECT COUNT(*) FROM dim_gift_category_mapping;  -- 應 = 7

-- 各群月別資料完整（月度，5年 × 12月）
SELECT canonical_group, COUNT(*) AS months
FROM vw_gift_canonical_monthly
WHERE period_type = 'MONTHLY'
GROUP BY canonical_group;
-- 應：GIFT_LOW=60, GIFT_HIGH=60, GIFT_LARGE=60

-- 門檻年份正確
SELECT DISTINCT report_year, threshold_floor, threshold_ceiling
FROM vw_gift_canonical_monthly
WHERE canonical_group = 'GIFT_LOW' AND period_type = 'MONTHLY'
ORDER BY report_year;
-- 期待：2021→0~760, 2022→0~760, 2023→0~850, 2024→0~900, 2025→0~900

-- COMBINED = LOW + HIGH（允差 1 TWD）
SELECT COUNT(*) AS mismatch_count
FROM (
    SELECT c.report_year, c.report_month,
           ABS(c.sales_result - (l.sales_result + h.sales_result)) AS diff
    FROM vw_gift_combined_monthly c
    JOIN vw_gift_canonical_monthly l
      ON l.report_year=c.report_year AND l.report_month=c.report_month
     AND l.canonical_group='GIFT_LOW' AND l.period_type='MONTHLY'
    JOIN vw_gift_canonical_monthly h
      ON h.report_year=c.report_year AND h.report_month=c.report_month
     AND h.canonical_group='GIFT_HIGH' AND h.period_type='MONTHLY'
    WHERE c.period_type='MONTHLY'
) t WHERE diff > 1;
-- 應 = 0
```

---

#### STEP 7：外部指標 CSV 收集（人工作業）

**輸出目錄**：`data/macro_raw/`

**CSV 格式規範**：
```
year,month,value
2021,1,xxxxx
2021,2,xxxxx
...
2025,12,xxxxx
```

**待辦（每項指標一份 CSV）**：
- [ ] `dept_store_sales.csv`（百貨+購物中心月銷售額，單位：千元）
- [ ] `retail_food_index.csv`（零售業食品飲料類指數）
- [ ] `cci.csv`（消費者信心指數）
- [ ] `cpi_total.csv`（CPI 總指數年增率，%）
- [ ] `cpi_food.csv`（CPI 食品飲料類年增率，%）
- [ ] `avg_wage_yoy.csv`（平均薪資 YoY，%，需自行計算）
- [ ] `unemployment.csv`（失業率，%）
- [ ] `twd_jpy.csv`（月均匯率，台幣換 1 日圓所需台幣數）
- [ ] `twd_usd.csv`（月均匯率）
- [ ] `inbound_tourists.csv`（入境旅客人次）
- [ ] `bsi.csv`（BSI 景氣信心指數，季別資料補插為月別）
- [ ] `lunar_calendar.csv`（由腳本自動生成：春節/中秋陽曆日期）
- [ ] `working_days.csv`（各月工作天數）

**驗收條件**：
```
每份 CSV：
- 行數 = 61（含標頭），即 60 筆月度資料
- 無空值（BSI 已季別插值）
- 數值無逗號千分位、無百分比符號、無負號空格
- year 範圍 2021~2025，month 範圍 1~12

人工抽查：
- 入境旅客 2021/01 ~ 2022/06 應接近 0（邊境管制期）
- 入境旅客 2023 應大幅回升
- 春節月份：2021/2, 2022/2, 2023/1, 2024/2, 2025/1 各有 has_lunar_new_year = 1
- 中秋月份：每年 9 月或 10 月應有 has_mid_autumn = 1
```

---

#### STEP 8：外部指標 Schema 建立與資料載入腳本

**檔案**：`db/schema_macro.sql`（`dim_macro_indicators` DDL）、`scripts/load_macro.py`

**待辦**：
- [ ] 撰寫 `dim_macro_indicators` DDL（14 項指標欄位）
- [ ] 在 SQL Server 建立資料表
- [ ] 撰寫 `scripts/load_macro.py`：
  - 逐一讀取 `data/macro_raw/*.csv`
  - Pivot 成 `(year, month, 各欄位)` 格式的 DataFrame
  - MERGE into `dim_macro_indicators`（冪等）
- [ ] 農曆行事曆自動計算（`lunardate` 套件，產生 `lunar_calendar.csv`）
- [ ] 工作天數計算（讀取人事行政總處 ICS 行事曆，產生 `working_days.csv`）
- [ ] 執行載入，確認 60 筆完整

**驗收條件**：
```sql
-- 60 筆完整
SELECT COUNT(*) FROM dim_macro_indicators
WHERE report_year BETWEEN 2021 AND 2025;  -- 應 = 60

-- 關鍵欄位無 NULL（BSI 已插值）
SELECT COUNT(*) FROM dim_macro_indicators
WHERE cci_index IS NULL OR cpi_yoy_pct IS NULL
   OR avg_wage_yoy_pct IS NULL OR bsi_index IS NULL;
-- 應 = 0

-- 春節旗標（應有 5 筆）
SELECT report_year, report_month, lunar_new_year_day
FROM dim_macro_indicators
WHERE has_lunar_new_year = 1
ORDER BY report_year;
-- 預期：2021/2, 2022/2, 2023/1, 2024/2, 2025/1

-- 中秋旗標（應有 5 筆）
SELECT report_year, report_month, mid_autumn_day
FROM dim_macro_indicators
WHERE has_mid_autumn = 1
ORDER BY report_year;
-- 每年 9 月或 10 月各一筆
```

---

#### STEP 9：整合 View 建立與分析資料集輸出

**檔案**：`db/views_analysis.sql`（含 `vw_gift_analysis_dataset`）、`scripts/build_gift_dataset.py`

**待辦**：
- [ ] 撰寫 `vw_gift_analysis_dataset` View DDL（含 UNION ALL 合計群）
- [ ] 驗證 View 含 4 群 × 60 個月 = 240 列
- [ ] `scripts/build_gift_dataset.py`：
  - 查詢 View，讀取為 DataFrame
  - 計算 `GIFT_COMBINED` 的 YoY（本年合計 / 前年合計 × 100）
  - 輸出 `data/gift_analysis_dataset.csv`（240 列）

**驗收條件**：
```sql
-- View 應有 240 列（4 群 × 60 月）
SELECT canonical_group, COUNT(*) AS cnt
FROM vw_gift_analysis_dataset
GROUP BY canonical_group;
-- 各群應 = 60

-- 外部指標無缺漏（控制疫情期間旅客近零屬正常）
SELECT COUNT(*) FROM vw_gift_analysis_dataset
WHERE cci_index IS NULL OR cpi_yoy_pct IS NULL;
-- 應 = 0
```

```python
# Python 驗收
df = pd.read_csv('data/gift_analysis_dataset.csv')
assert len(df) == 240
assert df['sales_result'].notna().all()
assert set(df['canonical_group'].unique()) == {
    'GIFT_LOW', 'GIFT_HIGH', 'GIFT_LARGE', 'GIFT_COMBINED'
}
# COMBINED YoY 已計算（非 NULL）
assert df[df['canonical_group']=='GIFT_COMBINED']['sales_yoy_pct'].notna().all()
```

---

#### STEP 10：EDA 與季節性分析

**檔案**：`notebooks/01_gift_eda.ipynb`、`outputs/` 目錄

**待辦**：
- [ ] **圖 1**：四群月度銷售時序圖（2021~2025，春節/中秋月份標記）
- [ ] **圖 2**：門檻調漲影響圖：2023/01（760→850）與 2024/01（850→900）前後 GIFT_LOW 銷售金額月度折線，標示斷點
- [ ] **圖 3**：各群 STL 季節性分解（4 張子圖，Trend / Seasonal / Residual）
- [ ] **圖 4**：四群 YoY 趨勢對比（同一時間軸，4 條折線）
- [ ] **表 1**：各群月份平均銷售排行（2021~2025 年均值，識別高峰月）
- [ ] **圖 5**：GIFT_COMBINED 佔 TOTAL 銷售的年度比例趨勢（堆疊長條圖）

**驗收條件**：
```
圖 1 可識別：
  - 每年 1月（春節前）LOW/HIGH 均有明顯峰值
  - 9月（中秋前）出現第二峰值
  - GIFT_LARGE 峰值集中在 1月（企業採購）與 9月

圖 2 可識別：
  - GIFT_LOW 2023/01 出現銷售金額跳升（門檻調漲）
  - 輸出斷點前後各 6 個月的平均銷售，供量化比較

表 1 輸出：各群年均前 3 高銷售月份（2021~2025）
```

---

#### STEP 11：相關性分析（核心 Notebook）

**檔案**：`notebooks/02_gift_correlation.ipynb`

**11a：基礎相關矩陣（全時段 60 個月）**
- [ ] 計算 4 群 × 14 指標的 Pearson 相關係數矩陣
- [ ] 計算 Spearman 相關係數矩陣（抗離群值）
- [ ] 輸出四群並列比較熱圖：`outputs/corr_heatmap_4groups.png`
- [ ] 標示顯著性：`*` p<0.05，`**` p<0.01

**11b：Lag 相關分析（落後效應）**
- [ ] 計算各外部指標對各群 `sales_result` 的 lag-0、lag-1、lag-2、lag-3 相關
- [ ] 輸出各群 Lag 相關折線圖：`outputs/lag_corr_{group}.png`
- [ ] 建立「最佳預測 Lag」對照表（記錄各指標對各群的最高相關的 lag）

**11c：偏相關分析（控制節日效應後的淨相關）**
- [ ] 以 `has_lunar_new_year` + `has_mid_autumn` 作控制變數，計算偏相關
- [ ] 輸出偏相關 vs 原始相關的比較表
- [ ] 標示「扣除節日效應後仍顯著（p<0.05）」的指標

**11d：門檻調漲斷點分析**
- [ ] 分段計算（2021~2022 vs 2023~2025）GIFT_LOW 的相關係數，比較是否顯著改變
- [ ] 輸出：`outputs/threshold_impact.png`（斷點前後相關係數對比）

**驗收條件**：
```
corr_heatmap_4groups.png：
  - 顯示 14 指標 × 4 群，有顯著性標記
  - GIFT_LARGE 與 BSI 相關係數 > GIFT_LOW 與 BSI 相關係數（驗證企業採購假說）
  - 春節/中秋旗標的相關係數對所有群均為正且顯著

Lag 分析：
  - 找到各群至少 2 個指標的最佳 Lag ≠ 0（存在落後效應）

偏相關：
  - 輸出控制節日效應後，仍顯著相關的指標清單
  - 至少 2 個指標（如 CCI、百貨銷售）在偏相關中仍 p<0.05
```

---

#### STEP 12：特徵工程與預測模型

**檔案**：`notebooks/03_gift_model.ipynb`、`scripts/train_gift_models.py`

**12a：特徵建立**
- [ ] Lag features：各群 lag_1m、lag_3m、lag_12m
- [ ] Rolling mean：3M、6M
- [ ] 月份編碼：`month_sin = sin(2π×month/12)`，`month_cos = cos(2π×month/12)`
- [ ] 行事曆旗標：春節、中秋、下月春節（`lead_1_lunar_new_year`）
- [ ] `price_floor_normalized`：各年門檻下限 / 900（標準化）
- [ ] 跨群比例特徵（見 3.5.2）

**12b：模型訓練（四群各自）**
- [ ] Random Forest Regressor（n_estimators=300，TimeSeriesSplit n_splits=3）
- [ ] XGBoost Regressor（對比）
- [ ] OLS（`statsmodels`，輸出係數表）
- [ ] 輸出各群最佳模型選擇摘要

**12c：2025 測試集評估**
- [ ] 計算各群各模型的 MAPE（2025 年 12 個月）
- [ ] 輸出預測 vs 實際對比圖（各群 1 張）
- [ ] 輸出最終 MAPE 彙整表

**12d：高峰月份分類（M5_PEAK）**
- [ ] 建立各群「年度前 3 銷售月份」標籤
- [ ] 訓練分類模型（2021~2024 訓練，2025 預測）
- [ ] 計算各群高峰月份命中率

**12e：模型與輸出儲存**
- [ ] `models/gift_{group}_rf.pkl`（Random Forest）
- [ ] `outputs/feature_importance_{group}.csv`
- [ ] `outputs/feature_importance_{group}.png`
- [ ] `outputs/ols_{group}.txt`
- [ ] `outputs/prediction_vs_actual_{group}.png`

**驗收條件**：
```
MAPE 標準（2025 測試集）：
  GIFT_LOW:      < 20%（門檻調漲結構性變動大）
  GIFT_HIGH:     < 18%
  GIFT_COMBINED: < 15%（最穩定，標準最嚴）
  GIFT_LARGE:    < 25%（波動大，標準寬鬆）

OLS p-value：
  至少 3 個特徵在至少 2 個群達 p < 0.05

特徵重要性：
  GIFT_LARGE 的 BSI 相關特徵（bsi_index 或 lag_bsi_1m）應進前 5 名
  春節旗標應在全部 4 群的 RF 特徵重要性前 3 名

高峰月份命中率（前 3 名）：
  各群 2025 年前 3 高峰月份命中率 ≥ 2/3
```

---

#### STEP 13：彙整報告與 PowerBI View

**檔案**：`docs/analysis_report.md`、`db/views_analysis_powerbi.sql`

**待辦**：
- [ ] 撰寫 `docs/analysis_report.md`（見附錄 C 更新版結構）
- [ ] 建立 `vw_gift_monthly_with_macro`（PowerBI 月度分析用）
- [ ] 建立 `vw_gift_annual_summary`（PowerBI 年度比較用）
- [ ] 建立 `vw_gift_peak_calendar`（各群高峰月份預測輸入）

**驗收條件**：
```
analysis_report.md 必須包含：
  ✓ 四群前 5 大相關外部指標（含方向說明）
  ✓ 春節月份對各群的平均提振幅度（%，計算方式：春節月均值/非春節月均值）
  ✓ 中秋月份對各群的平均提振幅度（%）
  ✓ 門檻調漲量化結論（2023 調漲後 GIFT_LOW 銷售佔比 vs 2022 的變化 ppt）
  ✓ GIFT_LARGE 的 BSI 假說驗證（是否如假說為強正向相關）
  ✓ 各群 MAPE 彙整表（最低標準 / 實際達成）
  ✓ 分析限制說明（樣本數僅 5 年，BSI 為季別插值等）

PowerBI 驗收：
  - 三個 View 均可從 PowerBI Desktop 連線
  - vw_gift_monthly_with_macro 含 canonical_group 欄位可供交叉篩選
```

---

### 3.7 測試與驗收規格（任務二）

#### T2-1 正規化對應正確性

```sql
-- 各年門檻正確
SELECT DISTINCT report_year, canonical_group, threshold_floor, threshold_ceiling
FROM vw_gift_canonical_monthly
WHERE period_type = 'MONTHLY'
ORDER BY canonical_group, report_year;
-- GIFT_LOW:  2021→760, 2022→760, 2023→850, 2024→900, 2025→900
-- GIFT_HIGH: 2021→5000, 2022→5000, 2023→5000, 2024→5000, 2025→5000

-- COMBINED 加總準確
SELECT COUNT(*) AS errors
FROM (
    SELECT ABS(c.sales_result - (l.sales_result + h.sales_result)) AS diff
    FROM vw_gift_combined_monthly c
    JOIN vw_gift_canonical_monthly l ON l.report_year=c.report_year
     AND l.report_month=c.report_month
     AND l.canonical_group='GIFT_LOW' AND l.period_type='MONTHLY'
    JOIN vw_gift_canonical_monthly h ON h.report_year=c.report_year
     AND h.report_month=c.report_month
     AND h.canonical_group='GIFT_HIGH' AND h.period_type='MONTHLY'
    WHERE c.period_type='MONTHLY'
) t WHERE diff > 1;
-- 應 = 0
```

#### T2-2 外部指標完整性

```sql
SELECT
    SUM(CASE WHEN dept_store_sales    IS NULL THEN 1 ELSE 0 END) AS miss_dept,
    SUM(CASE WHEN retail_food_index   IS NULL THEN 1 ELSE 0 END) AS miss_retail,
    SUM(CASE WHEN cci_index           IS NULL THEN 1 ELSE 0 END) AS miss_cci,
    SUM(CASE WHEN cpi_yoy_pct         IS NULL THEN 1 ELSE 0 END) AS miss_cpi,
    SUM(CASE WHEN cpi_food_yoy_pct    IS NULL THEN 1 ELSE 0 END) AS miss_cpi_food,
    SUM(CASE WHEN avg_wage_yoy_pct    IS NULL THEN 1 ELSE 0 END) AS miss_wage,
    SUM(CASE WHEN unemployment_rate   IS NULL THEN 1 ELSE 0 END) AS miss_unemp,
    SUM(CASE WHEN twd_jpy_rate        IS NULL THEN 1 ELSE 0 END) AS miss_jpy,
    SUM(CASE WHEN twd_usd_rate        IS NULL THEN 1 ELSE 0 END) AS miss_usd,
    SUM(CASE WHEN inbound_tourists    IS NULL THEN 1 ELSE 0 END) AS miss_tourist,
    SUM(CASE WHEN bsi_index           IS NULL THEN 1 ELSE 0 END) AS miss_bsi,
    SUM(CASE WHEN working_days        IS NULL THEN 1 ELSE 0 END) AS miss_workdays
FROM dim_macro_indicators
WHERE report_year BETWEEN 2021 AND 2025;
-- 全部應 = 0
```

#### T2-3 相關性分析輸出驗收

```
必須存在的輸出檔案：
  ✓ outputs/corr_heatmap_4groups.png
  ✓ outputs/stl_GIFT_LOW.png / GIFT_HIGH.png / GIFT_LARGE.png / GIFT_COMBINED.png
  ✓ outputs/lag_corr_GIFT_LOW.png（及其他三群）

相關係數驗收：
  ✓ GIFT_LARGE 與 bsi_index 的 Pearson |r| > GIFT_LOW 與 bsi_index 的 |r|
  ✓ has_lunar_new_year 對四群的相關係數均為正
  ✓ has_lunar_new_year 對至少 3 群達 p < 0.01
  ✓ 偏相關分析已執行並輸出（outputs/partial_corr_4groups.csv）
```

#### T2-4 模型精度驗收（2025 測試集）

| 群 | MAPE 最低標準 | MAPE 理想標準 | 高峰月命中率（前3名） |
|----|-------------|-------------|-------------------|
| GIFT_LOW | < 20% | < 13% | ≥ 2/3 |
| GIFT_HIGH | < 18% | < 12% | ≥ 2/3 |
| GIFT_COMBINED | < 15% | < 10% | ≥ 2/3 |
| GIFT_LARGE | < 25% | < 15% | ≥ 2/3 |

#### T2-5 報告完整性

```
docs/analysis_report.md 應包含：
  ✓ 各群前 5 大相關外部指標（係數、方向說明）
  ✓ 春節月份平均提振幅度（各群）
  ✓ 中秋月份平均提振幅度（各群）
  ✓ 門檻調漲影響量化
  ✓ BSI-GIFT_LARGE 假說驗證結論
  ✓ 各群 MAPE 摘要表
  ✓ 限制條件說明
```

---

## 4. 整體驗收流程

### 4.1 分階段 Gate Review

| Gate | 條件 | 通過標準 | 狀態 |
|------|------|---------|------|
| G1（Schema 完成） | STEP 1 完成 | 三張表 + 三個 View 建立成功 | ✅ 完成 |
| G2（ETL 完成） | STEP 2~5 完成 | 5 年資料全部載入，T1-1 ~ T1-4 通過 | ✅ 完成 |
| G3（正規化備齊） | STEP 6 完成 | `dim_gift_category_mapping` 7 列，View 驗證通過 | ✅ 完成 |
| G4（外部指標就緒） | STEP 7~8 完成 | 60 個月資料完整，T2-2 通過 | ✅ 完成（可驗收版） |
| G5（資料集整合） | STEP 9 完成 | `vw_gift_analysis_dataset` 240 列，T2-1 通過 | ✅ 完成 |
| G6（EDA 完成） | STEP 10 完成 | 5 張輸出圖存在，可識別季節性模式 | ✅ 完成 |
| G7（相關性完成） | STEP 11 完成 | T2-3 輸出驗收通過 | ✅ 完成（圖表/表格已輸出） |
| G8（模型完成） | STEP 12 完成 | MAPE 達 T2-4 標準 | ⚠ 完成但未達標 |
| G9（交付完成） | STEP 13 完成 | 報告完整，PowerBI View 可連線，T2-5 通過 | ✅ 完成（可驗收版） |

### 4.2 最終驗收查核清單

```
任務一（已完成）：
[x] STEP 1~5 驗收 SQL 全部通過
[x] ETL 冪等性：重跑多次，資料庫筆數不變（category=600, kpi=75）
[x] PowerBI 可連線 vw_kouseihi_monthly_category
[x] 所有 Python 腳本以 uv run python ... 執行無報錯
[x] etl_kouseihi_log 顯示 5 筆 SUCCESS 記錄

任務二（第二階段，可驗收版）：
[x] STEP 6：dim_gift_category_mapping 7 列 + 兩個 Gift View 建立
[x] STEP 7：macro_raw CSV 備齊（每份 60 筆）
[x] STEP 8：dim_macro_indicators 60 筆，關鍵欄位無 NULL
[x] STEP 9：vw_gift_analysis_dataset 240 列，gift_analysis_dataset.csv 輸出
[x] STEP 10：EDA 圖表輸出完成（timeseries / threshold / prediction）
[x] STEP 11：corr_heatmap_4groups.png + lag 圖輸出完成
[ ] STEP 12：四群模型 MAPE 達 T2-4 最低標準（目前未達）
[x] STEP 13：analysis_report.md 完整，PowerBI 三個 View 可連線
```

---

## 4.3 第一階段完成回報（2026-04-16）

### 已完成範圍

- 完成任務一 STEP 1~5：`KOUSEIHI ETL`（Parser / Transformer / Loader / CLI）
- 完成 DB 物件：`fact_kouseihi_category`、`fact_kouseihi_kpi`、`etl_kouseihi_log`
- 完成 PowerBI View：`vw_kouseihi_monthly_category`、`vw_kouseihi_annual`、`vw_kouseihi_half_year`
- 完成任務二 SQL 草稿：`db/schema_macro.sql`、`db/views_analysis.sql`、`db/views_prediction.sql`

### 重要設計修正（category 分類）

- 原先規格以 `GIFT_900_*` 作為固定區間；實際 PDF 歷年有不同區間。
- 第一階段已改為保留原始分類，不做跨年份正規化：
  - `2021~2022`: `GIFT_760_DOWN`、`GIFT_760_UP`
  - `2023`: `GIFT_850_DOWN`、`GIFT_850_UP`
  - `2024~2025`: `GIFT_900_DOWN`、`GIFT_900_UP`
- 相關表約束與 View 已同步調整，避免報表誤把不同年度門檻混為同一類。

### 驗收結果摘要

- 匯入結果：`fact_kouseihi_category = 600`、`fact_kouseihi_kpi = 75`
- 冪等性：重跑 `uv run python main_kouseihi.py --force`，資料筆數維持一致
- 關鍵驗證值（2025）：
  - `TOTAL ANNUAL sales_result = 377,054,372`
  - `TOTAL ANNUAL sales_yoy_pct = 105.9`
  - `ANNUAL KPI customer_count = 281,985`
  - `ANNUAL KPI unit_price = 1,337`
  - `ANNUAL KPI avg_daily_sales = 360,128`

> 第一階段（任務一）已完成，等待 Claude CLI 配發第二階段任務（任務二 STEP 6~11）。

---

## 5. 附錄

### A. KOUSEIHI PDF 欄位參照表

| PDF 顯示文字 | DB 欄位名 | 資料型別 | 說明 |
|------------|---------|---------|------|
| 賣上 | `sales_result` | DECIMAL(18,0) | 銷售金額（TWD 元） |
| 前年比（類別列） | `sales_yoy_pct` | DECIMAL(7,1) | 前年同期比（%，100=持平） |
| 本年構成 | `composition_curr_pct` | DECIMAL(5,1) | 本年類別佔比（%） |
| 前年構成 | `composition_prev_pct` | DECIMAL(5,1) | 前年類別佔比（%） |
| CUSTOMER COUNT 本年 | `customer_count` | INT | 客數 |
| CUSTOMER COUNT 前年比 | `customer_yoy_pct` | DECIMAL(7,1) | 客數前年比（%） |
| CUS UNIT PRICE 本年 | `unit_price` | DECIMAL(10,0) | 客單價（TWD 元） |
| CUS UNIT PRICE 前年比 | `unit_price_yoy_pct` | DECIMAL(7,1) | 客單價前年比（%） |
| TURNOVER 本年 | `turnover_curr` | DECIMAL(4,1) | 週轉次數（本年） |
| TURNOVER 前年 | `turnover_prev` | DECIMAL(4,1) | 週轉次數（前年） |
| DAY IN MONTH 本年 | `day_in_month_curr` | SMALLINT | 月銷售天數（本年） |
| DAY IN MONTH 前年 | `day_in_month_prev` | SMALLINT | 月銷售天數（前年） |
| AVERAGE DAILY SALES 本年 | `avg_daily_sales` | DECIMAL(14,0) | 日均銷售額（TWD） |
| AVERAGE DAILY SALES 前年比 | `avg_daily_sales_yoy_pct` | DECIMAL(7,1) | 日均銷售前年比（%） |

### B. SOKUHO 與 KOUSEIHI 資料層級關係

```
KOUSEIHI（公司別，月別，商品類別）
    └── 涵蓋全通路（實體門市 + 網路 + HQ + 其他）
    └── 資料粒度：年 → 月 × 商品類別

SOKUHO（門市別，日別，全商品）
    └── 涵蓋實體門市 + 部分 HQ 頻道
    └── 資料粒度：日 × 門市

交叉關係：
  SOKUHO GRAND TOTAL MTD（月底日）≈ KOUSEIHI TOTAL（月合計）
  差異可能來自：線上通路、HQ 業務、時間認列差異
```

### C. 分析報告建議章節結構（更新版）

```
docs/analysis_report.md
  1. 執行摘要
     - 四群 MAPE 達成摘要表
     - 前 5 大外部影響因子快覽

  2. 資料概況
     2.1 四群月度銷售趨勢（2021~2025）
     2.2 門檻調漲結構性斷點分析（2023/2024）
     2.3 各年禮盒佔公司總銷售比例

  3. 季節性特徵
     3.1 各群月度平均銷售排行（高峰月識別）
     3.2 春節效應：各群平均提振幅度（%）
     3.3 中秋效應：各群平均提振幅度（%）
     3.4 STL 季節性分解摘要

  4. 外部指標相關性分析
     4.1 Pearson 相關矩陣（四群並列）
     4.2 Lag 相關：最佳預測時間窗口
     4.3 偏相關：控制節日效應後的淨效應
     4.4 各群前 5 大影響因子（含方向說明）

  5. 特別分析：GIFT_LARGE 大單採購行為
     （GIFT_LARGE = 整筆訂單總額 ≥ 5000 TWD，非依商品牌價分類，為企業/團體大量採購行為）
     5.1 BSI 景氣信心假說驗證（企業景氣↑→大單採購↑）
     5.2 GIFT_LARGE 季節集中度（春節/中秋企業採購時間分布）
     5.3 GIFT_LARGE vs GIFT_COMBINED 相關因子差異（大單驅動力 vs 個人購買驅動力）

  6. 預測模型結果
     6.1 各群 MAPE 彙整表（最低標準 / 實際達成）
     6.2 2025 預測 vs 實際對比圖（四群）
     6.3 高峰月份命中率

  7. 2026 年應用展望
     7.1 如何利用外部指標更新預測
     7.2 可即時查詢的 PowerBI View 說明

  8. 限制條件與改善方向
     - 樣本數僅 5 年（60 個月）
     - BSI 為季別插值，月別精度不足
     - 門檻調漲造成跨年比較困難
```

### D. 相依套件（新增至 `pyproject.toml`）

```toml
# 分析套件（任務二專用）
scikit-learn = ">=1.4"
xgboost = ">=2.0"
statsmodels = ">=0.14"
prophet = ">=1.1"          # Facebook Prophet
matplotlib = ">=3.8"
seaborn = ">=0.13"
jupyter = ">=1.0"
```

---

*文件結束。本 SDD 供 course agent 實作參考，所有驗收 SQL 及數值均以 2025 年 PDF 為基準，其餘年份比照辦理。*

---

## E. 外在環境指標欄位代號說明（`dim_macro_indicators`）

以下為 `db/schema_macro.sql` 中主要外在環境欄位的中文意義，供閱讀模型與報表時快速對照：

- `dept_store_sales`：百貨公司銷售額（規模值）
- `retail_food_index`：食品零售指數（食品類零售景氣/動能）
- `cci_index`：消費者信心指數（Consumer Confidence Index）
- `cpi_yoy_pct`：整體 CPI 年增率（通膨年增）
- `cpi_food_yoy_pct`：食品 CPI 年增率
- `avg_wage_yoy_pct`：平均薪資年增率
- `twd_jpy_rate`：新台幣兌日圓匯率
- `twd_usd_rate`：新台幣兌美元匯率
- `unemployment_rate`：失業率
- `inbound_tourists`：入境旅客人數
- `bsi_index`：企業景氣指數（Business Sentiment Index）
- `has_lunar_new_year`：該月是否涵蓋農曆春節（0/1）
- `lunar_new_year_day`：春節日期（落在該月第幾日）
- `has_mid_autumn`：該月是否涵蓋中秋節（0/1）
- `mid_autumn_day`：中秋日期（落在該月第幾日）
- `working_days`：工作天數
- `calendar_days`：曆日總天數
- `weekend_days`：週末天數
- `gdp_yoy_pct`：GDP 年成長率
- `private_consumption_real_yoy_pct`：民間消費實質年成長率
- `department_store_yoy_pct`：百貨業年增率
- `retail_trade_yoy_pct`：整體零售業年增率
- `gift_market_sentiment_index`：禮盒市場氛圍指數（自建指標）
- `stock_wealth_effect_index`：股市財富效果指數（自建指標）
- `data_source`：資料來源註記
- `updated_at`：資料更新時間

補充：常見誤寫 `ift_market_sentiment_index`，正確欄位名為 `gift_market_sentiment_index`。
