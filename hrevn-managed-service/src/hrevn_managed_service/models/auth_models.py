from __future__ import annotations

from pydantic import BaseModel


class ApiKeyRecord(BaseModel):
    customer_id: str
    plan: str = "default"
    license_id: str | None = None
    active: bool = True


class AuthContext(BaseModel):
    authenticated: bool
    api_key_hint: str | None = None
    customer_id: str | None = None
    plan: str | None = None
    license_id: str | None = None
