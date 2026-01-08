# IPO ML Screener (AI × Industry 4.0 / Robotics) — Streamlit Dashboard

This repo screens **recently listed US stocks** and automatically scores a set of **hard thresholds** (liquidity, size, dilution/cash runway proxies, basic growth + margin, and a "left-of-peak uptrend" momentum filter).
It then presents results in a **Streamlit dashboard**.

## What it does (pipeline)
1. **Get recent IPOs** from IpoScoop.com (2024-present, ~570 IPOs)
2. Pull **market data** (price history, market cap, shares outstanding) via `yfinance`.
3. Pull **fundamentals** from SEC EDGAR **Company Facts** API (XBRL JSON) via `data.sec.gov` (cash, CFO, capex, revenue, gross profit, SBC when available).
4. Pull basic **filing metadata** (latest filing, latest 10-Q/10-K dates) from the SEC **Submissions** endpoint.
5. Compute:
   - **Uptrend / "left-of-peak"** momentum features
   - **Hard-gate scores** (pass/fail + weighted score)
6. Save a scored table to `data/processed/scores.parquet`.
7. Streamlit app loads the table, offers filters, and shows per-ticker details.

> Notes
- SEC requires a descriptive `User-Agent`. Set `SEC_USER_AGENT` in `.env` or your shell.
- Newly listed companies may have incomplete SEC financials; such fields will show as `NaN` and the scorer will mark them as "insufficient data".
- The script automatically skips delisted tickers and SPACs without trading data.

## Quick Start

### 1. Download and Score All IPOs (2024-present)

Run the automated batch download script:

```bash
bash run_full_download.sh
```

This will:
- Download IPO data from 2024-01-01 to present
- Fetch price history and SEC filings for each ticker (300 per batch)
- Calculate scores based on momentum, fundamentals, and hard gates
- Save results to `data/processed/scores.parquet`
- Process ~570 IPOs in 2-3 iterations (takes 10-30 minutes)

### 2. View the Dashboard

Once data is downloaded, launch the interactive dashboard:

```bash
streamlit run app.py
```

The dashboard lets you:
- Filter IPOs by score, date range, and pass/fail criteria
- View detailed metrics for each ticker
- See price charts and momentum indicators
- Explore SEC filing information

## Manual Usage

### Download a Single Batch

```bash
python -m ipo_ml_screener.cli refresh --start-date 2024-01-01 --limit 2000 --batch-size 300 --resume
```

Parameters:
- `--start-date`: Starting date for IPO search (YYYY-MM-DD)
- `--limit`: Maximum number of IPOs to consider from the source (use 2000+ to get all 2024-2025 IPOs)
- `--batch-size`: Number of tickers to process in this run (300 recommended)
- `--resume`: Skip already-processed tickers and append to existing data

### Continue Processing More Batches

Simply run the same command again with `--resume` flag - it will automatically skip already-processed tickers.

## How It Works

1. **IPO Discovery**: Fetches IPOs from IpoScoop.com since the specified start date
2. **Smart Processing**: Processes oldest IPOs first (2024) to prioritize stocks with trading history
3. **Data Collection**: For each ticker:
   - Fetches 2-year price history from Yahoo Finance
   - Retrieves SEC company facts and filing metadata
   - Skips delisted/invalid tickers automatically
4. **Scoring**: Calculates scores based on:
   - **Hard Gates**: Price > $5, Market cap > $100M, Liquidity, etc.
   - **Momentum**: Moving average trends, recent returns
   - **Fundamentals**: Revenue growth, margins, cash runway
5. **Storage**: Saves all results to a Parquet file with automatic deduplication

## Config
Edit `config.yaml` to tune:
- IPO lookback window (days since IPO)
- Momentum rules ("left-of-peak")
- Hard gate thresholds and weights

## Repo structure
- `src/ipo_ml_screener/` core logic
- `app.py` Streamlit UI
- `data/` cached raw + processed outputs
- `config.yaml` thresholds & weights
- `run_full_download.sh` automated batch processing script
- `run_batches.sh` legacy batch script (simpler version)

## Data sources
- IpoScoop.com "IPO Pricings" (for IPO list since 2024)
- Yahoo Finance via `yfinance` (market data)
- SEC EDGAR APIs (company tickers + company facts + submissions)

## Troubleshooting

### Script stops prematurely
- Increase `MAX_ITERATIONS` in the script (default: 10)
- Or just run the script again - it will resume from where it stopped

### Too many delisted tickers
- The script automatically skips tickers with no price data
- This is normal for older IPOs or SPACs that merged/delisted
- The script now processes oldest IPOs first to minimize this issue

### Dashboard shows wrong columns
- Make sure you're using the latest `scores.parquet` file
- Column names have been standardized to use `total_score` (not `score_total`)

## Disclaimer
This is a research tool, not investment advice. Always verify numbers in filings and consider liquidity/volatility risks for recent IPOs.
