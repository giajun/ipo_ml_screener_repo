#!/usr/bin/env bash
set -euo pipefail

cd /home/lijun/ipo_ml_screener_repo/ipo_ml_screener
export PYTHONPATH=$PWD/src

ITERATION=0
MAX_ITERATIONS=100

while true; do
  ITERATION=$((ITERATION + 1))
  echo "=== Iteration $ITERATION ==="

  OUT=$(python -m ipo_ml_screener.cli refresh --start-date 2024-01-01 --limit 2000 --batch-size 300 --resume 2>&1)
  echo "$OUT"

  # Debug: Check what we're searching for
  if echo "$OUT" | grep -q "No remaining tickers to process"; then
    echo "DEBUG: Found 'No remaining tickers to process' - breaking"
    break
  fi

  if echo "$OUT" | grep -q "This batch produced 0 rows"; then
    echo "DEBUG: Found 'This batch produced 0 rows' - breaking"
    break
  fi

  # Safety: prevent infinite loops
  if [ "$ITERATION" -ge "$MAX_ITERATIONS" ]; then
    echo "DEBUG: Reached max iterations ($MAX_ITERATIONS) - breaking"
    break
  fi

  echo "DEBUG: Continuing to next batch..."
done

echo "=== Completed after $ITERATION iterations ==="
