#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
ENV_FILE="${TRADING_ENV_FILE:-$PROJECT_DIR/.env}"
DB_CONTAINER="${TRADING_DB_CONTAINER:-traffic-monitor-db-1}"

if [ ! -f "$ENV_FILE" ]; then
  echo "ERROR: $ENV_FILE not found" >&2
  exit 1
fi
# shellcheck disable=SC1090
source "$ENV_FILE"
: "${TRADING_PG_PASSWORD:?TRADING_PG_PASSWORD is required}"

escaped_password=${TRADING_PG_PASSWORD//\'/\'\'}
docker exec -i "$DB_CONTAINER" psql -U umami -d umami <<SQL
DO \$\$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'trading_system') THEN
    CREATE ROLE trading_system WITH LOGIN PASSWORD '$escaped_password';
  ELSE
    ALTER ROLE trading_system WITH PASSWORD '$escaped_password';
  END IF;
END
\$\$;
SELECT 'CREATE DATABASE trading_system OWNER trading_system'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'trading_system')\gexec
GRANT ALL PRIVILEGES ON DATABASE trading_system TO trading_system;
SQL

docker exec -i -e PGPASSWORD="$TRADING_PG_PASSWORD" "$DB_CONTAINER" \
  psql -h localhost -U trading_system -d trading_system < "$PROJECT_DIR/db/schema.sql"
echo "trading_system bootstrap complete"

