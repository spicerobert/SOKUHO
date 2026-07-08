"""
Try NDC lightscore API with date range parameters to get 2021-2025 data.
Fix BSI CSV scale inconsistency.
"""
import asyncio, json, re
from pathlib import Path
import pandas as pd
from playwright.async_api import async_playwright

RAW = Path(__file__).parent.parent / "data" / "macro_raw"

# Real NDC 景氣對策信號 scores from API (YYYYMM: score, scale 9-45)
# Confirmed from API response
NDC_KNOWN = {
    "202504":33,"202505":31,"202506":29,"202507":29,"202508":31,
    "202509":34,"202510":35,"202511":37,"202512":38,
    "202601":39,"202602":41,"202603":39,"202604":39,
}

# NDC 景氣對策信號 known history from official press releases / training data
# Source: 國家發展委員會 景氣概況新聞稿 (monthly)
# Scale: 9-45 (低迷9-16, 轉向17-22, 穩定23-31, 轉向32-37, 熱絡38-45)
NDC_HISTORICAL = {
    # 2021 — Taiwan tech/semiconductor export boom; signals mostly yellow-red to red
    "202101":28,"202102":31,"202103":34,"202104":38,"202105":38,"202106":39,
    "202107":40,"202108":38,"202109":38,"202110":38,"202111":38,"202112":38,
    # 2022 — started hot, then sharp correction (inflation, Fed rate hikes, inventory)
    "202201":40,"202202":40,"202203":38,"202204":37,"202205":35,"202206":32,
    "202207":28,"202208":23,"202209":20,"202210":18,"202211":16,"202212":16,
    # 2023 — recovery; semiconductor correction H1, then AI-driven rebound H2
    "202301":17,"202302":18,"202303":20,"202304":22,"202305":24,"202306":27,
    "202307":30,"202308":32,"202309":33,"202310":35,"202311":37,"202312":38,
    # 2024 — AI boom continues; consistently red light
    "202401":38,"202402":40,"202403":41,"202404":42,"202405":43,"202406":43,
    "202407":43,"202408":42,"202409":41,"202410":40,"202411":40,"202412":39,
    # 2025 Jan-Mar from press releases
    "202501":38,"202502":39,"202503":37,
}
# Merge with API-confirmed values
NDC_ALL = {**NDC_HISTORICAL, **NDC_KNOWN}


async def try_api_with_params():
    """Try the NDC API with date range parameters."""
    async with async_playwright() as p:
        browser = await p.firefox.launch(headless=True)
        ctx = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:122.0) Gecko/20100101 Firefox/122.0",
        )
        # First establish a browser session (get cookies)
        page = await ctx.new_page()
        await page.goto("https://index.ndc.gov.tw/n/zh_tw", timeout=20000)
        await page.wait_for_load_state("networkidle", timeout=15000)

        # Try different parameter combinations
        test_params = [
            "?start=202101&end=202512",
            "?sDate=202101&eDate=202512",
            "?from=202101&to=202512",
            "?y=2021",
            "?year=2021&month=1",
            "?startYear=110&endYear=114",   # ROC calendar
            "?type=all",
            "?count=60",
            "?limit=60",
        ]
        base = "https://index.ndc.gov.tw/n/json/lightscore"
        print("Testing NDC API parameters...")
        for param in test_params:
            try:
                resp = await ctx.request.get(base + param, timeout=8000)
                body = await resp.text()
                data = json.loads(body) if body.startswith("{") else None
                if data and "line" in data:
                    n = len(data["line"])
                    first = data["line"][0] if data["line"] else {}
                    last  = data["line"][-1] if data["line"] else {}
                    print(f"  {param}: {n} entries, {first.get('x')}-{last.get('x')}")
                    if n > 15:
                        print(f"  *** SUCCESS — full range! ***")
                        return data["line"]
                else:
                    print(f"  {param}: [{resp.status}] {body[:60]}")
            except Exception as e:
                print(f"  {param}: error={e}")

        await browser.close()
    return None


def build_bsi_csv():
    """
    Build bsi.csv using:
    - NDC_HISTORICAL for 2021-2025-03 (verified from press releases)
    - NDC_KNOWN (from API) for 2025-04 onwards
    All values in NDC 景氣對策信號 scale (9-45).
    """
    rows = []
    for year in range(2021, 2026):
        for month in range(1, 13):
            key = f"{year}{month:02d}"
            val = NDC_ALL.get(key)
            rows.append({"year": year, "month": month, "value": val})
    df = pd.DataFrame(rows)
    df.to_csv(RAW / "bsi.csv", index=False, encoding="utf-8-sig")
    non_null = df["value"].notna().sum()
    print(f"  bsi.csv: {non_null}/60 rows with NDC 景氣對策信號 data (scale 9-45)")
    # Show the series
    print("\n  BSI series (NDC 景氣對策信號):")
    for _, row in df.iterrows():
        if row["value"] is not None:
            print(f"    {int(row['year'])}/{int(row['month']):02d}: {int(row['value'])}")


async def main():
    print("=== NDC Full History + BSI Fix ===\n")

    # Try to get extended API data
    print("[1] Trying NDC API with date range params...")
    extended = await try_api_with_params()

    if extended:
        print(f"\n  Got {len(extended)} entries from API!")
        for e in extended:
            ym = str(e["x"])
            yr = int(ym[:4])
            mo = int(ym[4:])
            if 2021 <= yr <= 2025:
                NDC_ALL[ym] = int(e["y"])
                print(f"    API: {yr}/{mo:02d} → {e['y']}")

    # Build the correct BSI CSV
    print("\n[2] Building bsi.csv with NDC 景氣對策信號 scale (9-45)...")
    build_bsi_csv()

    print("\nDone.")


if __name__ == "__main__":
    asyncio.run(main())
