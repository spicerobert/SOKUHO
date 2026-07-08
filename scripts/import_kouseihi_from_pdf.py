#!/usr/bin/env python
from __future__ import annotations

import argparse
import os
from pathlib import Path

import pdfplumber
import pyodbc
from dotenv import load_dotenv


CATEGORY_MAP = {
    "GRAMCOOKIES": "GRAM_COOKIES",
    "GIFT5000": "GIFT_5000_UP",
    "DRYCAKE": "DRY_CAKE",
    "F&B": "FB",
    "OTHER": "OTHER",
    "TOTAL": "TOTAL",
}


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Import KOUSEIHI monthly rows from PDF")
    p.add_argument("--pdf", required=True, help="PDF path")
    p.add_argument("--year", type=int, required=True, help="report year")
    p.add_argument("--month-start", type=int, required=True, help="start month")
    p.add_argument("--month-end", type=int, required=True, help="end month")
    p.add_argument("--force", action="store_true", help="delete existing rows first")
    return p.parse_args()


def _normalize_label(v: str | None) -> str:
    if not v:
        return ""
    return "".join(v.replace("\n", "").replace(" ", "").upper().split())


def _to_int(v: str | None) -> int | None:
    if not v:
        return None
    s = v.replace(",", "").strip()
    if not s:
        return None
    return int(float(s))


def _to_float(v: str | None) -> float | None:
    if not v:
        return None
    s = v.replace(",", "").strip()
    if not s:
        return None
    return float(s)


def _connect() -> pyodbc.Connection:
    load_dotenv()
    return pyodbc.connect(
        "DRIVER={ODBC Driver 18 for SQL Server};"
        f"SERVER={os.environ['DB_SERVER']};"
        f"DATABASE={os.environ['DB_NAME']};"
        f"UID={os.environ['DB_USER']};"
        f"PWD={os.environ['DB_PASSWORD']};"
        "TrustServerCertificate=yes;"
        "Encrypt=yes;"
    )


def _extract_rows(pdf_path: Path, month_start: int, month_end: int) -> tuple[list[dict], list[dict]]:
    with pdfplumber.open(str(pdf_path)) as pdf:
        table = pdf.pages[0].extract_tables()[0]

    month_to_col = {1: 2, 2: 3, 3: 4, 4: 5, 5: 6, 6: 7, 7: 9, 8: 10, 9: 11, 10: 12, 11: 13, 12: 14}
    months = list(range(month_start, month_end + 1))

    category_rows: list[dict] = []
    kpi_rows: list[dict] = []

    i = 1
    gift_floor_seen = 0
    while i < len(table):
        row = table[i]
        label = _normalize_label(row[0] if len(row) > 0 else None)
        metric = (row[1] or "").strip() if len(row) > 1 and row[1] else ""

        # Category blocks (4 rows each): amount / yoy / comp_curr / comp_prev
        if (
            label in ("GRAMCOOKIES", "DRYCAKE", "F&B", "OTHER", "TOTAL")
            or label.startswith("GIFT900")
            or label.startswith("GIFT5000")
        ):
            if i + 3 >= len(table):
                break
            r_amt = table[i]
            r_yoy = table[i + 1]
            r_curr = table[i + 2]
            r_prev = table[i + 3]

            if label.startswith("GIFT900"):
                gift_floor_seen += 1
                cat = "GIFT_900_DOWN" if gift_floor_seen == 1 else "GIFT_900_UP"
            elif label.startswith("GIFT5000"):
                cat = "GIFT_5000_UP"
            else:
                cat = CATEGORY_MAP.get(label, label)

            for m in months:
                c = month_to_col[m]
                category_rows.append(
                    {
                        "report_month": m,
                        "category": cat,
                        "sales_result": _to_int(r_amt[c] if c < len(r_amt) else None),
                        "sales_yoy_pct": _to_float(r_yoy[c] if c < len(r_yoy) else None),
                        "composition_curr_pct": _to_float(r_curr[c] if c < len(r_curr) else None),
                        "composition_prev_pct": _to_float(r_prev[c] if c < len(r_prev) else None),
                    }
                )
            i += 4
            continue

        # KPI blocks
        if label == "CUSTOMERCOUNT" and i + 1 < len(table):
            yoy_row = table[i + 1]
            for m in months:
                c = month_to_col[m]
                kpi_rows.append(
                    {
                        "report_month": m,
                        "customer_count": _to_int(row[c] if c < len(row) else None),
                        "customer_yoy_pct": _to_float(yoy_row[c] if c < len(yoy_row) else None),
                    }
                )
            i += 2
            continue

        if label == "CUSUNITPRICE" and i + 1 < len(table):
            yoy_row = table[i + 1]
            for idx, m in enumerate(months):
                c = month_to_col[m]
                kpi_rows[idx]["unit_price"] = _to_float(row[c] if c < len(row) else None)
                kpi_rows[idx]["unit_price_yoy_pct"] = _to_float(yoy_row[c] if c < len(yoy_row) else None)
            i += 2
            continue

        if label == "TURNOVER" and i + 1 < len(table):
            prev_row = table[i + 1]
            for idx, m in enumerate(months):
                c = month_to_col[m]
                kpi_rows[idx]["turnover_curr"] = _to_float(row[c] if c < len(row) else None)
                kpi_rows[idx]["turnover_prev"] = _to_float(prev_row[c] if c < len(prev_row) else None)
            i += 2
            continue

        if label == "DAYINMONTH" and i + 1 < len(table):
            prev_row = table[i + 1]
            for idx, m in enumerate(months):
                c = month_to_col[m]
                kpi_rows[idx]["day_in_month_curr"] = _to_int(row[c] if c < len(row) else None)
                kpi_rows[idx]["day_in_month_prev"] = _to_int(prev_row[c] if c < len(prev_row) else None)
            i += 2
            continue

        if label == "AVERAGEDAILYSALES" and i + 1 < len(table):
            yoy_row = table[i + 1]
            for idx, m in enumerate(months):
                c = month_to_col[m]
                kpi_rows[idx]["avg_daily_sales"] = _to_float(row[c] if c < len(row) else None)
                kpi_rows[idx]["avg_daily_sales_yoy_pct"] = _to_float(yoy_row[c] if c < len(yoy_row) else None)
            i += 2
            continue

        if metric == "":
            i += 1
            continue
        i += 1

    return category_rows, kpi_rows


def main() -> None:
    args = parse_args()
    if args.month_start < 1 or args.month_end > 12 or args.month_start > args.month_end:
        raise ValueError("month range invalid")

    pdf_path = Path(args.pdf)
    if not pdf_path.exists():
        raise FileNotFoundError(pdf_path)

    category_rows, kpi_rows = _extract_rows(pdf_path, args.month_start, args.month_end)
    source_file = pdf_path.name

    conn = _connect()
    cur = conn.cursor()
    try:
        if args.force:
            cur.execute(
                """
                DELETE FROM fact_kouseihi_category
                WHERE report_year = ? AND report_month BETWEEN ? AND ? AND period_type = 'MONTHLY'
                """,
                args.year,
                args.month_start,
                args.month_end,
            )
            cur.execute(
                """
                DELETE FROM fact_kouseihi_kpi
                WHERE report_year = ? AND report_month BETWEEN ? AND ? AND period_type = 'MONTHLY'
                """,
                args.year,
                args.month_start,
                args.month_end,
            )

        for r in category_rows:
            cur.execute(
                """
                INSERT INTO fact_kouseihi_category
                (report_year, report_month, period_type, category,
                 sales_result, sales_yoy_pct, composition_curr_pct, composition_prev_pct, source_file)
                VALUES (?, ?, 'MONTHLY', ?, ?, ?, ?, ?, ?)
                """,
                args.year,
                r["report_month"],
                r["category"],
                r["sales_result"],
                r["sales_yoy_pct"],
                r["composition_curr_pct"],
                r["composition_prev_pct"],
                source_file,
            )

        for r in kpi_rows:
            cur.execute(
                """
                INSERT INTO fact_kouseihi_kpi
                (report_year, report_month, period_type, customer_count, customer_yoy_pct,
                 unit_price, unit_price_yoy_pct, turnover_curr, turnover_prev,
                 day_in_month_curr, day_in_month_prev, avg_daily_sales, avg_daily_sales_yoy_pct, source_file)
                VALUES (?, ?, 'MONTHLY', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                args.year,
                r["report_month"],
                r.get("customer_count"),
                r.get("customer_yoy_pct"),
                r.get("unit_price"),
                r.get("unit_price_yoy_pct"),
                r.get("turnover_curr"),
                r.get("turnover_prev"),
                r.get("day_in_month_curr"),
                r.get("day_in_month_prev"),
                r.get("avg_daily_sales"),
                r.get("avg_daily_sales_yoy_pct"),
                source_file,
            )

        cur.execute(
            """
            INSERT INTO etl_kouseihi_log
            (source_file, report_year, category_rows, kpi_rows, status, error_message)
            VALUES (?, ?, ?, ?, 'SUCCESS', NULL)
            """,
            source_file,
            args.year,
            len(category_rows),
            len(kpi_rows),
        )
        conn.commit()
    except Exception as exc:
        conn.rollback()
        cur.execute(
            """
            INSERT INTO etl_kouseihi_log
            (source_file, report_year, category_rows, kpi_rows, status, error_message)
            VALUES (?, ?, 0, 0, 'FAILED', ?)
            """,
            source_file,
            args.year,
            str(exc)[:4000],
        )
        conn.commit()
        raise
    finally:
        conn.close()

    print(f"Imported category_rows={len(category_rows)}, kpi_rows={len(kpi_rows)}")


if __name__ == "__main__":
    main()
