#!/usr/bin/env bash
set -euo pipefail

cd /home/liharr/src/trading-system
docker compose exec -T research python -m trading_system.shadow
