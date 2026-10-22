"""
Database loader: upserts records into SQL Server via pyodbc.

Uses MERGE statement for idempotent loads (safe to re-run).
Tracks each file in etl_log to allow incremental processing.
"""

import logging
from datetime import date
from typing import Any

from etl.sokuho_overrides import Resolution

import pyodbc
import pandas as pd

logger = logging.getLogger(__name__)


class DatabaseUnavailableError(RuntimeError):
    """SQL Server is not reachable (production integration_pos_db likely down)."""


def _connection_refused(exc: BaseException) -> bool:
    msg = str(exc).lower()
    return "10061" in msg or "actively refused" in msg or "login timeout expired" in msg


def _db_startup_hint(server: str, database: str) -> str:
    return (
        f"無法連線到 SQL Server（{server} / {database}）。\n"
        "PosInsight 在正式機的 integration_pos_db 容器（port 1434）。請確認：\n"
        "\n"
        "  1. 本機在 CF 網段（HQ 連不到正式機）\n"
        "  2. 正式機已登入、Docker Desktop 已啟動：docker ps --filter name=integration_pos_db\n"
        "  3. .env 的 DB_SERVER 正確（正式機本機為 127.0.0.1,1434；開發機為 <正式機 IP>,1434）\n"
        "\n"
        "確認後請重新執行本指令。"
    )


# ── Connection ──────────────────────────────────────────────────────────────

def get_connection(
    server: str,
    database: str,
    user: str,
    password: str,
    *,
    timeout: int = 10,
) -> pyodbc.Connection:
    conn_str = (
        f"DRIVER={{ODBC Driver 18 for SQL Server}};"
        f"SERVER={server};"
        f"DATABASE={database};"
        f"UID={user};"
        f"PWD={password};"
        "TrustServerCertificate=yes;"
        "Encrypt=yes;"
    )
    try:
        return pyodbc.connect(conn_str, autocommit=False, timeout=timeout)
    except pyodbc.OperationalError as exc:
        if _connection_refused(exc):
            raise DatabaseUnavailableError(_db_startup_hint(server, database)) from exc
        raise


# ── Store ID cache ──────────────────────────────────────────────────────────

def load_store_map(conn: pyodbc.Connection) -> dict[str, int]:
    """Return {store_name: store_id} mapping from dim_store."""
    with conn.cursor() as cur:
        cur.execute("SELECT store_name, store_id FROM dim_store")
        result = {row.store_name: row.store_id for row in cur.fetchall()}
    if not result:
        raise RuntimeError(
            "dim_store is empty — run db/seed_stores.sql first."
        )
    return result


# ── ETL log helpers ─────────────────────────────────────────────────────────

def is_already_loaded(conn: pyodbc.Connection, source_file: str) -> bool:
    """True if this file was previously loaded successfully."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT 1 FROM etl_log WHERE source_file = ? AND status = 'SUCCESS'",
            source_file,
        )
        return cur.fetchone() is not None


def log_result(
    conn: pyodbc.Connection,
    source_file: str,
    report_date: date,
    records_loaded: int,
    status: str,
    error_message: str | None = None,
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO etl_log (source_file, report_date, records_loaded, status, error_message)
            VALUES (?, ?, ?, ?, ?)
            """,
            source_file,
            report_date,
            records_loaded,
            status,
            error_message,
        )
    conn.commit()


def upsert_sokuho_resolution(
    conn: pyodbc.Connection,
    report_date: date,
    actual_source_file: str,
    default_source_file: str | None,
    resolution_note: str | None,
    ignored_files_note: str | None,
) -> None:
    """Record which PDF was chosen for this report date (non-standard names, overrides)."""
    with conn.cursor() as cur:
        cur.execute(
            """
            MERGE etl_sokuho_import_resolution AS tgt
            USING (
                SELECT CAST(? AS DATE) AS report_date,
                       CAST(? AS NVARCHAR(500)) AS actual_source_file,
                       CAST(? AS NVARCHAR(500)) AS default_source_file,
                       CAST(? AS NVARCHAR(1000)) AS resolution_note,
                       CAST(? AS NVARCHAR(1000)) AS ignored_files_note
            ) AS src
            ON tgt.report_date = src.report_date
            WHEN MATCHED THEN
                UPDATE SET
                    actual_source_file = src.actual_source_file,
                    default_source_file = src.default_source_file,
                    resolution_note = src.resolution_note,
                    ignored_files_note = src.ignored_files_note,
                    last_loaded_at = GETDATE()
            WHEN NOT MATCHED THEN
                INSERT (report_date, actual_source_file, default_source_file, resolution_note, ignored_files_note)
                VALUES (src.report_date, src.actual_source_file, src.default_source_file, src.resolution_note, src.ignored_files_note);
            """,
            report_date,
            actual_source_file,
            default_source_file,
            resolution_note,
            ignored_files_note,
        )
    conn.commit()


# ── Core upsert ─────────────────────────────────────────────────────────────

_MERGE_SQL = """
MERGE fact_sales AS tgt
USING (
    SELECT
        CAST(? AS DATE)         AS report_date,
        CAST(? AS SMALLINT)     AS store_id,
        CAST(? AS CHAR(5))      AS record_type,
        CAST(? AS DECIMAL(18,0)) AS sales_result,
        CAST(? AS DECIMAL(10,2)) AS sales_budget_pct,
        CAST(? AS DECIMAL(12,2)) AS sales_yoy_pct,
        CAST(? AS INT)           AS customer_count,
        CAST(? AS DECIMAL(10,2)) AS customer_yoy_pct,
        CAST(? AS DECIMAL(12,2)) AS unit_price,
        CAST(? AS DECIMAL(10,2)) AS unit_price_yoy_pct,
        CAST(? AS DECIMAL(12,0)) AS ft_expense,
        CAST(? AS DECIMAL(10,2)) AS ft_budget_pct,
        CAST(? AS DECIMAL(12,0)) AS pt_expense,
        CAST(? AS DECIMAL(10,2)) AS pt_budget_pct,
        CAST(? AS DECIMAL(12,0)) AS total_personnel_expense,
        CAST(? AS DECIMAL(10,2)) AS total_personnel_budget_pct,
        CAST(? AS DECIMAL(18,0)) AS transfer_amount,
        CAST(? AS DECIMAL(18,0)) AS sales_incl_result,
        CAST(? AS DECIMAL(10,2)) AS sales_incl_budget_pct,
        CAST(? AS DECIMAL(12,2)) AS sales_incl_yoy_pct,
        CAST(? AS NVARCHAR(255)) AS source_file
) AS src
ON  tgt.report_date = src.report_date
AND tgt.store_id    = src.store_id
AND tgt.record_type = src.record_type
WHEN MATCHED THEN
    UPDATE SET
        sales_result                = src.sales_result,
        sales_budget_pct            = src.sales_budget_pct,
        sales_yoy_pct               = src.sales_yoy_pct,
        customer_count              = src.customer_count,
        customer_yoy_pct            = src.customer_yoy_pct,
        unit_price                  = src.unit_price,
        unit_price_yoy_pct          = src.unit_price_yoy_pct,
        ft_expense                  = src.ft_expense,
        ft_budget_pct               = src.ft_budget_pct,
        pt_expense                  = src.pt_expense,
        pt_budget_pct               = src.pt_budget_pct,
        total_personnel_expense     = src.total_personnel_expense,
        total_personnel_budget_pct  = src.total_personnel_budget_pct,
        transfer_amount             = src.transfer_amount,
        sales_incl_result           = src.sales_incl_result,
        sales_incl_budget_pct       = src.sales_incl_budget_pct,
        sales_incl_yoy_pct          = src.sales_incl_yoy_pct,
        source_file                 = src.source_file,
        value_source                = 'PDF',
        loaded_at                   = GETDATE()
WHEN NOT MATCHED THEN
    INSERT (
        report_date, store_id, record_type,
        sales_result, sales_budget_pct, sales_yoy_pct,
        customer_count, customer_yoy_pct,
        unit_price, unit_price_yoy_pct,
        ft_expense, ft_budget_pct, pt_expense, pt_budget_pct,
        total_personnel_expense, total_personnel_budget_pct,
        transfer_amount,
        sales_incl_result, sales_incl_budget_pct, sales_incl_yoy_pct,
        source_file
    )
    VALUES (
        src.report_date, src.store_id, src.record_type,
        src.sales_result, src.sales_budget_pct, src.sales_yoy_pct,
        src.customer_count, src.customer_yoy_pct,
        src.unit_price, src.unit_price_yoy_pct,
        src.ft_expense, src.ft_budget_pct, src.pt_expense, src.pt_budget_pct,
        src.total_personnel_expense, src.total_personnel_budget_pct,
        src.transfer_amount,
        src.sales_incl_result, src.sales_incl_budget_pct, src.sales_incl_yoy_pct,
        src.source_file
    );
"""

_ORDERED_COLS = [
    "report_date", "store_id", "record_type",
    "sales_result", "sales_budget_pct", "sales_yoy_pct",
    "customer_count", "customer_yoy_pct",
    "unit_price", "unit_price_yoy_pct",
    "ft_expense", "ft_budget_pct",
    "pt_expense", "pt_budget_pct",
    "total_personnel_expense", "total_personnel_budget_pct",
    "transfer_amount",
    "sales_incl_result", "sales_incl_budget_pct", "sales_incl_yoy_pct",
    "source_file",
]


def _to_py(val: Any) -> Any:
    """Convert numpy/pandas scalars → native Python for pyodbc."""
    if pd.isna(val):
        return None
    if hasattr(val, "item"):        # numpy scalar
        return val.item()
    return val


# 單日補值（Jack 2026-10-22）：PDF 單日為 0（或缺列）、當天客數 > 0、前後月累計完整時，單日＝當日 MTD − 前日 MTD。
# 客數 0 的「只進月累計」是入帳調整（例 Costco 10/13 MTD +768,600），不補——它在 vw_daily_store_sales.adjustment 看得到。
# 缺列時客數取月累計客數差。report_date 為 NULL 時掃全部日期（回補用）。
_DERIVE_SQL = """
MERGE fact_sales AS tgt
USING (
    SELECT m.store_id, m.report_date, m.source_file,
           m.sales_result - CASE WHEN DAY(m.report_date) = 1 THEN 0 ELSE p.sales_result END AS derived,
           m.customer_count - CASE WHEN DAY(m.report_date) = 1 THEN 0 ELSE p.customer_count END AS cust_diff
    FROM fact_sales m
    JOIN dim_store ds ON ds.store_id = m.store_id AND ds.store_type NOT IN ('subtotal', 'grand_total')
    LEFT JOIN fact_sales p ON p.store_id = m.store_id AND p.record_type = 'MTD'
                          AND p.report_date = DATEADD(DAY, -1, m.report_date)
    WHERE m.record_type = 'MTD' AND (? IS NULL OR m.report_date = ?)
      AND (DAY(m.report_date) = 1 OR p.sales_result IS NOT NULL)
) AS src
ON tgt.store_id = src.store_id AND tgt.report_date = src.report_date AND tgt.record_type = 'DAILY'
WHEN MATCHED AND ISNULL(tgt.sales_result, 0) = 0 AND tgt.customer_count > 0 AND src.derived > 0 THEN
    UPDATE SET sales_result = src.derived,
               sales_incl_result = src.derived + ISNULL(tgt.transfer_amount, 0),
               value_source = 'DERIVED'
WHEN NOT MATCHED AND src.cust_diff > 0 AND src.derived > 0 THEN
    INSERT (report_date, store_id, record_type, sales_result, sales_incl_result, customer_count, source_file, value_source)
    VALUES (src.report_date, src.store_id, 'DAILY', src.derived, src.derived, src.cust_diff, src.source_file, 'DERIVED');
"""


def derive_daily_from_mtd(conn: pyodbc.Connection, report_date: date | None = None) -> int:
    """Fill a store's zero/missing DAILY sales from MTD(d) − MTD(d−1); returns rows changed."""
    with conn.cursor() as cur:
        cur.execute(_DERIVE_SQL, report_date, report_date)
        n = cur.rowcount
    conn.commit()
    if n:
        logger.info("DERIVED %d DAILY row(s) from MTD for %s", n, report_date or "all dates")
    return n


def load_dataframe(
    conn: pyodbc.Connection,
    df: pd.DataFrame,
    store_map: dict[str, int],
) -> int:
    """
    Upsert all rows in df into fact_sales.
    Returns the number of rows processed.
    """
    if df.empty:
        return 0

    df = df.copy()
    df["store_id"] = df["store_name"].map(store_map)

    # Personnel expense allocation not needed in the DB layer.
    # We still parse/store the rest of the metrics, but force these fields to NULL
    # so PowerBI DAX can't accidentally depend on them.
    for col in (
        "ft_expense",
        "ft_budget_pct",
        "pt_expense",
        "pt_budget_pct",
        "total_personnel_expense",
        "total_personnel_budget_pct",
    ):
        if col in df.columns:
            df[col] = None

    count = 0
    with conn.cursor() as cur:
        for _, row in df.iterrows():
            params = [_to_py(row.get(c)) for c in _ORDERED_COLS]
            cur.execute(_MERGE_SQL, params)
            count += 1
    conn.commit()
    return count


def load_file(
    conn: pyodbc.Connection,
    df: pd.DataFrame,
    store_map: dict[str, int],
    source_file: str,
    report_date: date,
    force: bool = False,
    resolution: Resolution | None = None,
    unknown_store_policy: str = "skip_row",
) -> int:
    """
    Full pipeline for one PDF's data:
      1. Skip if already loaded (unless force=True)
      2. Upsert rows
      3. Write etl_log entry

    Returns number of rows loaded (0 if skipped).
    """
    if not force and is_already_loaded(conn, source_file):
        logger.info("SKIPPED (already loaded): %s", source_file)
        return 0

    # Unknown store handling policy:
    # - skip_day: skip this whole file/day if any unknown store appears
    # - skip_row: skip only unknown-store rows and keep importing known stores
    unknown_stores = sorted(set(df["store_name"]) - set(store_map))
    success_note: str | None = None
    if unknown_stores:
        unknown_msg = (
            f"Unknown stores in {source_file}: {', '.join(unknown_stores)}"
        )
        if unknown_store_policy == "skip_day":
            logger.warning("SKIPPED DAY due to unknown stores: %s", unknown_stores)
            log_result(conn, source_file, report_date, 0, "SKIPPED", unknown_msg)
            return 0

        before = len(df)
        df = df[df["store_name"].isin(store_map)].copy()
        skipped = before - len(df)
        success_note = f"{unknown_msg}. Skipped rows: {skipped}"
        logger.warning("Skipping unknown-store rows: %s (rows=%d)", unknown_stores, skipped)
        if df.empty:
            log_result(conn, source_file, report_date, 0, "SKIPPED", success_note)
            return 0

    try:
        if force:
            # Re-processing replaces this file's rows for this day: MERGE alone keeps rows the new parse
            # no longer yields (2026-10-21: misaligned old parses left e.g. THSR DAILY 3,172,499).
            # Same transaction as the MERGE (load_dataframe commits; rollback below restores).
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM fact_sales WHERE report_date = ? AND source_file = ?",
                    report_date, source_file,
                )
        n = load_dataframe(conn, df, store_map)
        derive_daily_from_mtd(conn, report_date)
        log_result(conn, source_file, report_date, n, "SUCCESS", success_note)
        if resolution is not None:
            ignored_txt = (
                "; ".join(resolution.ignored_basenames) if resolution.ignored_basenames else None
            )
            upsert_sokuho_resolution(
                conn,
                report_date=resolution.report_date,
                actual_source_file=resolution.chosen_path.name,
                default_source_file=resolution.default_source_file,
                resolution_note=resolution.note,
                ignored_files_note=ignored_txt,
            )
        logger.info("LOADED %s → %d rows", source_file, n)
        return n
    except Exception as exc:
        conn.rollback()
        log_result(conn, source_file, report_date, 0, "FAILED", str(exc))
        logger.error("FAILED %s: %s", source_file, exc)
        raise
