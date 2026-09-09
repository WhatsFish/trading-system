# Isolated portfolio PostgreSQL acceptance

This suite runs the real `portfolio-store.ts` queries against PostgreSQL 16.
It covers both SQL migrations (including reapplication after a confirmation),
snapshot aggregation/freshness, actor-bound expiring single-use previews,
concurrent revision conflicts, snapshot invalidation, and atomic rollback after
both a real history constraint violation and a post-consumption exception.

Independent database connections exercise the worker's SQL lock protocol:
shared configuration lock `884424`, exclusive confirmation transaction lock
`884424`, and serialized executor submissions on `884425`. Tests observe actual
`pg_locks` waiters, including the queued-writer/nested-executor try-lock case.
They do **not** start the worker, submit orders, or call OKX.

The suite is destructive to its fixtures. Use only the disposable container
below, never a production database. The URL must explicitly name
`portfolio_test` on loopback with no query overrides; the connected database
name is also checked. Without `TEST_PORTFOLIO_DATABASE_URL`, the test reports
**SKIP**, not successful PostgreSQL acceptance. Start from an empty database.

## Reproduce

Prerequisites: existing `web/node_modules` with `pg` and TypeScript, and local
`postgres:16-alpine` / `node:22-bookworm-slim` images. No installation, secrets,
host ports, external Docker network, or existing service deployment is needed.
Run from the repository root:

```bash
set -eu
DB=trading-system-portfolio-test-cbfb17ed
RUNNER=trading-system-portfolio-test-runner-cbfb17ed
BUILD="$PWD/web/.portfolio-postgres-test-build"
for name in "$DB" "$RUNNER"; do
  if docker container inspect "$name" >/dev/null 2>&1; then
    echo "Refusing existing container: $name"; exit 1
  fi
done
[ ! -e "$BUILD" ] || { echo "Refusing existing build directory: $BUILD"; exit 1; }
mkdir "$BUILD"
cleanup() {
  docker rm -f "$RUNNER" "$DB" >/dev/null 2>&1 || true
  rm -r "$BUILD"
}
trap cleanup EXIT

docker run --rm --network none --user "$(id -u):$(id -g)" \
  -v "$PWD/web/node_modules:/workspace/web/node_modules:ro" \
  -v "$PWD/web/src/lib:/workspace/web/src/lib:ro" \
  -v "$PWD/web/tests:/workspace/web/tests:ro" \
  -v "$BUILD:/workspace/web/.portfolio-postgres-test-build" \
  -w /workspace/web node:22-bookworm-slim \
  node node_modules/typescript/bin/tsc --module commonjs --moduleResolution node \
  --target es2020 --esModuleInterop --skipLibCheck \
  --outDir .portfolio-postgres-test-build tests/portfolio-postgres.test.ts

docker run -d --name "$DB" --rm --network none \
  --tmpfs /var/lib/postgresql/data \
  -e POSTGRES_HOST_AUTH_METHOD=trust -e POSTGRES_DB=portfolio_test \
  postgres:16-alpine >/dev/null
ready=0
for attempt in $(seq 1 30); do
  if docker exec "$DB" pg_isready -h 127.0.0.1 -U postgres -d portfolio_test \
    >/dev/null 2>&1; then ready=1; break; fi
  sleep 1
done
[ "$ready" = 1 ]

docker run --name "$RUNNER" --rm --network "container:$DB" \
  -v "$PWD/web/node_modules:/workspace/web/node_modules:ro" \
  -v "$BUILD:/workspace/web/.portfolio-postgres-test-build:ro" \
  -v "$PWD/db:/workspace/db:ro" \
  -w /workspace/web \
  -e TEST_PORTFOLIO_DATABASE_URL=postgres://postgres@127.0.0.1/portfolio_test \
  node:22-bookworm-slim \
  node --test .portfolio-postgres-test-build/tests/portfolio-postgres.test.js
```

Expected: **11 tests passed, 0 failed, 0 skipped** (ten acceptance subtests and
their parent). The exit trap removes only the two exact test container names
and this run's compiled artifacts, including on failure.
