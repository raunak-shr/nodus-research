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


class Unavailable(NodusError):
    """A dependency the feature needs is not installed or not reachable."""

    code = "unavailable"
    status_code = 503
