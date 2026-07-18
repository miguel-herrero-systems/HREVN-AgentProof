from __future__ import annotations

import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


from hrevn_managed_service.models.requests import ConsumeCompanyMagicLinkRequest, RequestCompanyMagicLinkRequest
from hrevn_managed_service.models.requests import (
    AcceptCompanyAdminInviteRequest,
    CreateCompanyWithOwnerRequest,
)
from hrevn_managed_service.services.company_account_service import GENERIC_MAGIC_LINK_MESSAGE, generate_token, hash_token


def test_request_company_magic_link_normalizes_email():
    payload = RequestCompanyMagicLinkRequest(email="  OWNER@Example.com  ")

    assert payload.email == "owner@example.com"


def test_consume_company_magic_link_requires_token():
    with pytest.raises(ValueError):
        ConsumeCompanyMagicLinkRequest(token="   ")


def test_company_account_token_helpers_are_stable():
    raw_token = generate_token("mag")

    assert raw_token.startswith("mag_")
    assert hash_token(raw_token) == hash_token(raw_token)
    assert GENERIC_MAGIC_LINK_MESSAGE


def test_create_company_with_owner_normalizes_owner_email():
    payload = CreateCompanyWithOwnerRequest(
        legal_name="Acme SL",
        tax_id="B12345678",
        contact_email="contacto@acme.test",
        owner_full_name="Laura Owner",
        owner_email="  OWNER@Acme.test ",
    )

    assert payload.owner_email == "owner@acme.test"


def test_accept_company_admin_invite_requires_token():
    with pytest.raises(ValueError):
        AcceptCompanyAdminInviteRequest(token=" ")
