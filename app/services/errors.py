"""Transport-neutral domain errors.

Services raise these instead of `HTTPException` so the same call works from an
HTTP route (mapped to a status code by a handler in `app/main.py`) and from a
WebSocket action (mapped to an error frame in `app/api/v2/protocol.py`).
"""

from __future__ import annotations


class NodusError(Exception):
    """Base class. `code` is the stable identifier a client switches on."""

    code = "error"
    status_code = 500

    def __init__(self, message: str, **detail: object) -> None:
        super().__init__(message)
        self.message = message
        self.detail = detail


class NotFound(NodusError):
    code = "not_found"
    status_code = 404


class Conflict(NodusError):
    code = "conflict"
    status_code = 409


class BadRequest(NodusError):
    code = "bad_request"
    status_code = 400


class Forbidden(NodusError):
    """Authenticated, but this particular capability is not on offer."""

    code = "forbidden"
    status_code = 403


class TooManyRequests(NodusError):
    """Admission refused — the caller is over a rate limit or a global cap.

    `retry_after` is carried both as an attribute (the HTTP handler turns it
    into a `Retry-After` header) and inside `detail`, so a socket client reading
    an error frame gets the same hint without a second code path.
    """

    code = "too_many_requests"
    status_code = 429

    def __init__(self, message: str, *, retry_after: float | None = None, **detail: object) -> None:
        if retry_after is not None:
            detail["retry_after"] = round(retry_after, 1)
        super().__init__(message, **detail)
        self.retry_after = retry_after


class Unavailable(NodusError):
    """A dependency the feature needs is not installed or not reachable."""

    code = "unavailable"
    status_code = 503
