from __future__ import annotations

from pathlib import Path

import pytest

from hrevn_managed_service.services import promotora_demo_service as service


def _certificate_record() -> dict:
    return {
        "certificate": {
            "promotion_name": "Residencial Altamar",
            "location": "Santander",
            "period": "2026-07",
            "global_progress_pct": 4.44,
            "certified_at": "2026-07-02T09:15:00Z",
            "certified_by": "Técnica demo",
        },
        "partidas": service._partidas([80] + [0] * 17),
        "photos": [{"photo_id": "PP-TEST"}],
    }


def test_certificate_requires_exact_catalog_and_percentages() -> None:
    record = _certificate_record()
    service.validate_certificate_content(record)

    record["partidas"][1] = dict(record["partidas"][0])
    with pytest.raises(service.PromotoraDemoError, match="partida_catalog_mismatch"):
        service.validate_certificate_content(record)


def test_handover_requires_complete_defect_and_photo() -> None:
    record = {
        "review": {
            "promotion_name": "Residencial Las Acacias",
            "unit": "Vivienda 1B",
            "client": "Cliente demo",
            "reviewed_at": "2026-07-01T12:05:00Z",
            "reviewed_by": "Técnica demo",
        },
        "defects": [
            {
                "item": "D-01",
                "descripcion": "Persiana desalineada.",
                "ubicacion": "Dormitorio 2",
                "estado": "Pendiente",
            }
        ],
        "photos": [{"photo_id": "PP-TEST"}],
    }
    service.validate_handover_content(record)

    record["defects"][0]["descripcion"] = ""
    with pytest.raises(service.PromotoraDemoError, match="required_field"):
        service.validate_handover_content(record)


def test_seed_is_explicit_and_idempotent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    assets = Path(__file__).resolve().parents[1] / "assets" / "promotora-demo"
    monkeypatch.setattr(service, "_storage_dir", lambda: tmp_path)
    monkeypatch.setattr(service, "_seed_assets_dir", lambda: assets)
    emitted: list[str] = []

    def fake_emit(_state: dict, record: dict) -> dict:
        emitted.append(record["record_id"])
        return {
            "bundle_id": f"BND-{record['record_id']}",
            "record_id": f"EB1-{record['record_id']}",
            "bundle_path": str(tmp_path / f"{record['record_id']}.zip"),
            "root_hash": "0" * 64,
            "signature_status": "signing_not_configured",
            "signature_algorithm": "Ed25519",
            "signature_public_key_id": "demo",
            "anchor_status": "anchor_pending",
            "anchor": {"network": "sepolia", "status": "anchor_pending"},
            "verification_url": "https://hrevn.com/verify/promotora-record/",
            "bundle_verification_url": "https://hrevn.com/verify/evidence-bundle/",
            "created_at": service._utc_now(),
        }

    monkeypatch.setattr(service, "_emit_record_bundle", fake_emit)
    first = service.seed_promotora_demo_once()
    second = service.seed_promotora_demo_once()

    assert len(first["records"]) == 6
    assert len(second["records"]) == 6
    assert len(emitted) == 6
    assert first["seed_completed"] is True
