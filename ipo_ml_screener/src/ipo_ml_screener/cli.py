# src/ipo_ml_screener/cli.py
from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from ipo_ml_screener.ipo import fetch_ipos_since, fetch_recent_ipos
from ipo_ml_screener.market import compute_price_summary, get_price_history, is_equity_like
from ipo_ml_screener.momentum import compute_momentum_flags
from ipo_ml_screener.scoring import compute_hard_gates, compute_total_score
from ipo_ml_screener.sec import (
    ticker_to_cik,
    compute_financial_metrics,
    extract_filing_meta,
)


def _load_existing(out_path: Path) -> pd.DataFrame:
    if out_path.exists():
        try:
            return pd.read_parquet(out_path)
        except Exception:
            return pd.DataFrame()
    return pd.DataFrame()


def refresh(
    days_since_ipo: int,
    limit: int,
    start_date: str | None,
    batch_size: int,
    resume: bool,
    out: str,
) -> None:
    """
    Incremental pipeline:
      - Fetch IPO universe
      - If resume: skip already-processed tickers from existing parquet
      - Process only next batch_size tickers
      - Append + dedupe + save parquet
    """
    out_path = Path(out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    # 0) load existing scores (optional)
    existing = _load_existing(out_path) if resume else pd.DataFrame()
    processed = set(existing["ticker"].astype(str).str.upper()) if (resume and not existing.empty and "ticker" in existing.columns) else set()

    # 1) IPO universe
    if start_date:
        ipos_res = fetch_ipos_since(start_date=start_date, limit=limit)
    else:
        ipos_res = fetch_recent_ipos(limit=min(limit, 200))  # recent page limited anyway
    ipos = ipos_res.df.copy()

    if ipos.empty:
        print("No IPOs fetched.")
        return

    ipos["ipo_date"] = pd.to_datetime(ipos["ipo_date"], errors="coerce")
    ipos = ipos.dropna(subset=["ipo_date", "ticker"]).reset_index(drop=True)
    ipos["ticker"] = ipos["ticker"].astype(str).str.strip().str.upper()

    # When start_date is NOT used, keep days_since_ipo as a universe limiter
    if not start_date and days_since_ipo is not None:
        now = pd.Timestamp.utcnow().tz_localize(None)
        ipos["days_since_ipo"] = (now - ipos["ipo_date"]).dt.days.astype("int64")
        ipos = ipos[ipos["days_since_ipo"] <= days_since_ipo].reset_index(drop=True)

    # 2) resume skip
    if processed:
        ipos = ipos[~ipos["ticker"].isin(processed)].reset_index(drop=True)

    if ipos.empty:
        print("No remaining tickers to process.")
        return

    # 3) take next batch (oldest first to prioritize stocks with trading history)
    ipos = ipos.sort_values("ipo_date", ascending=True).head(batch_size).reset_index(drop=True)

    rows: list[dict] = []
    now = pd.Timestamp.utcnow().tz_localize(None)

    for _, r in ipos.iterrows():
        ticker = str(r["ticker"]).strip().upper()
        company = str(r.get("company", "")).strip()
        ipo_date = pd.to_datetime(r["ipo_date"]).to_pydatetime()

        # Quick non-equity filter
        if not is_equity_like(ticker):
            continue

        # Market data
        hist = get_price_history(ticker, period="2y", interval="1d")
        if hist is None or hist.empty:
            continue

        ps = compute_price_summary(ticker, hist)
        mom = compute_momentum_flags(hist)

        # SEC data (best-effort)
        cik = ticker_to_cik(ticker)

        sec_metrics = {}
        sec_meta = {}
        if cik:
            try:
                sec_metrics = compute_financial_metrics(ticker)
            except Exception:
                sec_metrics = {}
            try:
                sec_meta = extract_filing_meta(ticker)
            except Exception:
                sec_meta = {}

        hard = compute_hard_gates(
            price_summary=ps,
            sec_metrics=sec_metrics,
            days_since_ipo=int((now - pd.Timestamp(ipo_date)).days),
        )
        score = compute_total_score(
            hard_gates=hard,
            momentum=mom,
            price_summary=ps,
            sec_metrics=sec_metrics,
        )

        row = {
            "ticker": ticker,
            "company": company,
            "ipo_date": pd.Timestamp(ipo_date),
            "days_since_ipo": int((now - pd.Timestamp(ipo_date)).days),
            # Market
            "last_close": ps.last_close,
            "avg_dollar_vol_20d": ps.avg_dollar_vol_20d,
            "market_cap": ps.market_cap,
            "currency": ps.currency,
            # Momentum flags
            **{f"mom_{k}": v for k, v in mom.items()},
            "pass_momentum": bool(mom.get("pass_momentum", False)),
            # SEC / fundamentals (metrics)
            **sec_metrics,
            # SEC meta (filings)
            **sec_meta,
            # Hard gates
            **{f"hg_{k}": v for k, v in hard.items()},
            "pass_hard_gates": bool(hard.get("pass_hard_gates", False)),
            # Total score
            "total_score": float(score.get("score_total", 0.0)),
        }
        rows.append(row)

    batch_df = pd.DataFrame(rows)

    if batch_df.empty:
        print("This batch produced 0 rows (all skipped).")
        return

    # 5) append + dedupe + save
    if resume and not existing.empty:
        merged = pd.concat([existing, batch_df], ignore_index=True)
    else:
        merged = batch_df

    merged["ticker"] = merged["ticker"].astype(str).str.upper()
    merged = merged.drop_duplicates(subset=["ticker"], keep="last")

    if "total_score" in merged.columns:
        merged = merged.sort_values(["total_score", "days_since_ipo"], ascending=[False, True]).reset_index(drop=True)

    merged.to_parquet(out_path, index=False)

    print(f"Processed this run: {len(batch_df)} tickers")
    print(f"Saved: {out_path} (total {len(merged)} rows)")


def main() -> None:
    p = argparse.ArgumentParser(prog="ipo_ml_screener")
    sub = p.add_subparsers(dest="cmd", required=True)

    p_refresh = sub.add_parser("refresh", help="Fetch IPO universe, compute scores, write parquet.")
    p_refresh.add_argument("--days-since-ipo", type=int, default=365, help="Only used when --start-date is not set.")
    p_refresh.add_argument("--limit", type=int, default=2000, help="Max IPO rows to consider from source (universe).")
    p_refresh.add_argument("--batch-size", type=int, default=300, help="How many tickers to process in this run.")
    p_refresh.add_argument(
        "--start-date",
        type=str,
        default=None,
        help="Fetch IPOs from this date (YYYY-MM-DD) using year pages, e.g. 2024-01-01.",
    )
    p_refresh.add_argument(
        "--resume",
        action="store_true",
        help="Append to existing parquet and skip already processed tickers.",
    )
    p_refresh.add_argument(
        "--out",
        type=str,
        default="data/processed/scores.parquet",
        help="Output parquet path.",
    )

    args = p.parse_args()

    if args.cmd == "refresh":
        refresh(
            days_since_ipo=args.days_since_ipo,
            limit=args.limit,
            start_date=args.start_date,
            batch_size=args.batch_size,
            resume=args.resume,
            out=args.out,
        )
    else:
        raise SystemExit("Unknown command")


if __name__ == "__main__":
    main()
