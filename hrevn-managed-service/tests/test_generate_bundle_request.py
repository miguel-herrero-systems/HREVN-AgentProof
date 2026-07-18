from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


from hrevn_managed_service.models.requests import GenerateBundleRequest


def test_generate_bundle_request_defaults_to_verified_record_mode():
    request = GenerateBundleRequest(record={"issuer_id": "acme"})

    assert request.bundle_mode == "verified_record_v1"
    assert request.record == {"issuer_id": "acme"}
    assert request.traces == []


def test_generate_bundle_request_accepts_eb1_mode():
    request = GenerateBundleRequest(bundle_mode="evidence_bundle_eb1", record={"issuer_id": "acme"})

    assert request.bundle_mode == "evidence_bundle_eb1"
    assert request.record == {"issuer_id": "acme"}
