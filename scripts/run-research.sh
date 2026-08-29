#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="/home/liharr/src/trading-system"
cd "$PROJECT_DIR"
docker compose exec -T research python -m trading_system.research --period 5y
docker compose exec -T research python -m trading_system.research_backtest
