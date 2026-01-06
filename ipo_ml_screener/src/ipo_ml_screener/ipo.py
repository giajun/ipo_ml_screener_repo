from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timezone
import pandas as pd
import requests


STOCKANALYSIS_IPO_URL = "https://stockanalysis.com/ipos/"


def fetch_recent_ipos_stockanalysis(url: str = STOCKANALYSIS_IPO_URL) -> pd.DataFrame:
    # StockAnalysis renders a HTML table; pandas can usually parse it via read_html.
    # We keep it robust by using requests -> text -> read_html.
    r = requests.get(url, timeout=30, headers={"User-Agent": "Mozilla/5.0"})
    r.raise_for_status()
    tables = pd.read_html(r.text)
    # Usually the first big table is the IPO list.
    df = tables[0].copy()
    # Normalize columns
    df.columns = [str(c).strip().lower().replace(" ", "_") for c in df.columns]
    # expected: date, symbol, name, ipo_price, current_price, return, ...
    if "symbol" in df.columns and "ticker" not in df.columns:
        df = df.rename(columns={"symbol": "ticker"})
    if "date" in df.columns:
        df["ipo_date"] = pd.to_datetime(df["date"], errors="coerce").dt.date
    elif "ipo_date" not in df.columns:
        df["ipo_date"] = pd.NaT
    if "name" not in df.columns and "company" in df.columns:
        df = df.rename(columns={"company": "name"})
    return df


def filter_ipos_by_age(df: pd.DataFrame, days_since_ipo: int) -> pd.DataFrame:
    today = datetime.now(timezone.utc).date()
    d = df.copy()
    d["ipo_date"] = pd.to_datetime(d.get("ipo_date"), errors="coerce").dt.date
    d["days_since_ipo"] = d["ipo_date"].apply(lambda x: (today - x).days if pd.notna(x) else None)
    d = d[d["days_since_ipo"].notna()]
    d = d[d["days_since_ipo"] <= days_since_ipo]
    return d
