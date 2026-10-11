from django.db import migrations

# Sync pull cursor (docs/DATABASE.md §1): every insert or update of a syncable
# row takes the next value of one global sequence, so "what changed since
# cursor N" is a simple, clock-independent range query. Tables opt in with
#   CREATE TRIGGER <table>_row_version BEFORE INSERT OR UPDATE ON <table>
#   FOR EACH ROW EXECUTE FUNCTION shopflow_set_row_version();
CREATE = """
CREATE SEQUENCE IF NOT EXISTS shopflow_row_version AS bigint;
CREATE OR REPLACE FUNCTION shopflow_set_row_version() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    NEW.row_version := nextval('shopflow_row_version');
    RETURN NEW;
END;
$$;
"""

DROP = """
DROP FUNCTION IF EXISTS shopflow_set_row_version();
DROP SEQUENCE IF EXISTS shopflow_row_version;
"""


class Migration(migrations.Migration):
    dependencies = [("common", "0001_append_only_function")]
    operations = [migrations.RunSQL(CREATE, DROP)]
