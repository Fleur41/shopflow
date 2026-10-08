#!/bin/sh
# Local development only: create the runtime role the application connects as.
# Runs automatically on a fresh database volume; for an existing volume run
# `make db-roles`. Production roles are created by infrastructure code.
set -eu

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<EOSQL
DO \$\$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'shopflow_app') THEN
        CREATE ROLE shopflow_app LOGIN PASSWORD '${POSTGRES_APP_PASSWORD}'
            NOSUPERUSER NOCREATEDB NOCREATEROLE;
    END IF;
END
\$\$;
GRANT CONNECT ON DATABASE "$POSTGRES_DB" TO shopflow_app;
EOSQL
