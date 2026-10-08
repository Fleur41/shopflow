from django.db import migrations

# Shared trigger function for append-only tables (audit log, inventory
# movements, ledgers): any UPDATE or DELETE raises, whatever code issued it.
# See docs/DATABASE.md §4.
CREATE_FUNCTION = """
CREATE OR REPLACE FUNCTION shopflow_prevent_modification() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'Table % is append-only: % is not allowed', TG_TABLE_NAME, TG_OP
        USING ERRCODE = 'restrict_violation';
END;
$$;
"""

DROP_FUNCTION = "DROP FUNCTION IF EXISTS shopflow_prevent_modification();"


class Migration(migrations.Migration):
    initial = True
    dependencies: list[tuple[str, str]] = []
    operations = [migrations.RunSQL(CREATE_FUNCTION, DROP_FUNCTION)]
