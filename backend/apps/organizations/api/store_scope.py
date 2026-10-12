"""Base view for endpoints under ``/stores/{store_id}/`` (docs/API.md §1).

The store comes from the URL, so it is checked against the caller's
membership: a store of another business, or one the caller isn't assigned
to, is a 404, never a 403.
"""

import uuid
from functools import cached_property
from typing import Any

from django.http import Http404
from rest_framework.request import Request

from .. import selectors
from ..models import Store
from .permissions import TenantAPIView


class StoreScopedView(TenantAPIView):
    def initial(self, request: Request, *args: Any, **kwargs: Any) -> None:
        super().initial(request, *args, **kwargs)
        # Before any other check (e.g. a missing Idempotency-Key), so a store
        # that isn't yours is always a 404.
        _ = self.store

    @cached_property
    def store(self) -> Store:
        store_id = self.kwargs.get("store_id")
        if not isinstance(store_id, uuid.UUID):  # pragma: no cover - URL converter guarantees it
            raise Http404
        store = selectors.accessible_stores(self.ctx).filter(pk=store_id, is_active=True).first()
        if store is None:
            raise Http404
        return store
