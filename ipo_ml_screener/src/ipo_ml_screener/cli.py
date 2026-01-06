from __future__ import annotations
import argparse
from datetime import datetime, timezone
import pandas as pd

from ipo_ml_screener.config import load_config
from ipo_ml_screener.ipo import fetch_recent_ipos_stockanalysis, filter_ipos_by_age
from ipo_ml_screener.market import get_price_history, get_quote_info, compute_momentum_features
from ipo_ml_screener.sec import compute_financial_metrics
from ipo_ml_screener.scoring import score_hard_gates
from ipo_ml_screener.io_utils import save_scores


def refresh(days_since_ipo: int, limit: int | None = None) -> pd.DataFrame:
    cfg = load_config()
    # IPO list
    ipos = fetch_recent_ipos_stockanalysis(cfg["ipo"]["url"])
    ipos = filter_ipos_by_age(ipos, days_since_ipo=days_since_ipo)
    if limit:
        ipos = ipos.head(limit)

    rows = []
    for _, r in ipos.iterrows():
        ticker = str(r.get("ticker", "")).upper().strip()
        if not ticker:
            continue

        name = r.get("name") or r.get("company") or ""
        ipo_date = r.get("ipo_date")

        # Market
        hist = get_price_history(ticker, period="2y")
        mom = compute_momentum_features(hist, cfg["momentum"])
        qi = get_quote_info(ticker)

        # Liquidity proxy: avg dollar volume 20d (Close*Volume)
        avg_dv = None
        if hist is not None and not hist.empty and "Close" in hist.columns and "Volume" in hist.columns:
            tail = hist.tail(20)
            if len(tail) >= 5:
                avg_dv = float((tail["Close"] * tail["Volume"]).mean())

        # SEC fundamentals
        fin = compute_financial_metrics(ticker)

        row = {
            "ticker": ticker,
            "name": name,
            "ipo_date": str(ipo_date) if pd.notna(ipo_date) else None,
            "days_since_ipo": int(r.get("days_since_ipo")) if pd.notna(r.get("days_since_ipo")) else None,
            "price": qi.get("last_price") or qi.get("last_price"),
            "market_cap": qi.get("market_cap"),
            "shares_outstanding": qi.get("shares_outstanding") or qi.get("shares"),
            "avg_dollar_vol_20d": avg_dv,
            **mom,
            **fin,
        }

        score = score_hard_gates(row, cfg)
        row.update(score)
        rows.append(row)

    out = pd.DataFrame(rows)
    return out


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("refresh", help="Download/update data and compute scores")
    r.add_argument("--days-since-ipo", type=int, default=365)
    r.add_argument("--limit", type=int, default=120)

    args = ap.parse_args()
    cfg = load_config()

    if args.cmd == "refresh":
        df = refresh(days_since_ipo=args.days_since_ipo, limit=args.limit)
        save_scores(df, cfg["output"]["processed_path"])
        print(f"Saved: {cfg['output']['processed_path']} ({len(df)} rows)")


if __name__ == "__main__":
    main()
