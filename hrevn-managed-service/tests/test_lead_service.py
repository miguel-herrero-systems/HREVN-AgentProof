from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


from hrevn_managed_service.config import settings
from hrevn_managed_service.models.requests import ContactRequest, LeadCaptureRequest
from hrevn_managed_service.services import lead_service


def _set_setting(name: str, value):
    original = getattr(settings, name)
    object.__setattr__(settings, name, value)
    return original


def _sample_request() -> LeadCaptureRequest:
    return LeadCaptureRequest(
        email="team@example.com",
        source_page="chequeo-uso-ia",
        language="es",
        result_level="medium",
        result_eligibility="apto",
        result_eligibility_reasons=[],
        result_primary_use="marketing",
        result_signals=["No existe una política interna clara sobre uso de IA."],
        answers={"triage-1": ["marketing"], "doc-1": "no"},
        page_url="https://hrevn.com/chequeo-uso-ia/",
        user_agent="pytest",
    )


def _sample_contact_request() -> ContactRequest:
    return ContactRequest(
        name="Miguel",
        email="team@example.com",
        organization="HREVN",
        source_page="contacto",
        product_interest="contact",
        language="es",
        landing="contacto",
        profile_type="empresa-final",
        ai_system_type="rrhh-seleccion",
        current_situation="explorando",
        objective="orientacion-inicial",
        message="Queremos hablar del caso.",
        contact_consent="acepta-contacto",
        page_url="https://hrevn.com/contacto/",
        user_agent="pytest",
    )


def _sample_hrevn_start_contact_request() -> ContactRequest:
    return ContactRequest(
        name="Miguel",
        email="team@example.com",
        organization="HREVN",
        source_page="chequeo-uso-ia-formacion",
        product_interest="hrevn_start_stage_1",
        language="es",
        message="Queremos ordenar el uso interno de IA y una primera formación.",
        page_url="https://hrevn.com/chequeo-uso-ia/formacion/",
        user_agent="pytest",
    )


def test_capture_lead_submission_stores_payload_even_without_smtp(tmp_path, monkeypatch):
    original_dir = _set_setting("lead_storage_dir", tmp_path)
    original_host = _set_setting("lead_smtp_host", "")
    try:
        result = lead_service.capture_lead_submission(_sample_request())

        assert result.delivery_status == "stored_only"
        stored_files = sorted(tmp_path.glob("ai_use_check_leads_*.jsonl"))
        assert stored_files

        payload = json.loads(stored_files[0].read_text(encoding="utf-8").strip())
        assert payload["email"] == "team@example.com"
        assert payload["result_level"] == "medium"
        assert payload["result_eligibility"] == "apto"
    finally:
        object.__setattr__(settings, "lead_storage_dir", original_dir)
        object.__setattr__(settings, "lead_smtp_host", original_host)


def test_capture_lead_submission_returns_emailed_when_mailer_succeeds(tmp_path, monkeypatch):
    original_dir = _set_setting("lead_storage_dir", tmp_path)
    monkeypatch.setattr(lead_service, "send_lead_email", lambda payload: None)
    try:
        result = lead_service.capture_lead_submission(_sample_request())
        assert result.delivery_status == "emailed"
        assert result.email_error is None
    finally:
        object.__setattr__(settings, "lead_storage_dir", original_dir)


def test_capture_contact_submission_stores_payload_even_without_smtp(tmp_path):
    original_dir = _set_setting("lead_storage_dir", tmp_path)
    original_host = _set_setting("lead_smtp_host", "")
    try:
        result = lead_service.capture_contact_submission(_sample_contact_request())

        assert result.delivery_status == "stored_only"
        stored_files = sorted(tmp_path.glob("contact_requests_*.jsonl"))
        assert stored_files

        payload = json.loads(stored_files[0].read_text(encoding="utf-8").strip())
        assert payload["name"] == "Miguel"
        assert payload["source_page"] == "contacto"
        assert payload["objective"] == "orientacion-inicial"
    finally:
        object.__setattr__(settings, "lead_storage_dir", original_dir)
        object.__setattr__(settings, "lead_smtp_host", original_host)


def test_capture_hrevn_start_contact_request_accepts_new_source_page(tmp_path):
    original_dir = _set_setting("lead_storage_dir", tmp_path)
    original_host = _set_setting("lead_smtp_host", "")
    try:
        result = lead_service.capture_contact_submission(_sample_hrevn_start_contact_request())

        assert result.delivery_status == "stored_only"
        stored_files = sorted(tmp_path.glob("contact_requests_*.jsonl"))
        assert stored_files

        payload = json.loads(stored_files[0].read_text(encoding="utf-8").strip())
        assert payload["source_page"] == "chequeo-uso-ia-formacion"
        assert payload["product_interest"] == "hrevn_start_stage_1"
    finally:
        object.__setattr__(settings, "lead_storage_dir", original_dir)
        object.__setattr__(settings, "lead_smtp_host", original_host)


def test_validate_lead_origin_accepts_known_origins_and_rejects_unknown():
    original_origins = _set_setting("lead_allowed_origins_raw", "https://hrevn.com,https://www.hrevn.com")
    try:
        lead_service.validate_lead_origin("https://hrevn.com")
        try:
            lead_service.validate_lead_origin("https://evil.example.com")
        except ValueError as exc:
            assert "Origin not allowed" in str(exc)
        else:
            raise AssertionError("Expected ValueError for disallowed origin")
    finally:
        object.__setattr__(settings, "lead_allowed_origins_raw", original_origins)
