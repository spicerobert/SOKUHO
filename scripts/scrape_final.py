"""
Final production scraper — Webwright-style iterative approach.

Targets:
  dept_store_yoy.csv / retail_trade_yoy.csv ← MOEA bulletin (Playwright)
  bsi.csv                                    ← NDC 景氣對策信號 (Playwright)

MOEA: use full browser rendering, collect bull_ids from filter,
      navigate each bulletin and extract YoY% from rendered text.
NDC:  navigate table, find year-range control, extract full history.
"""

from __future__ import annotations
import asyncio, re
from pathlib import Path

import pandas as pd
from playwright.async_api import async_playwright, Page

RAW = Path(__file__).parent.parent / "data" / "macro_raw"
SS  = Path(__file__).parent.parent / "outputs" / "macro_scrape_screenshots"
SS.mkdir(parents=True, exist_ok=True)

BASE = "https://www.moea.gov.tw/MNS/dos"


# ── Parse MOEA bulletin rendered text ────────────────────────────────────
def parse_moea_text(text: str) -> dict:
    """Extract year/month and YoY% from rendered bulletin text."""
    r: dict = {}
    hdr = re.search(r"(\d{3})年(\d{1,2})月批發", text)
    if hdr:
        r["year"]  = 1911 + int(hdr.group(1))
        r["month"] = int(hdr.group(2))

    def _pct(pat: str) -> float | None:
        m = re.search(pat, text)
        if not m:
            return None
        v = float(m.group(1))
        ctx = text[max(0, m.start()-8): m.end()+10]
        return -v if "年減" in ctx else v

    r["dept"]   = _pct(r"百貨公司年[增減](\d+\.?\d*)%")
    r["retail"] = _pct(r"零售業營業額[^。]{0,100}?年[增減](\d+\.?\d*)%")
    return r


# ── MOEA scraper ──────────────────────────────────────────────────────────
async def scrape_moea(page: Page) -> dict[tuple[int,int], dict]:
    """
    1. Load MOEA bulletin list, iterate date filter options.
    2. For each option, find bull_id(s) in the rendered HTML.
    3. Navigate to each bulletin, extract text, parse YoY%.
    """
    results: dict[tuple[int,int], dict] = {}
    list_url = f"{BASE}/bulletin/Bulletin.aspx?kind=8&html=1&menu_id=6727"

    print("[MOEA] Loading bulletin list...")
    await page.goto(list_url, timeout=30000)
    await page.wait_for_load_state("networkidle", timeout=20000)
    await page.screenshot(path=str(SS / "moea_list.png"))

    # -- Collect all bull_ids from each filter option ----------------------
    sels = await page.query_selector_all("select")
    if not sels:
        print("  [!] No select found")
        return results

    opts = await sels[0].query_selector_all("option")
    date_opts = []
    for o in opts:
        v = (await o.get_attribute("value") or "").strip()
        if re.match(r"\d{4}-\d{2}", v):
            date_opts.append(v)
    print(f"  Filter options ({len(date_opts)}): {date_opts[:6]}...{date_opts[-3:]}")

    all_bull_ids: list[int] = []
    for dt in date_opts:
        # Re-get select (page might have re-rendered)
        sels2 = await page.query_selector_all("select")
        if not sels2:
            break
        await sels2[0].select_option(dt)
        # Wait for table to refresh via network response
        try:
            await page.wait_for_load_state("networkidle", timeout=8000)
        except Exception:
            await page.wait_for_timeout(2000)

        html = await page.content()
        ids  = re.findall(r"bull_id=(\d+)", html)
        new  = [int(x) for x in ids if int(x) > 10000 and int(x) not in all_bull_ids]
        all_bull_ids.extend(new)

    # Also grab from unfiltered list (reload without filter)
    await page.goto(list_url, timeout=30000)
    await page.wait_for_load_state("networkidle", timeout=15000)
    html0 = await page.content()
    for x in re.findall(r"bull_id=(\d+)", html0):
        if int(x) > 10000 and int(x) not in all_bull_ids:
            all_bull_ids.append(int(x))

    all_bull_ids = sorted(set(all_bull_ids), reverse=True)
    print(f"\n  Found {len(all_bull_ids)} unique bull_ids: {all_bull_ids[:5]}...{all_bull_ids[-3:]}")

    # -- Navigate to each bulletin and extract data -----------------------
    print("\n  Fetching each bulletin...")
    for bid in all_bull_ids:
        url = f"{BASE}/bulletin/Bulletin.aspx?kind=8&html=1&menu_id=6727&bull_id={bid}"
        try:
            await page.goto(url, timeout=20000)
            await page.wait_for_load_state("networkidle", timeout=12000)
            text = await page.evaluate("document.body.innerText")
            if len(text) < 400 or "批發" not in text:
                continue
            d = parse_moea_text(text)
            if not d.get("year") or d.get("dept") is None:
                continue
            key = (d["year"], d["month"])
            if key not in results:
                results[key] = d
                sign_d = "+" if (d["dept"] or 0) >= 0 else ""
                sign_r = "+" if (d.get("retail") or 0) >= 0 else ""
                print(f"  {key[0]}/{key[1]:02d}  "
                      f"dept={sign_d}{d['dept']:.1f}%  "
                      f"retail={sign_r}{d.get('retail',0):.1f}%  "
                      f"[bull_id={bid}]")
        except Exception as e:
            print(f"  [bull_id={bid}] error: {e}")

    # -- Try scanning older IDs (2021-2024 period) -----------------------
    if all_bull_ids:
        oldest = min(all_bull_ids)
        print(f"\n  Scanning older IDs (below {oldest})...")
        await _scan_older_ids(page, oldest, results)

    return results


async def _scan_older_ids(page: Page, oldest_id: int,
                           results: dict) -> None:
    """
    Scan bulletin IDs below the oldest known.
    Use step 2 for efficiency; MOEA retail bulletins appear every ~15-25 IDs.
    """
    target_months = {(y, m) for y in range(2021, 2025) for m in range(1, 13)}
    target_months -= {(2024, m) for m in range(6, 13)}  # already covered by filter

    scan_limit = oldest_id - 1200   # ~60 months × avg 20 IDs/month
    for bid in range(oldest_id - 1, scan_limit, -2):
        if not target_months - set(results.keys()):
            break  # all target months found
        url = f"{BASE}/bulletin/Bulletin.aspx?kind=8&html=1&menu_id=6727&bull_id={bid}"
        try:
            await page.goto(url, timeout=15000)
            await page.wait_for_load_state("networkidle", timeout=8000)
            text = await page.evaluate("document.body.innerText")
            if len(text) < 400 or "批發" not in text or "年增" not in text:
                continue
            d = parse_moea_text(text)
            if not d.get("year") or d.get("dept") is None:
                continue
            key = (d["year"], d["month"])
            if key in results:
                continue
            results[key] = d
            sign_d = "+" if (d["dept"] or 0) >= 0 else ""
            sign_r = "+" if (d.get("retail") or 0) >= 0 else ""
            print(f"  {key[0]}/{key[1]:02d}  "
                  f"dept={sign_d}{d['dept']:.1f}%  "
                  f"retail={sign_r}{d.get('retail', 0):.1f}%  "
                  f"[bull_id={bid}]")
            if key <= (2021, 1):
                print("  Reached Jan 2021!")
                break
        except Exception:
            pass


# ── NDC 景氣對策信號 scraper ──────────────────────────────────────────────
async def scrape_ndc_bsi(page: Page) -> list[dict]:
    """
    Navigate NDC 景氣指標 table, extract 景氣對策信號(分) monthly scores.
    Scores range 9-45; we use them directly as BSI in the DB.
    """
    rows = []
    print("\n[NDC] Scraping 景氣對策信號...")
    ndc_url = "https://index.ndc.gov.tw/n/zh_tw/page/composite_index_table"

    try:
        await page.goto(ndc_url, timeout=30000)
        await page.wait_for_load_state("networkidle", timeout=25000)
        await page.screenshot(path=str(SS / "ndc_01.png"))

        # -- Look for year/period range controls -------------------------
        sels = await page.query_selector_all("select")
        inputs = await page.query_selector_all("input[type=text], input[type=number]")
        btns   = await page.query_selector_all("button")
        print(f"  selects={len(sels)}, inputs={len(inputs)}, buttons={len(btns)}")

        for sel in sels:
            opts = await sel.query_selector_all("option")
            vals = [(await o.get_attribute("value") or "").strip() for o in opts[:8]]
            print(f"  select options: {vals}")

        for btn in btns:
            t = (await btn.inner_text()).strip()
            if t:
                print(f"  button: [{t}]")

        # -- Try "用表格檢視" (switch to table view) ----------------------
        table_btn = None
        for btn in btns:
            t = (await btn.inner_text()).strip()
            if "表格" in t or "table" in t.lower():
                table_btn = btn
                break
        if table_btn:
            print("  Clicking table view button...")
            await table_btn.click()
            await page.wait_for_timeout(3000)
            await page.screenshot(path=str(SS / "ndc_02_table.png"))

        # -- Try to load older data via year selector or date inputs ------
        # NDC often has start/end date inputs like "民國年" (ROC calendar)
        year_inputs = await page.query_selector_all(
            "input[placeholder*='年'], input[name*='year'], input[id*='year'], "
            "input[placeholder*='民國'], input[id*='start'], input[name*='start']"
        )
        print(f"  Year-like inputs: {len(year_inputs)}")

        if year_inputs:
            # Set start year to 110 (ROC 110 = 2021)
            await year_inputs[0].triple_click()
            await year_inputs[0].fill("110")
            if len(year_inputs) > 1:
                await year_inputs[1].triple_click()
                await year_inputs[1].fill("113")  # end ROC 113 = 2024
            # Click search/confirm button
            for btn in btns:
                t = (await btn.inner_text()).strip()
                if any(kw in t for kw in ["查詢","搜尋","確認","送出","search","Search"]):
                    await btn.click()
                    await page.wait_for_timeout(3000)
                    await page.screenshot(path=str(SS / "ndc_03_range.png"))
                    break

        # -- Extract table data ------------------------------------------
        tbl_rows = await page.query_selector_all("table tr")
        print(f"  Table rows: {len(tbl_rows)}")
        raw_pairs: list[tuple[str, int]] = []
        for row in tbl_rows:
            cells = await row.query_selector_all("td, th")
            cell_texts = [(await c.inner_text()).strip() for c in cells]
            # Look for rows with date (YYYY-MM or ROC format) + score
            if len(cell_texts) >= 2:
                date_col = cell_texts[0]
                # Match "2025-05" or "110/01" or "110年01月"
                dm = re.match(r"(20\d{2})-(\d{2})|(\d{3})[/年](\d{2})", date_col)
                if dm:
                    if dm.group(1):  # Western YYYY-MM
                        yr, mo = int(dm.group(1)), int(dm.group(2))
                    else:            # ROC YYY/MM
                        yr, mo = 1911 + int(dm.group(3)), int(dm.group(4))
                    # Find score column (integer 9-45)
                    for ct in cell_texts[1:]:
                        ct_clean = ct.strip().replace(",", "")
                        if re.fullmatch(r"\d{1,2}", ct_clean):
                            score = int(ct_clean)
                            if 9 <= score <= 45:
                                raw_pairs.append((f"{yr}-{mo:02d}", score))
                                break

        print(f"  Extracted {len(raw_pairs)} date-score pairs")
        for dp, sc in raw_pairs[:12]:
            print(f"    {dp}: {sc}")

        # -- If table still shows too few rows, try page text extraction --
        if len(raw_pairs) < 20:
            print("\n  Trying text extraction from page body...")
            text = await page.evaluate("document.body.innerText")
            # Pattern: "2021-01\t\t\n\t31"  or "年月\t景氣對策信號"
            # Try to find embedded JSON or chart data
            scripts = await page.query_selector_all("script:not([src])")
            for sc in scripts:
                src = await sc.inner_text()
                # Look for arrays: [33, 31, 29, ...]
                arrays = re.findall(r"\[(\d{2}(?:,\s*\d{2}){10,})\]", src)
                labels = re.findall(r'"(1[01]\d/\d{2})"', src)
                if arrays and labels:
                    scores = [int(x) for x in arrays[0].split(",")]
                    print(f"  Script: {len(scores)} scores, {len(labels)} labels")
                    for lbl, sc_val in zip(labels, scores):
                        roc_yr, mo = lbl.split("/")
                        yr = 1911 + int(roc_yr)
                        raw_pairs.append((f"{yr}-{mo}", sc_val))
                    break

            # Also look for the chart data blob we saw earlier
            # "景氣對策信號及分數333129..." followed by "2025/032025/05..."
            m_blob = re.search(
                r"景氣對策信號及分數((?:\d{2})+)((?:20\d{2}/\d{2})+)", text.replace("\n","").replace(" ","")
            )
            if m_blob:
                score_blob = m_blob.group(1)
                date_blob  = m_blob.group(2)
                scores_b = [int(score_blob[i:i+2]) for i in range(0, len(score_blob), 2)]
                dates_b  = re.findall(r"20\d{2}/\d{2}", date_blob)
                print(f"  Chart blob: {len(scores_b)} scores, {len(dates_b)} dates")
                for d_str, sc_val in zip(dates_b, scores_b):
                    if 9 <= sc_val <= 45:
                        yr_s, mo_s = d_str.split("/")
                        raw_pairs.append((f"{yr_s}-{mo_s}", sc_val))

        # Deduplicate and sort
        seen = {}
        for d_str, sc in raw_pairs:
            if d_str not in seen:
                seen[d_str] = sc
        raw_pairs = sorted(seen.items())
        print(f"\n  Final: {len(raw_pairs)} unique data points")
        for d_str, sc in raw_pairs:
            print(f"    {d_str}: {sc}")

        # Convert to rows
        for d_str, score in raw_pairs:
            m_d = re.match(r"(\d{4})-(\d{2})", d_str)
            if m_d:
                yr, mo = int(m_d.group(1)), int(m_d.group(2))
                if 2021 <= yr <= 2025:
                    rows.append({"year": yr, "month": mo, "value": score})

    except Exception as e:
        print(f"  NDC error: {e}")
        await page.screenshot(path=str(SS / "ndc_error.png"))

    return rows


# ── Main ──────────────────────────────────────────────────────────────────
async def main():
    print("=== Final scraper: MOEA dept_store + NDC BSI ===\n")

    async with async_playwright() as p:
        browser = await p.firefox.launch(headless=True)
        ctx = await browser.new_context(
            viewport={"width": 1280, "height": 900},
            locale="zh-TW",
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:122.0) "
                "Gecko/20100101 Firefox/122.0"
            ),
        )
        page = await ctx.new_page()

        # ── MOEA ──────────────────────────────────────────────────────────
        moea = await scrape_moea(page)

        # ── NDC ───────────────────────────────────────────────────────────
        ndc  = await scrape_ndc_bsi(page)

        await browser.close()

    # ── Update CSVs ───────────────────────────────────────────────────────
    print(f"\n{'='*60}")
    print(f"MOEA entries collected: {len(moea)}")
    print(f"NDC  entries collected: {len(ndc)}")

    # dept_store_yoy + retail_trade_yoy
    in_range = {k: v for k, v in moea.items() if 2021 <= k[0] <= 2025}
    if in_range:
        dept_df   = pd.read_csv(RAW / "department_store_yoy.csv")
        retail_df = pd.read_csv(RAW / "retail_trade_yoy.csv")
        upd_d = upd_r = 0
        for (y, m), d in in_range.items():
            dm = (dept_df["year"] == y) & (dept_df["month"] == m)
            rm = (retail_df["year"] == y) & (retail_df["month"] == m)
            if dm.any() and d.get("dept") is not None:
                dept_df.loc[dm, "value"] = round(d["dept"], 2)
                upd_d += 1
            if rm.any() and d.get("retail") is not None:
                retail_df.loc[rm, "value"] = round(d["retail"], 2)
                upd_r += 1
        dept_df.to_csv(RAW / "department_store_yoy.csv", index=False, encoding="utf-8-sig")
        retail_df.to_csv(RAW / "retail_trade_yoy.csv",   index=False, encoding="utf-8-sig")
        print(f"\nUpdated department_store_yoy.csv: {upd_d} rows replaced")
        print(f"Updated retail_trade_yoy.csv:      {upd_r} rows replaced")
    else:
        print("\nNo in-range MOEA data collected.")

    # bsi
    if ndc:
        bsi_df = pd.read_csv(RAW / "bsi.csv")
        upd_b = 0
        for row in ndc:
            y, m, sc = row["year"], row["month"], row["value"]
            bm = (bsi_df["year"] == y) & (bsi_df["month"] == m)
            if bm.any():
                bsi_df.loc[bm, "value"] = sc
                upd_b += 1
        bsi_df.to_csv(RAW / "bsi.csv", index=False, encoding="utf-8-sig")
        print(f"Updated bsi.csv: {upd_b} rows replaced (NDC 景氣對策信號, scale 9-45)")
    else:
        print("No NDC BSI data collected.")

    print("\nDone.")


if __name__ == "__main__":
    asyncio.run(main())
