"""Fail-closed authorization for knowledge administration endpoints."""
import hmac
import os

from fastapi import Header, HTTPException


def require_admin_api_key(x_admin_api_key: str | None = Header(default=None)):
    expected = os.getenv("ADMIN_API_KEY")
    if not expected:
        raise HTTPException(status_code=503, detail="Admin knowledge management is not configured")
    if not x_admin_api_key or not hmac.compare_digest(x_admin_api_key, expected):
        raise HTTPException(status_code=401, detail="Invalid administrator credential")
