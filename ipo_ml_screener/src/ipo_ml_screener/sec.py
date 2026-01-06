from __future__ import annotations
from dataclasses import dataclass
from functools import lru_cache
from typing import Any
import os
import re
import pandas as pd
import requests


SEC_TICKER_CIK_URL = "https://www.sec.gov/files/company_tickers.json"
SEC_COMPANYFACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik10}.json"

# You MUST set a descriptive User-Agent per SEC guidance.
DEFAULT_UA = os.environ.get("SEC_USER_AGENT", "IPO-ML-Screener your.email@example.com")


@lru_cache(maxsize=1)
def load_ticker_cik_map() -> dict:
    r = requests.get(SEC_TICKER_CIK_URL, timeout=30, headers={"User-Agent": DEFAULT_UA})
    r.raise_for_status()
    data = r.json()
    # Format is dict keyed by integer strings: {"0": {"cik_str":..., "ticker":..., "title":...}, ...}
    out = {}
    for _, v in data.items():
        t = str(v.get("ticker", "")).upper()
        if not t:
            continue
        out[t] = int(v.get("cik_str"))
    return out


def ticker_to_cik(ticker: str) -> int | None:
    m = load_ticker_cik_map()
    return m.get(ticker.upper())


def _cik10(cik: int) -> str:
    return str(cik).zfill(10)


def fetch_company_facts(ticker: str) -> dict | None:
    cik = ticker_to_cik(ticker)
    if cik is None:
        return None
    url = SEC_COMPANYFACTS_URL.format(cik10=_cik10(cik))
    r = requests.get(url, timeout=30, headers={"User-Agent": DEFAULT_UA})
    if r.status_code != 200:
        return None
    return r.json()


def extract_latest_usd_series(facts: dict, taxonomy: str, tag: str) -> pd.DataFrame:
    # Returns dataframe with columns: end, val, fy, fp, form
    try:
        units = facts["facts"][taxonomy][tag]["units"]
    except Exception:
        return pd.DataFrame()

    # Prefer USD if available
    key = "USD" if "USD" in units else next(iter(units.keys()), None)
    if key is None:
        return pd.DataFrame()

    rows = units[key]
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    # normalize dates
    if "end" in df.columns:
        df["end"] = pd.to_datetime(df["end"], errors="coerce")
    return df.sort_values("end")


def latest_value(facts: dict, taxonomy: str, tag: str) -> float | None:
    df = extract_latest_usd_series(facts, taxonomy, tag)
    if df.empty:
        return None
    # prefer 10-Q/10-K over others
    if "form" in df.columns:
        pref = df[df["form"].isin(["10-Q", "10-K"])]
        if not pref.empty:
            df = pref
    df = df.dropna(subset=["end", "val"])
    if df.empty:
        return None
    return float(df.iloc[-1]["val"])


def compute_financial_metrics(ticker: str) -> dict:
    facts = fetch_company_facts(ticker)
    if not facts:
        return {}

    # Common tags (may be absent depending on filer)
    cash = latest_value(facts, "us-gaap", "CashAndCashEquivalentsAtCarryingValue")
    rev = latest_value(facts, "us-gaap", "Revenues")
    gp = latest_value(facts, "us-gaap", "GrossProfit")
    cfo = latest_value(facts, "us-gaap", "NetCashProvidedByUsedInOperatingActivities")
    capex = latest_value(facts, "us-gaap", "PaymentsToAcquirePropertyPlantAndEquipment")
    sbc = latest_value(facts, "us-gaap", "ShareBasedCompensation")

    # simple derived
    fcf = None
    if cfo is not None and capex is not None:
        fcf = float(cfo) - float(capex)

    gross_margin = None
    if gp is not None and rev not in (None, 0):
        gross_margin = float(gp) / float(rev)

    sbc_to_rev = None
    if sbc is not None and rev not in (None, 0):
        sbc_to_rev = float(sbc) / float(rev)

    # YoY revenue growth (quarterly) if possible:
    yoy_growth = None
    rev_df = extract_latest_usd_series(facts, "us-gaap", "Revenues")
    if not rev_df.empty and "end" in rev_df.columns and "val" in rev_df.columns:
        # Try to compute latest quarter vs same quarter last year using end date matching by month/day proximity.
        rev_df = rev_df[rev_df.get("form").isin(["10-Q","10-K"])].dropna(subset=["end","val"])
        if len(rev_df) >= 5:
            latest = rev_df.iloc[-1]
            end_latest = latest["end"]
            # find closest record ~1 year earlier (330-400 days)
            target_min = end_latest - pd.Timedelta(days=400)
            target_max = end_latest - pd.Timedelta(days=330)
            prior = rev_df[(rev_df["end"] >= target_min) & (rev_df["end"] <= target_max)]
            if not prior.empty:
                prev = prior.iloc[-1]
                prev_val = float(prev["val"])
                if prev_val != 0:
                    yoy_growth = float(latest["val"]) / prev_val - 1.0

    # Cash runway months (rough): cash / monthly burn, where burn = -CFO if CFO<0 else 0
    runway_months = None
    if cash is not None and cfo is not None and cfo < 0:
        monthly_burn = abs(float(cfo)) / 3.0  # assume quarterly CFO
        runway_months = float(cash) / monthly_burn if monthly_burn > 0 else None

    return {
        "cash": cash,
        "revenue": rev,
        "gross_profit": gp,
        "gross_margin": gross_margin,
        "cfo": cfo,
        "capex": capex,
        "fcf": fcf,
        "sbc": sbc,
        "sbc_to_revenue": sbc_to_rev,
        "yoy_revenue_growth": yoy_growth,
        "cash_runway_months": runway_months,
    }
