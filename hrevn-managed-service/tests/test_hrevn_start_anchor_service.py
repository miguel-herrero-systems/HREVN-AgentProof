from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


from hrevn_managed_service.services.hrevn_start_anchor_service import (
    anchor_course_artifact,
    anchor_policy_artifact,
    build_course_anchor_payload,
    build_policy_anchor_payload,
)


def _sample_payload() -> dict:
    return build_policy_anchor_payload(
        artifact_id="art-123",
        verification_code="HST-POL-2605-ABCD",
        verification_url="https://hrevn.com/verify/hrevn-start/policy/?artifact_id=art-123",
        organization_name="Acme Demo SL",
        organization_tax_id="B12345678",
        representative_name="Laura Demo",
        representative_role="CEO",
        policy_version="v1.0",
        issue_date="2026-05-09",
        effective_date="2026-05-09",
        language="es",
    )


def test_build_policy_anchor_payload_contains_stable_policy_fields():
    payload = _sample_payload()

    assert payload["product"] == "hrevn_start_policy"
    assert payload["artifact_id"] == "art-123"
    assert payload["organization_name"] == "Acme Demo SL"
    assert payload["policy_version"] == "v1.0"


def test_anchor_policy_artifact_returns_none_when_disabled():
    result = anchor_policy_artifact(_sample_payload(), enabled=False)

    assert result is None


def test_anchor_policy_artifact_defaults_to_pending_without_transaction_reference():
    result = anchor_policy_artifact(
        _sample_payload(),
        enabled=True,
        emit_real=False,
        network="sepolia",
        anchor_method="hrevn_start_anchor",
        transaction_reference="",
    )

    assert result is not None
    assert result["payload_sha256"]
    assert result["anchor_record"]["network"] == "sepolia"
    assert result["anchor_record"]["anchor_method"] == "hrevn_start_anchor"
    assert result["anchor_record"]["transaction_reference"] is None
    assert result["anchor_record"]["status"] == "anchor_pending"


def test_anchor_policy_artifact_marks_anchored_when_transaction_reference_exists():
    result = anchor_policy_artifact(
        _sample_payload(),
        enabled=True,
        network="sepolia",
        anchor_method="hrevn_start_anchor",
        transaction_reference="0xabc123",
    )

    assert result is not None
    assert result["anchor_record"]["transaction_reference"] == "0xabc123"
    assert result["anchor_record"]["status"] == "anchored"
    assert result["anchor_record"]["anchored_at"].endswith("Z")


def test_anchor_policy_artifact_marks_failed_when_real_emitter_lacks_credentials():
    result = anchor_policy_artifact(
        _sample_payload(),
        enabled=True,
        emit_real=True,
        network="sepolia",
        anchor_method="hrevn_start_anchor",
        transaction_reference="",
    )

    assert result is not None
    assert result["anchor_record"]["status"] == "anchor_failed"
    assert result["anchor_record"]["error"] == "missing_sepolia_credentials"


def test_build_course_anchor_payload_contains_stable_certificate_fields():
    payload = build_course_anchor_payload(
        artifact_id="cert-123",
        verification_code="HST-TRN-2605-ABCD",
        verification_url="https://hrevn.com/verify/hrevn-start/?artifact_id=cert-123",
        full_name="Laura Demo",
        email="Laura@Example.com",
        organization_name="Acme Demo SL",
        course_version="v1",
        completed_at="2026-05-09T10:00:00Z",
        issued_at="2026-05-09T10:05:00Z",
        language="es",
        identity_confirmed=True,
    )

    assert payload["product"] == "hrevn_start_course_certificate"
    assert payload["artifact_id"] == "cert-123"
    assert payload["email"] == "laura@example.com"
    assert payload["identity_confirmed"] is True


def test_anchor_course_artifact_defaults_to_pending_without_transaction_reference():
    payload = build_course_anchor_payload(
        artifact_id="cert-123",
        verification_code="HST-TRN-2605-ABCD",
        verification_url="https://hrevn.com/verify/hrevn-start/?artifact_id=cert-123",
        full_name="Laura Demo",
        email="Laura@Example.com",
        organization_name="Acme Demo SL",
        course_version="v1",
        completed_at="2026-05-09T10:00:00Z",
        issued_at="2026-05-09T10:05:00Z",
        language="es",
        identity_confirmed=True,
    )
    result = anchor_course_artifact(
        payload,
        enabled=True,
        emit_real=False,
        network="sepolia",
        anchor_method="hrevn_start_anchor",
        transaction_reference="",
    )

    assert result is not None
    assert result["anchor_record"]["status"] == "anchor_pending"
