from rest_framework.pagination import CursorPagination


class DefaultCursorPagination(CursorPagination):
    """Stable cursor pagination for list endpoints.

    The default ordering is by primary key: IDs are UUIDv7, so ``-id`` is
    newest-first and unique, which cursor pagination requires.
    """

    page_size = 50
    page_size_query_param = "page_size"
    max_page_size = 200
    ordering = "-id"
