from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


from hrevn_managed_service.config import _parse_api_keys, settings


def test_parse_api_keys_supports_customer_plan_and_license_fields():
    parsed = _parse_api_keys("key-1:acme:pro:LIC-ACME-001,key-2:beta")

    assert parsed["key-1"]["customer_id"] == "acme"
    assert parsed["key-1"]["plan"] == "pro"
    assert parsed["key-1"]["license_id"] == "LIC-ACME-001"
    assert parsed["key-1"]["active"] is True

    assert parsed["key-2"]["customer_id"] == "beta"
    assert parsed["key-2"]["plan"] == "default"
    assert parsed["key-2"]["license_id"] is None


def test_default_verifier_plugin_root_exists_in_workspace():
    assert settings.verifier_plugin_root.exists()
    assert settings.verifier_plugin_root.name == "hrevn_plugin"
