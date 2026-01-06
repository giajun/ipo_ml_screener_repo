# IPO ML Screener (AI × Industry 4.0 / Robotics) — Streamlit Dashboard

This repo screens **recently listed US stocks** and automatically scores a set of **hard thresholds** (liquidity, size, dilution/cash runway proxies, basic growth + margin, and a “left-of-peak uptrend” momentum filter).
It then presents results in a **Streamlit dashboard**.

## What it does (pipeline)
1. **Get recent IPOs** (default: last 200 IPOs) from StockAnalysis.
2. Pull **market data** (price history, market cap, shares outstanding) via `yfinance`.
3. Pull **fundamentals** from SEC EDGAR **Company Facts** API (XBRL JSON) via `data.sec.gov` (cash, CFO, capex, revenue, gross profit, SBC when available).
4. Compute:
   - **Uptrend / “left-of-peak”** momentum features
   - **Hard-gate scores** (pass/fail + weighted score)
5. Save a scored table to `data/processed/scores.parquet`.
6. Streamlit app loads the table, offers filters, and shows per-ticker details.

> Notes
- SEC requires a descriptive `User-Agent`. Set `SEC_USER_AGENT` in `.env` or your shell.
- Newly listed companies may have incomplete SEC financials; such fields will show as `NaN` and the scorer will mark them as “insufficient data”.

## Quickstart
```bash
# 1) Create env
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
pip install -e .

# 2) Configure SEC User-Agent (required by SEC)
export SEC_USER_AGENT="Your Name your.email@example.com"

# 3) Refresh data (downloads IPO list, market data, SEC facts, computes scores)
python -m ipo_ml_screener.cli.refresh --days-since-ipo 365 --limit 120

# 4) Run dashboard
streamlit run app.py
```

## Config
Edit `config.yaml` to tune:
- IPO lookback window (days since IPO)
- Momentum rules (“left-of-peak”)
- Hard gate thresholds and weights

## Repo structure
- `src/ipo_ml_screener/` core logic
- `app.py` Streamlit UI
- `data/` cached raw + processed outputs
- `config.yaml` thresholds & weights

## Data sources
- StockAnalysis “200 Most Recent IPOs” (for initial candidate list)
- Yahoo Finance via `yfinance` (market data)
- SEC EDGAR APIs (company tickers + company facts)

## Disclaimer
This is a research tool, not investment advice. Always verify numbers in filings and consider liquidity/volatility risks for recent IPOs.
