"""Optional HTTP Basic authentication for the dashboard.

Basic is the only scheme the whole surface can use: ``EventSource`` cannot send
custom headers, so a bearer token would leave ``/api/stream`` unprotected. The
browser caches the credentials after the first challenge and replays them on the
SSE request.

Credentials come from the environment. With no password set the dashboard stays
open, which keeps a loopback demo frictionless.
"""

import logging
import os
import secrets
from typing import Callable, Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials

_logger = logging.getLogger(__name__)

USERNAME_ENV = "EXCHANGE_SIMULATOR_USER"
PASSWORD_ENV = "EXCHANGE_SIMULATOR_PASSWORD"
DEFAULT_USERNAME = "admin"

_scheme = HTTPBasic(auto_error=False)


def _matches(supplied: str, expected: str) -> bool:
    return secrets.compare_digest(supplied.encode("utf-8"), expected.encode("utf-8"))


def build_auth_dependency(
    username: Optional[str] = None,
    password: Optional[str] = None,
) -> Callable:
    """Return a dependency that guards every route, or a no-op when unset."""
    username = username if username is not None else os.environ.get(USERNAME_ENV, DEFAULT_USERNAME)
    password = password if password is not None else os.environ.get(PASSWORD_ENV)

    if not password:
        _logger.warning(
            "%s is not set: the dashboard is unauthenticated and anyone who can "
            "reach this port can start or stop a session", PASSWORD_ENV,
        )

        async def allow_everyone() -> None:
            return None

        return allow_everyone

    _logger.info("Dashboard requires HTTP Basic authentication as %r", username)

    def verify(credentials: Optional[HTTPBasicCredentials] = Depends(_scheme)) -> None:
        if credentials is None or not (
            _matches(credentials.username, username) and _matches(credentials.password, password)
        ):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid credentials",
                headers={"WWW-Authenticate": 'Basic realm="Exchange Simulator"'},
            )

    return verify
