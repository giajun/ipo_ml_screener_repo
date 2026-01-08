from __future__ import annotations
from dataclasses import dataclass
from functools import lru_cache
from typing import Any
import os
import re
import time
import pandas as pd
import requests


SEC_TICKER_CIK_URL = "https://www.sec.gov/files/company_tickers.json"
SEC_COMPANYFACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik10}.json"
SEC_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik10}.json"

# You MUST set a descriptive User-Agent per SEC guidance.
DEFAULT_UA = os.environ.get("SEC_USER_AGENT", "IPO-ML-Screener your.email@example.com")


class _RateLimiter:
    """Very small per-process rate limiter for SEC endpoints.

    SEC requests that automated requests remain under a reasonable rate; this
    limiter defaults to ~8 requests/sec.
    """

    def __init__(self, max_rps: float = 8.0):
        self.min_interval = 1.0 / max_rps if max_rps > 0 else 0.0
        self._last = 0.0

    def wait(self) -> None:
        if self.min_interval <= 0:
            return
        now = time.time()
        dt = now - self._last
        if dt < self.min_interval:
            time.sleep(self.min_interval - dt)
        self._last = time.time()


_rl = _RateLimiter()


def _sec_get_json(url: str) -> dict | None:
    _rl.wait()
    r = requests.get(url, timeout=30, headers={"User-Agent": DEFAULT_UA})
    if r.status_code != 200:
        return None
    try:
        return r.json()
    except Exception:
        return None


@lru_cache(maxsize=1)
def load_ticker_cik_map() -> dict:
    data = _sec_get_json(SEC_TICKER_CIK_URL)
    if not data:
        return {}
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
    return _sec_get_json(url)


def fetch_company_submissions(ticker: str) -> dict | None:
    """Fetch SEC submissions JSON (filings index) for a ticker."""
    cik = ticker_to_cik(ticker)
    if cik is None:
        return None
    url = SEC_SUBMISSIONS_URL.format(cik10=_cik10(cik))
    return _sec_get_json(url)


def extract_filing_meta(ticker: str) -> dict:
    """Return lightweight filing metadata useful for dashboards and sanity checks."""
    sub = fetch_company_submissions(ticker)
    if not sub:
        return {}

    recent = (sub.get("filings", {}) or {}).get("recent", {}) or {}
    forms = recent.get("form", []) or []
    filing_dates = recent.get("filingDate", []) or []

    def _latest_form_date(target_forms: set[str]) -> str | None:
        best = None
        for f, d in zip(forms, filing_dates):
            if f in target_forms and d:
                if best is None or str(d) > str(best):
                    best = d
        return str(best) if best is not None else None

    latest_any = str(filing_dates[0]) if filing_dates else None
    latest_10q = _latest_form_date({"10-Q"})
    latest_10k = _latest_form_date({"10-K"})

    return {
        "latest_filing_date": latest_any,
        "latest_10q_date": latest_10q,
        "latest_10k_date": latest_10k,
        "has_10q": latest_10q is not None,
        "has_10k": latest_10k is not None,
    }


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
