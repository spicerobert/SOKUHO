USE PosInsight;
GO

IF OBJECT_ID('dim_macro_indicators', 'U') IS NULL
CREATE TABLE dim_macro_indicators (
    id                              INT             IDENTITY(1,1)   PRIMARY KEY,
    report_year                     SMALLINT        NOT NULL,
    report_month                    TINYINT         NOT NULL,
    dept_store_sales                DECIMAL(18,2)   NULL,
    retail_food_index               DECIMAL(8,2)    NULL,
    cci_index                       DECIMAL(8,2)    NULL,
    cpi_yoy_pct                     DECIMAL(6,2)    NULL,
    cpi_food_yoy_pct                DECIMAL(6,2)    NULL,
    avg_wage_yoy_pct                DECIMAL(6,2)    NULL,
    twd_jpy_rate                    DECIMAL(8,4)    NULL,
    twd_usd_rate                    DECIMAL(8,4)    NULL,
    unemployment_rate               DECIMAL(5,2)    NULL,
    inbound_tourists                INT             NULL,
    bsi_index                       DECIMAL(8,2)    NULL,
    has_lunar_new_year              BIT             NOT NULL DEFAULT 0,
    lunar_new_year_day              TINYINT         NULL,
    has_mid_autumn                  BIT             NOT NULL DEFAULT 0,
    mid_autumn_day                  TINYINT         NULL,
    working_days                    TINYINT         NULL,
    calendar_days                   TINYINT         NULL,
    weekend_days                    TINYINT         NULL,
    -- Added per user request
    gdp_yoy_pct                     DECIMAL(6,2)    NULL,   -- GDP 年成長率
    private_consumption_real_yoy_pct DECIMAL(6,2)   NULL,   -- 民間消費實質成長
    department_store_yoy_pct        DECIMAL(6,2)    NULL,   -- 百貨業年增率
    retail_trade_yoy_pct            DECIMAL(6,2)    NULL,   -- 整體零售業年增率
    gift_market_sentiment_index     DECIMAL(8,2)    NULL,   -- 食品禮盒市場氛圍（自建 index）
    stock_wealth_effect_index       DECIMAL(8,2)    NULL,   -- 股市財富效果（自建 index）
    data_source                     NVARCHAR(200)   NULL,
    updated_at                      DATETIME2       NOT NULL DEFAULT GETDATE(),
    CONSTRAINT uq_macro_year_month UNIQUE (report_year, report_month)
);
GO

IF OBJECT_ID('dim_macro_indicators', 'U') IS NOT NULL
BEGIN
    IF COL_LENGTH('dim_macro_indicators', 'dept_store_sales') IS NULL
        ALTER TABLE dim_macro_indicators ADD dept_store_sales DECIMAL(18,2) NULL;
    IF COL_LENGTH('dim_macro_indicators', 'retail_food_index') IS NULL
        ALTER TABLE dim_macro_indicators ADD retail_food_index DECIMAL(8,2) NULL;
    IF COL_LENGTH('dim_macro_indicators', 'cpi_food_yoy_pct') IS NULL
        ALTER TABLE dim_macro_indicators ADD cpi_food_yoy_pct DECIMAL(6,2) NULL;
    IF COL_LENGTH('dim_macro_indicators', 'avg_wage_yoy_pct') IS NULL
        ALTER TABLE dim_macro_indicators ADD avg_wage_yoy_pct DECIMAL(6,2) NULL;
    IF COL_LENGTH('dim_macro_indicators', 'bsi_index') IS NULL
        ALTER TABLE dim_macro_indicators ADD bsi_index DECIMAL(8,2) NULL;
    IF COL_LENGTH('dim_macro_indicators', 'has_mid_autumn') IS NULL
        ALTER TABLE dim_macro_indicators ADD has_mid_autumn BIT NOT NULL DEFAULT 0;
    IF COL_LENGTH('dim_macro_indicators', 'mid_autumn_day') IS NULL
        ALTER TABLE dim_macro_indicators ADD mid_autumn_day TINYINT NULL;
    IF COL_LENGTH('dim_macro_indicators', 'calendar_days') IS NULL
        ALTER TABLE dim_macro_indicators ADD calendar_days TINYINT NULL;
    IF COL_LENGTH('dim_macro_indicators', 'weekend_days') IS NULL
        ALTER TABLE dim_macro_indicators ADD weekend_days TINYINT NULL;
    IF COL_LENGTH('dim_macro_indicators', 'gdp_yoy_pct') IS NULL
        ALTER TABLE dim_macro_indicators ADD gdp_yoy_pct DECIMAL(6,2) NULL;
    IF COL_LENGTH('dim_macro_indicators', 'private_consumption_real_yoy_pct') IS NULL
        ALTER TABLE dim_macro_indicators ADD private_consumption_real_yoy_pct DECIMAL(6,2) NULL;
    IF COL_LENGTH('dim_macro_indicators', 'department_store_yoy_pct') IS NULL
        ALTER TABLE dim_macro_indicators ADD department_store_yoy_pct DECIMAL(6,2) NULL;
    IF COL_LENGTH('dim_macro_indicators', 'retail_trade_yoy_pct') IS NULL
        ALTER TABLE dim_macro_indicators ADD retail_trade_yoy_pct DECIMAL(6,2) NULL;
    IF COL_LENGTH('dim_macro_indicators', 'gift_market_sentiment_index') IS NULL
        ALTER TABLE dim_macro_indicators ADD gift_market_sentiment_index DECIMAL(8,2) NULL;
    IF COL_LENGTH('dim_macro_indicators', 'stock_wealth_effect_index') IS NULL
        ALTER TABLE dim_macro_indicators ADD stock_wealth_effect_index DECIMAL(8,2) NULL;
END
GO
