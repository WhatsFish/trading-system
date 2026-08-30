#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="/home/liharr/src/trading-system"
# shellcheck disable=SC1091
source "$PROJECT_DIR/.env"
docker exec -e PGPASSWORD="$TRADING_PG_PASSWORD" traffic-monitor-db-1 \
  psql -h localhost -U trading_system -d trading_system -v ON_ERROR_STOP=1 \
  -c "UPDATE system_setting SET value = 'true', updated_at = NOW() WHERE key = 'execution_enabled';"
echo "Live execution database gate enabled."
