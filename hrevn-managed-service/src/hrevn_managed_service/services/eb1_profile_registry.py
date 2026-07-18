from __future__ import annotations


GENERIC_EVIDENCE_BUNDLE_PACKAGE_TYPE = "generic_evidence_bundle"

EB1_PROFILE_PACKAGE_TYPES: dict[str, str] = {
    "us_contractor_owner_dispute_v1": "us_contractor_owner_dispute_bundle",
    "property_manager_rental_visit_v1": "property_manager_rental_visit_bundle",
    "junta_andalucia_property_event_v1": "junta_andalucia_property_event_bundle",
    "promotora_construction_certificate_v1": "promotora_construction_certificate_bundle",
    "promotora_handover_review_v1": "promotora_handover_review_bundle",
}


def resolve_eb1_package_type(profile: str | None) -> str:
    if profile and profile in EB1_PROFILE_PACKAGE_TYPES:
        return EB1_PROFILE_PACKAGE_TYPES[profile]
    return GENERIC_EVIDENCE_BUNDLE_PACKAGE_TYPE
