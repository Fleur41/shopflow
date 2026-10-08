"""Enumerate the API's URL routes for cross-cutting tests."""

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

from django.urls import URLPattern, URLResolver, get_resolver

HANDLER_METHODS = ("get", "post", "put", "patch", "delete")


@dataclass(frozen=True)
class Route:
    path: str  # e.g. "api/v1/stores/<uuid:store_id>/"
    view_class: type[Any]

    @property
    def methods(self) -> list[str]:
        return [m.upper() for m in HANDLER_METHODS if hasattr(self.view_class, m)]

    @property
    def has_path_params(self) -> bool:
        return "<" in self.path

    def url(self, **params: Any) -> str:
        url = "/" + self.path
        for name, value in params.items():
            for converter in ("uuid", "int", "str", "slug"):
                url = url.replace(f"<{converter}:{name}>", str(value))
        assert "<" not in url, f"unfilled parameter in {url}"
        return url


def api_routes() -> list[Route]:
    return [r for r in _walk(get_resolver().url_patterns, "") if r.path.startswith("api/v1/")]


def _walk(patterns: list[Any], prefix: str) -> Iterator[Route]:
    for pattern in patterns:
        if isinstance(pattern, URLResolver):
            yield from _walk(pattern.url_patterns, prefix + str(pattern.pattern))
        elif isinstance(pattern, URLPattern):
            view_class = getattr(pattern.callback, "cls", None)
            if view_class is not None:
                yield Route(prefix + str(pattern.pattern), view_class)
