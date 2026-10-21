#!/usr/bin/env python
r"""比對 PosInsight 現況與搬遷清單（manifest），確認 .bak 還原後資料一致。

  uv run python scripts/verify_prod_migration.py --manifest "<SOKUHO_BAK_DEST>\migration\<名稱>.manifest.json"

清單由 prepare_prod_bak.py 產出，與 .bak 同名放在一起。連線用 .env（DB_SERVER / DB_NAME / DB_USER / DB_PASSWORD）。
fact_sales 只比 report_date <= 清單的 max_report_date：還原後排程補抓的新日子不算差異。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from etl import loader as db


def snapshot(conn, max_report_date: str | None = None) -> dict:
    """dbo 各表列數、view 清單、fact_sales 最大日期與金額合計；可用 max_report_date 截斷 fact_sales。"""
    cur = conn.cursor()
    cur.execute("SELECT DB_NAME()")
    database = cur.fetchone()[0]
    cur.execute(
        "SELECT name FROM sys.tables WHERE schema_id = SCHEMA_ID('dbo') ORDER BY name"
    )
    tables = [r[0] for r in cur.fetchall()]
    counts = {}
    for t in tables:
        cur.execute(f"SELECT COUNT_BIG(*) FROM dbo.[{t}]")
        counts[t] = cur.fetchone()[0]

    cutoff = "WHERE report_date <= ?" if max_report_date else ""
    params = [max_report_date] if max_report_date else []
    cur.execute(
        f"SELECT COUNT_BIG(*), MAX(report_date), SUM(CAST(sales_incl_result AS decimal(38,2))) "
        f"FROM dbo.fact_sales {cutoff}",
        params,
    )
    n, max_date, total = cur.fetchone()
    counts["fact_sales"] = n

    cur.execute("SELECT name FROM sys.views WHERE schema_id = SCHEMA_ID('dbo') ORDER BY name")
    views = [r[0] for r in cur.fetchall()]
    cur.execute("SELECT COUNT(*) FROM sys.objects WHERE schema_id <> SCHEMA_ID('dbo') AND is_ms_shipped = 0")
    foreign = cur.fetchone()[0]
    cur.execute("SELECT CAST(DATABASEPROPERTYEX(DB_NAME(), 'Collation') AS nvarchar(128))")
    collation = cur.fetchone()[0]
    return {
        "database": database,
        "collation": collation,
        "table_counts": counts,
        "views": views,
        "non_dbo_objects": foreign,
        "max_report_date": max_date.isoformat() if max_date else None,
        "fact_sales_sales_incl_result_sum": str(total),
    }


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--manifest", required=True, type=Path)
    args = ap.parse_args()
    load_dotenv()

    expected = json.loads(args.manifest.read_text(encoding="utf-8"))
    conn = db.get_connection(
        server=os.environ["DB_SERVER"],
        database=os.environ["DB_NAME"],
        user=os.environ["DB_USER"],
        password=os.environ["DB_PASSWORD"],
    )
    try:
        actual = snapshot(conn, expected["max_report_date"])
    finally:
        conn.close()

    diffs = []
    for key in ("collation", "views", "non_dbo_objects", "max_report_date", "fact_sales_sales_incl_result_sum"):
        if actual[key] != expected[key]:
            diffs.append(f"{key}: 清單 {expected[key]!r} ≠ 現況 {actual[key]!r}")
    for t in sorted(set(expected["table_counts"]) | set(actual["table_counts"])):
        e, a = expected["table_counts"].get(t), actual["table_counts"].get(t)
        # 還原後排程會繼續寫 etl_log / etl_sokuho_import_resolution，只允許變多
        grows = t in ("etl_log", "etl_sokuho_import_resolution") and e is not None and a is not None and a >= e
        mark = "OK" if e == a or grows else "差異"
        print(f"  {t:<34}{e!s:>10}{a!s:>10}  {mark}")
        if mark != "OK":
            diffs.append(f"{t}: 清單 {e} ≠ 現況 {a}")

    print(f"資料庫 {actual['database']}；fact_sales 截至 {actual['max_report_date']}；view {len(actual['views'])} 個")
    if diffs:
        print("驗收失敗：\n  " + "\n  ".join(diffs))
        return 1
    print("驗收通過")
    return 0


if __name__ == "__main__":
    sys.exit(main())
