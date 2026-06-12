"""Shared safe HTTP client for all adapters.

``safe_request`` enforces redirect-pinning: every ``Location`` header host is
re-validated against the caller-supplied allowlist (same dot-bounded suffix
logic as ``validate_source_host``).  Cross-host redirects are refused.

Placing this in a separate module (not ``__init__.py``) avoids the circular
import that would arise from individual adapter modules importing from the
package init while the init imports from those modules.
"""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urlparse

import requests

from ..config import ConfigError

logger = logging.getLogger(__name__)

# Maximum HTTP redirect hops safe_request will follow before raising.
MAX_REDIRECT_HOPS = 5


def _host_allowed(
    host: str,
    allowed: frozenset[str] | set[str],
) -> bool:
    """Return True if *host* matches the allowlist (dot-bounded suffix)."""
    return host in allowed or any(host.endswith("." + h) for h in allowed)


def safe_request(
    method: str,
    url: str,
    *,
    allowed_hosts: frozenset[str] | set[str],
    session: "requests.Session | None" = None,
    max_hops: int = MAX_REDIRECT_HOPS,
    **kwargs: Any,
) -> "requests.Response":
    """Perform an HTTP request with redirect-pinning against the host allowlist.

    ``allow_redirects=False`` is enforced; on a 3xx response each ``Location``
    header host is re-validated before following.  Cross-host redirects are
    refused.  301/302/303-on-POST are followed as GET per RFC 7231 §6.4.3;
    307/308 preserve the original method and body.

    Args:
        method: HTTP method (``"GET"`` or ``"POST"``).
        url: Initial request URL.
        allowed_hosts: Set of allowed hostnames (dot-bounded suffix match).
        session: Optional ``requests.Session`` to use.
        max_hops: Maximum redirect hops to follow before raising.
        **kwargs: Forwarded to the underlying ``requests.request`` call.
            ``allow_redirects`` is always forced to ``False``.

    Returns:
        The final response (may be 2xx or an error status — caller decides
        whether to call ``raise_for_status``).

    Raises:
        ConfigError: A ``Location`` host is outside ``allowed_hosts``.
        RuntimeError: More than ``max_hops`` redirects were followed.
    """
    kwargs["allow_redirects"] = False
    caller = session.request if session is not None else requests.request

    current_method = method.upper()
    current_url = url
    current_kwargs = dict(kwargs)

    for hop in range(max_hops + 1):
        resp = caller(current_method, current_url, **current_kwargs)

        if resp.status_code < 300 or resp.status_code >= 400:
            return resp

        location = resp.headers.get("Location", "")
        if not location:
            return resp

        parsed = urlparse(location)
        if not parsed.netloc:
            # Relative redirect — resolve using current URL's origin.
            orig = urlparse(current_url)
            redirect_host = (orig.hostname or "").lower()
            scheme_netloc = f"{orig.scheme}://{orig.netloc}"
            if location.startswith("/"):
                location = scheme_netloc + location
        else:
            redirect_host = (parsed.hostname or "").lower()

        if not _host_allowed(redirect_host, allowed_hosts):
            raise ConfigError(
                f"safe_request: redirect from {current_url!r} to {location!r} "
                f"points to host {redirect_host!r} which is outside the "
                f"allowlist {sorted(allowed_hosts)} — refusing cross-host redirect"
            )

        if hop == max_hops:
            raise RuntimeError(
                f"safe_request: exceeded {max_hops} redirect hops at {current_url!r}"
            )

        # Determine next method per RFC 7231:
        # 307/308 → preserve method + body.
        # 301/302/303 → switch to GET (body/json dropped).
        if resp.status_code in (307, 308):
            next_method = current_method
            next_kwargs = dict(current_kwargs)
        else:
            next_method = "GET"
            next_kwargs = {k: v for k, v in current_kwargs.items()
                          if k not in ("json", "data")}

        logger.debug("Redirect %d (%d): %s → %s",
                     hop + 1, resp.status_code, current_url, location)
        current_method = next_method
        current_url = location
        current_kwargs = next_kwargs

    raise RuntimeError("safe_request: redirect loop exhausted")
