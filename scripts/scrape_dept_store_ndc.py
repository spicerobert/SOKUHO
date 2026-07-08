"""
Scrape real data for:
  dept_store_yoy.csv / retail_trade_yoy.csv  ← MOEA bulletin text
  bsi.csv                                     ← NDC 景氣對策信號

Strategy:
  Phase 1 – Collect all bulletin IDs from MOEA filter (2024-06 ~ present)
  Phase 2 – Fetch each bulletin via HTTP request and extract YoY%
  Phase 3 – Scan older IDs (2021-2024) via HTTP request scan
  Phase 4 – Scrape NDC BSI historical data
"""

from __future__ import annotations
import asyncio, re, time
from pathlib import Path

import pandas as pd
from playwright.async_api import async_playwright, Page

RAW = Path(__file__).parent.parent / "data" / "macro_raw"
SS  = Path(__file__).parent.parent / "outputs" / "macro_scrape_screenshots"
SS.mkdir(parents=True, exist_ok=True)

BASE_MOEA = "https://www.moea.gov.tw/MNS/dos"
NDC_TABLE = "https://index.ndc.gov.tw/n/zh_tw/page/composite_index_table"

# Known IDs from probe (confirmed working)
KNOWN: dict[tuple[int,int], int] = {
    (2025, 7): 16668, (2025, 8): 16698, (2025, 9): 16715,
    (2025,10): 16732, (2025,11): 16762, (2025,12): 16780,
    (2026, 1): 16799, (2026, 2): 16815, (2026, 3): 16832,
    (2026, 4): 16850,
}


def extract_bulletin_data(text: str) -> dict:
    """Extract year, month, YoY% from MOEA bulletin plain text."""
    r: dict = {}
    hdr = re.search(r"(\d{3})年(\d{1,2})月批發", text)
    if hdr:
        r["year"]  = 1911 + int(hdr.group(1))
        r["month"] = int(hdr.group(2))

    def yoy(pattern: str) -> float | None:
        m = re.search(pattern, text)
        if not m:
            return None
        val = float(m.group(1))
        ctx = text[max(0, m.start()-5): m.end()+5]
        return -val if "年減" in ctx else val

    r["dept_store_yoy"] = yoy(r"百貨公司年[增減](\d+\.?\d*)%")
    r["retail_yoy"]     = yoy(r"零售業營業額[^。]{0,80}?年[增減](\d+\.?\d*)%")
    r["wholesale_yoy"]  = yoy(r"批發業營業額[^。]{0,60}?年[增減](\d+\.?\d*)%")
    return r


async def fetch_bulletin_text(ctx, bull_id: int) -> str | None:
    url = f"{BASE_MOEA}/bulletin/Bulletin.aspx?kind=8&html=1&menu_id=6727&bull_id={bull_id}"
    try:
        resp = await ctx.request.get(url, timeout=12000)
        if resp.status != 200:
            return None
        html = await resp.text()
        # Strip tags for text extraction
        text = re.sub(r"<[^>]+>", " ", html)
        text = re.sub(r"&nbsp;", " ", text)
        text = re.sub(r"&[a-z]+;", "", text)
        text = re.sub(r"\s+", " ", text)
        return text if len(text) > 500 and "批發" in text else None
    except Exception:
        return None


async def main():
    moea_data: dict[tuple[int,int], dict] = {}
    bsi_rows:  list[dict] = []

    async with async_playwright() as p:
        browser = await p.firefox.launch(headless=True)
        ctx = await browser.new_context(
            viewport={"width":1280,"height":900}, locale="zh-TW",
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:122.0) Gecko/20100101 Firefox/122.0",
        )
        page = await ctx.new_page()

        # ── Phase 1: Collect all bull_ids from MOEA date filter ───────────
        print("[1] Collecting bull_ids from MOEA filter...")
        list_url = f"{BASE_MOEA}/bulletin/Bulletin.aspx?kind=8&html=1&menu_id=6727"
        await page.goto(list_url, timeout=30000)
        await page.wait_for_load_state("networkidle", timeout=20000)

        sels = await page.query_selector_all("select")
        all_bull_ids: list[int] = []
        if sels:
            opts = await sels[0].query_selector_all("option")
            date_opts = [v for o in opts
                         if (v := (await o.get_attribute("value") or "").strip())
                         and re.match(r"\d{4}-\d{2}", v)]
            print(f"  Filter options: {date_opts}")

            for dt in date_opts:
                await sels[0].select_option(dt)
                await page.wait_for_timeout(1500)
                # Extract bull_ids from the current table — read HTML directly
                html = await page.content()
                ids  = re.findall(r"bull_id=(\d+)", html)
                for bid in ids:
                    bid_i = int(bid)
                    if bid_i not in all_bull_ids and bid_i > 10000:
                        all_bull_ids.append(bid_i)

        # Merge with known IDs
        for bid in KNOWN.values():
            if bid not in all_bull_ids:
                all_bull_ids.append(bid)
        all_bull_ids = sorted(set(all_bull_ids), reverse=True)
        print(f"  Total unique bull_ids found: {len(all_bull_ids)}")
        print(f"  ID range: {min(all_bull_ids)} – {max(all_bull_ids)}")

        # ── Phase 2: Fetch each bulletin via HTTP ─────────────────────────
        print("\n[2] Fetching bulletins via HTTP...")
        for bid in all_bull_ids:
            text = await fetch_bulletin_text(ctx, bid)
            if not text:
                continue
            d = extract_bulletin_data(text)
            if d.get("year") and d.get("dept_store_yoy") is not None:
                key = (d["year"], d["month"])
                if key not in moea_data:
                    moea_data[key] = d
                    sign_d = "+" if (d.get("dept_store_yoy") or 0) >= 0 else ""
                    sign_r = "+" if (d.get("retail_yoy") or 0) >= 0 else ""
                    print(f"  {key}  dept={sign_d}{d.get('dept_store_yoy',.0):.1f}%"
                          f"  retail={sign_r}{d.get('retail_yoy',0):.1f}%"
                          f"  [bull_id={bid}]")

        # ── Phase 3: Scan older IDs (estimate ~15348 – 16668) ────────────
        oldest_known = min(all_bull_ids) if all_bull_ids else 16668
        scan_start   = oldest_known - 1
        scan_end     = oldest_known - 1300   # go back ~65 months × avg gap ~20
        print(f"\n[3] Scanning IDs {scan_end} .. {scan_start} for pre-2024 bulletins...")
        hit_count = 0
        for bid in range(scan_start, scan_end, -2):  # step 2
            text = await fetch_bulletin_text(ctx, bid)
            if not text:
                continue
            d = extract_bulletin_data(text)
            if d.get("year") and d.get("dept_store_yoy") is not None:
                key = (d["year"], d["month"])
                if key not in moea_data:
                    moea_data[key] = d
                    hit_count += 1
                    sign_d = "+" if (d.get("dept_store_yoy") or 0) >= 0 else ""
                    sign_r = "+" if (d.get("retail_yoy") or 0) >= 0 else ""
                    print(f"  {key}  dept={sign_d}{d.get('dept_store_yoy',0):.1f}%"
                          f"  retail={sign_r}{d.get('retail_yoy',0):.1f}%"
                          f"  [bull_id={bid}]")
                    if key <= (2021, 1):
                        print("  Reached Jan 2021 — scan complete")
                        break

        print(f"\n  Scan found {hit_count} additional months")

        # ── Phase 4: NDC 景氣對策信號 (BSI) ───────────────────────────────
        print("\n[4] Scraping NDC Business Conditions Signal for BSI...")
        try:
            await page.goto(NDC_TABLE, timeout=30000)
            await page.wait_for_load_state("networkidle", timeout=20000)
            await page.screenshot(path=str(SS / "ndc_bsi.png"))

            # Try "用表格檢視" button
            btn = page.locator("text=用表格檢視").first
            if await btn.count() > 0:
                await btn.click()
                await page.wait_for_timeout(3000)
                await page.screenshot(path=str(SS / "ndc_bsi_table.png"))

            html = await page.content()
            text_ndc = await page.evaluate("document.body.innerText")

            # Extract from <table> elements
            tables = await page.query_selector_all("table")
            print(f"  Tables: {len(tables)}")
            for i, tbl in enumerate(tables[:5]):
                t = (await tbl.inner_text()).strip()
                print(f"  Table {i} ({len(t)} chars): {t[:200]}")
                if any(str(y) in t for y in range(2021, 2026)):
                    print(f"  *** Table {i} has historical data! ***")

            # Search for year/score data in page scripts (embedded chart data)
            scripts = await page.query_selector_all("script:not([src])")
            for sc in scripts:
                src = await sc.inner_text()
                if len(src) < 100 or "110" not in src:
                    continue
                # Look for arrays of 2-digit numbers (NDC scores 9-45)
                # and associated year-month labels
                num_arrays = re.findall(r"\[(\d{2}(?:,\s*\d{2}){5,})\]", src)
                lbl_arrays = re.findall(r"\[(?:[\"'](\d{3}/\d{2})[\"'],?\s*){5,}\]", src)
                if num_arrays:
                    print(f"  Script score array: {num_arrays[0][:80]}")
                if lbl_arrays:
                    print(f"  Script labels: {lbl_arrays[:12]}")

                # Simpler: find pairs like '110/01': 33
                pairs = re.findall(r"[\"'](\d{3}/\d{2})[\"']\s*:\s*(\d{1,2})\b", src)
                if pairs:
                    print(f"  Found {len(pairs)} label:score pairs")
                    for lbl, sc_val in pairs[:5]:
                        print(f"    {lbl} → {sc_val}")

            # Also try the NDC open data download
            await page.goto("https://index.ndc.gov.tw/n/zh_tw/download", timeout=20000)
            await page.wait_for_load_state("networkidle", timeout=12000)
            dl_links = await page.query_selector_all("a")
            ndc_dl = []
            for l in dl_links:
                h = (await l.get_attribute("href")) or ""
                t = (await l.inner_text()).strip()
                if any(x in h.lower() for x in [".xls",".xlsx",".csv",".zip"]) or \
                   any(x in t for x in ["下載","Excel","資料"]):
                    ndc_dl.append((t[:60], h[:120]))
            print(f"\n  NDC download links: {len(ndc_dl)}")
            for t, h in ndc_dl[:10]:
                print(f"    [{t}] {h}")

        except Exception as e:
            print(f"  NDC error: {e}")

        await browser.close()

    # ── Results ───────────────────────────────────────────────────────────
    print(f"\n{'='*60}")
    print(f"MOEA data collected: {len(moea_data)} month-entries")
    sorted_data = sorted(moea_data.items())
    for key, d in sorted_data:
        if 2021 <= key[0] <= 2025:   # only show in-range months
            sign_d = "+" if (d.get("dept_store_yoy") or 0) >= 0 else ""
            sign_r = "+" if (d.get("retail_yoy") or 0) >= 0 else ""
            print(f"  {key}  dept={sign_d}{d.get('dept_store_yoy',0):.1f}%"
                  f"  retail={sign_r}{d.get('retail_yoy',0):.1f}%")

    # ── Write updated CSVs ────────────────────────────────────────────────
    if moea_data:
        dept_df   = pd.read_csv(RAW / "department_store_yoy.csv")
        retail_df = pd.read_csv(RAW / "retail_trade_yoy.csv")

        updated_dept   = 0
        updated_retail = 0
        for (y, m), d in moea_data.items():
            if not (2021 <= y <= 2025):
                continue   # skip out-of-range months (2026+)
            dm = (dept_df["year"]==y) & (dept_df["month"]==m)
            rm = (retail_df["year"]==y) & (retail_df["month"]==m)
            if dm.any() and d.get("dept_store_yoy") is not None:
                dept_df.loc[dm, "value"] = d["dept_store_yoy"]
                updated_dept += 1
            if rm.any() and d.get("retail_yoy") is not None:
                retail_df.loc[rm, "value"] = d["retail_yoy"]
                updated_retail += 1

        dept_df.to_csv(RAW/"department_store_yoy.csv",   index=False, encoding="utf-8-sig")
        retail_df.to_csv(RAW/"retail_trade_yoy.csv",     index=False, encoding="utf-8-sig")
        print(f"\nUpdated department_store_yoy.csv: {updated_dept} rows")
        print(f"Updated retail_trade_yoy.csv:      {updated_retail} rows")


if __name__ == "__main__":
    asyncio.run(main())
