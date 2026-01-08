# src/ipo_ml_screener/ipo.py
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from io import StringIO
from typing import Optional

import pandas as pd
import requests


BASE_URL = "https://stockanalysis.com/ipos"


@dataclass
class IPOFetchResult:
    df: pd.DataFrame
    source: str


def _normalize_ipo_table(df: pd.DataFrame) -> pd.DataFrame:
    """
    Normalize StockAnalysis IPO tables into:
      ticker, company, ipo_date, ipo_price (optional), exchange (optional)
    Column names on the site can vary a bit, so we do best-effort mapping.
    """
    if df is None or df.empty:
        return pd.DataFrame(columns=["ticker", "company", "ipo_date"])

    # Clean column names
    cols = {c: str(c).strip() for c in df.columns}
    df = df.rename(columns=cols)

    # Build a mapping by fuzzy matching
    col_lc = {c.lower(): c for c in df.columns}

    def pick(*candidates: str) -> Optional[str]:
        for cand in candidates:
            for k_lc, k in col_lc.items():
                if cand in k_lc:
                    return k
        return None

    ticker_col = pick("symbol", "ticker")
    company_col = pick("company", "name")
    date_col = pick("ipo date", "date")
    price_col = pick("ipo price", "price")
    exch_col = pick("exchange",)

    out = pd.DataFrame()
    if ticker_col:
        out["ticker"] = df[ticker_col].astype(str).str.strip()
    else:
        out["ticker"] = pd.NA

    if company_col:
        out["company"] = df[company_col].astype(str).str.strip()
    else:
        out["company"] = pd.NA

    if date_col:
        out["ipo_date"] = pd.to_datetime(df[date_col], errors="coerce")
    else:
        out["ipo_date"] = pd.NaT

    if price_col:
        # keep numeric if possible
        out["ipo_price"] = pd.to_numeric(df[price_col], errors="coerce")
    if exch_col:
        out["exchange"] = df[exch_col].astype(str).str.strip()

    # Drop rows without ticker or date
    out = out.dropna(subset=["ticker", "ipo_date"])
    out = out[out["ticker"].astype(str).str.len() > 0]

    # De-duplicate
    out = out.drop_duplicates(subset=["ticker"], keep="first")

    return out.reset_index(drop=True)


def fetch_recent_ipos(limit: int = 200, session: Optional[requests.Session] = None) -> IPOFetchResult:
    """
    Fetch last ~200 IPOs from StockAnalysis (https://stockanalysis.com/ipos/).
    Note: this page is limited to 200.
    """
    sess = session or requests.Session()
    r = sess.get(BASE_URL, timeout=30)
    r.raise_for_status()

    tables = pd.read_html(StringIO(r.text))
    if not tables:
        return IPOFetchResult(pd.DataFrame(columns=["ticker", "company", "ipo_date"]), "recent")

    df = _normalize_ipo_table(tables[0])
    df = df.sort_values("ipo_date", ascending=False).head(limit).reset_index(drop=True)
    return IPOFetchResult(df, "recent")


def fetch_ipos_by_year(year: int, session: Optional[requests.Session] = None) -> IPOFetchResult:
    """
    Fetch all IPOs for a given year from StockAnalysis:
      https://stockanalysis.com/ipos/<year>/
    """
    url = f"{BASE_URL}/{year}/"
    sess = session or requests.Session()
    r = sess.get(url, timeout=30)
    r.raise_for_status()

    tables = pd.read_html(StringIO(r.text))
    if not tables:
        return IPOFetchResult(pd.DataFrame(columns=["ticker", "company", "ipo_date"]), f"year:{year}")

    # First table is typically the list
    df = _normalize_ipo_table(tables[0])
    df = df.sort_values("ipo_date", ascending=False).reset_index(drop=True)
    return IPOFetchResult(df, f"year:{year}")


def fetch_ipos_since(
    start_date: str,
    limit: Optional[int] = None,
    session: Optional[requests.Session] = None,
) -> IPOFetchResult:
    """
    Fetch IPOs from start_date (YYYY-MM-DD) to now using year pages.
    Example: start_date="2024-01-01"
    """
    start_dt = pd.to_datetime(start_date).to_pydatetime()
    now_year = datetime.now().year
    sess = session or requests.Session()

    frames = []
    for y in range(start_dt.year, now_year + 1):
        try:
            frames.append(fetch_ipos_by_year(y, session=sess).df)
        except Exception:
            # If a year page fails, just skip it (robustness).
            continue

    if not frames:
        return IPOFetchResult(pd.DataFrame(columns=["ticker", "company", "ipo_date"]), f"since:{start_date}")

    df = pd.concat(frames, ignore_index=True)
    df = df.dropna(subset=["ticker", "ipo_date"]).drop_duplicates(subset=["ticker"], keep="first")

    df = df[df["ipo_date"] >= pd.Timestamp(start_dt)]
    df = df.sort_values("ipo_date", ascending=False).reset_index(drop=True)

    if limit is not None:
        df = df.head(limit).reset_index(drop=True)

    return IPOFetchResult(df, f"since:{start_date}")
