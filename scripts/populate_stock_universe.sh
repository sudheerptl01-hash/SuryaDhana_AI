#!/bin/bash
# Populate NSE 1000 & Midcap 500 stock universe into DuckDB
# Usage: bash scripts/populate_stock_universe.sh

set -e

echo "=========================================="
echo "Populating NSE 1000 & Midcap 500 Universe"
echo "=========================================="

# Check if data-service is running
echo "[1/3] Checking data-service availability..."
if ! curl -s http://localhost:8001/health > /dev/null 2>&1; then
    echo "ERROR: data-service not running on :8001"
    echo "Start with: docker compose -f infra/docker-compose.yml up"
    exit 1
fi
echo "✓ data-service is available"

# Extract tickers from CSV
echo "[2/3] Reading stock universe from CSV..."
TICKERS=$(python3 -c "
import pandas as pd
import json
df = pd.read_csv('data/NSE_1000_MIDCAP_500.csv')
tickers = df['ticker'].tolist()
print(json.dumps(tickers))
")

echo "✓ Loaded $(echo $TICKERS | python3 -c "import sys, json; print(len(json.loads(sys.stdin.read())))")" tickers

# Trigger historical data fetch
echo "[3/3] Triggering historical data fetch..."
curl -s -X POST http://localhost:8001/fetch/historical \
  -H "Content-Type: application/json" \
  -d "{\"tickers\": $TICKERS, \"years\": 5}" \
  | python3 -m json.tool

echo ""
echo "=========================================="
echo "Data fetch initiated. Check logs:"
echo "docker compose logs -f data-service"
echo "=========================================="
