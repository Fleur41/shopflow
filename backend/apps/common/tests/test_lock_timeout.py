from django.db import OperationalError

from apps.common.errors import exception_handler, is_lock_timeout


class _PgError(Exception):
    def __init__(self, sqlstate):
        super().__init__(sqlstate)
        self.sqlstate = sqlstate


def _db_error(sqlstate):
    try:
        try:
            raise _PgError(sqlstate)
        except _PgError as cause:
            raise OperationalError("db error") from cause
    except OperationalError as exc:
        return exc


def test_lock_timeouts_become_a_retryable_409():
    response = exception_handler(_db_error("55P03"), {})

    assert response is not None
    assert response.status_code == 409
    assert response.data["code"] == "LOCK_TIMEOUT"
    assert response["Retry-After"] == "1"


def test_other_database_errors_are_not_disguised():
    error = _db_error("08006")  # connection failure

    assert not is_lock_timeout(error)
    assert exception_handler(error, {}) is None  # propagates to the 500 handler
