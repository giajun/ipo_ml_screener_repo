#!/usr/bin/env bash
set -euo pipefail

cd /home/lijun/ipo_ml_screener_repo/ipo_ml_screener
export PYTHONPATH=$PWD/src

echo "======================================"
echo "IPO ML Screener - Full Download Script"
echo "======================================"
echo "This script will download and score all IPOs from 2024-01-01 to now"
echo "Processing in batches of 300 tickers"
echo ""

ITERATION=0
MAX_ITERATIONS=10

while true; do
  ITERATION=$((ITERATION + 1))
  echo ""
  echo "=== Iteration $ITERATION / $MAX_ITERATIONS ==="
  echo "Starting batch processing at $(date)"

  # Count current rows before processing
  BEFORE=0
  if [ -f "data/processed/scores.parquet" ]; then
    BEFORE=$(python -c "import pandas as pd; print(len(pd.read_parquet('data/processed/scores.parquet')))" 2>/dev/null || echo "0")
  fi
  echo "Current database size: $BEFORE rows"

  # Run the CLI command
  OUT=$(python -m ipo_ml_screener.cli refresh --start-date 2024-01-01 --limit 2000 --batch-size 300 --resume 2>&1)

  # Count processed rows
  PROCESSED=$(echo "$OUT" | grep "Processed this run:" | sed 's/.*: \([0-9]*\).*/\1/')
  TOTAL=$(echo "$OUT" | grep "total \([0-9]*\) rows" | sed 's/.*total \([0-9]*\).*/\1/')

  echo "Processed: $PROCESSED tickers"
  echo "Database size: $TOTAL rows"

  # Check for completion conditions
  if echo "$OUT" | grep -q "No remaining tickers to process"; then
    echo ""
    echo "✓ All tickers have been processed!"
    break
  fi

  if echo "$OUT" | grep -q "This batch produced 0 rows"; then
    echo ""
    echo "✓ No more valid tickers to process (batch returned 0 rows)"
    break
  fi

  # Safety limit
  if [ "$ITERATION" -ge "$MAX_ITERATIONS" ]; then
    echo ""
    echo "⚠ Reached maximum iterations ($MAX_ITERATIONS)"
    echo "Run this script again to continue processing more batches"
    break
  fi

  echo "Continuing to next batch..."
done

echo ""
echo "======================================"
echo "Download Complete!"
echo "======================================"
echo "Final statistics:"
python -c "
import pandas as pd
df = pd.read_parquet('data/processed/scores.parquet')
print(f'Total IPOs: {len(df)}')
print(f'Date range: {df[\"ipo_date\"].min().date()} to {df[\"ipo_date\"].max().date()}')
print(f'Top score: {df[\"total_score\"].max():.1f} ({df.loc[df[\"total_score\"].idxmax(), \"ticker\"]})')
print(f'')
print(f'You can now view the dashboard with:')
print(f'  streamlit run app.py')
"
