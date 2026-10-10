"""Shared FastAPI dependencies."""

from __future__ import annotations

import secrets
from typing import Annotated

from fastapi import Depends, Header, HTTPException, status

from app.settings import Settings, get_settings


def require_admin(
    settings: Annotated[Settings, Depends(get_settings)],
    x_admin_token: Annotated[str | None, Header()] = None,
) -> None:
    """Allow the request only when `X-Admin-Token` equals ADMIN_TOKEN (constant-time compare).

    An unset ADMIN_TOKEN refuses every request, so admin endpoints are never open by default.
    """
    expected = settings.admin_token
    supplied = x_admin_token or ""
    if not expected or not secrets.compare_digest(supplied.encode(), expected.encode()):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="admin token required")
