from rest_framework.request import Request
from rest_framework.throttling import BaseThrottle


def client_ip(request: Request) -> str | None:
    """The caller's IP, honouring REST_FRAMEWORK["NUM_PROXIES"] like the throttles do."""
    return BaseThrottle().get_ident(request) or None
