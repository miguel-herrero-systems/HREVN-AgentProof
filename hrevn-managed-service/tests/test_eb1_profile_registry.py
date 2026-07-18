from hrevn_managed_service.services.eb1_profile_registry import resolve_eb1_package_type


def test_property_manager_profile_keeps_existing_package_type():
    assert resolve_eb1_package_type("property_manager_rental_visit_v1") == "property_manager_rental_visit_bundle"


def test_junta_profile_is_registered_for_future_vertical():
    assert resolve_eb1_package_type("junta_andalucia_property_event_v1") == "junta_andalucia_property_event_bundle"


def test_agentproof_profile_resolves_to_session_bundle():
    assert resolve_eb1_package_type("agentproof_codex_session_v1") == "agentproof_codex_session_bundle"


def test_unknown_profile_uses_generic_package_type():
    assert resolve_eb1_package_type("unknown_vertical_v1") == "generic_evidence_bundle"
