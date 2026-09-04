"""Framework-agnostic domain errors.

Services raise these instead of `fastapi.HTTPException`, so business logic stays free of
HTTP concerns and can be reused from the scheduler, CLI scripts or tests. `app.main`
installs handlers that translate them into JSON responses with the right status code.
"""
from __future__ import annotations


class DomainError(Exception):
    """Base class – a user-facing message plus an HTTP status hint."""

    status_code = 400

    def __init__(self, message: str, *, status_code: int | None = None):
        super().__init__(message)
        self.message = message
        if status_code is not None:
            self.status_code = status_code


class NotFoundError(DomainError):
    status_code = 404


class ValidationError(DomainError):
    status_code = 400


class ConflictError(DomainError):
    status_code = 409


class UpstreamError(DomainError):
    """A third-party service (SERP API, social network, AI provider…) failed."""

    status_code = 502
