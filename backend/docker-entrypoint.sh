#!/bin/sh
# Container entrypoint: wait for the database, apply migrations, then start the server.
# Compose already waits for the db healthcheck; the retry loop here makes the backend
# robust when it is started on its own or the db restarts mid-boot.
set -eu

attempts="${MIGRATION_ATTEMPTS:-30}"
n=1
echo "Applying database migrations..."
until alembic upgrade head; do
    if [ "$n" -ge "$attempts" ]; then
        echo "Database not ready / migration failed after $attempts attempts; giving up." >&2
        exit 1
    fi
    echo "Migration attempt $n/$attempts failed; retrying in 2s..." >&2
    n=$((n + 1))
    sleep 2
done

echo "Migrations applied; starting: $*"
exec "$@"
