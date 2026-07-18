from __future__ import annotations

from datetime import UTC, datetime
import ipaddress
from typing import Any
from uuid import uuid4

from ..models.requests import (
    PolicyCaseCreateRequest,
    PolicyCaseUpdateRequest,
    PolicyDocumentGenerateRequest,
    PolicyQuestionnaireSubmissionRequest,
)
from .db import connect_dict, qualified_table


class PolicyServiceError(RuntimeError):
    error_code = "policy_service_error"


class PolicyCaseNotFoundError(PolicyServiceError):
    error_code = "policy_case_not_found"


class PolicySubmissionNotFoundError(PolicyServiceError):
    error_code = "policy_submission_not_found"


class PolicyDocumentNotFoundError(PolicyServiceError):
    error_code = "policy_document_not_found"


def _now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


VALUE_LABELS: dict[str, dict[str, str]] = {
    "sector": {
        "services": "Servicios",
        "commerce": "Comercio",
        "industry": "Industria",
        "technology": "Tecnología",
        "professional_firm": "Despacho / asesoría / consultoría",
        "health": "Salud",
        "education": "Educación",
        "hospitality": "Hostelería / turismo",
        "construction": "Construcción / inmobiliario",
        "other": "Otro",
    },
    "workforce": {"1_5": "1-5", "6_10": "6-10", "11_50": "11-50", "51_250": "51-250", "250_plus": "+250"},
    "country_scope": {"spain": "España", "eu": "UE", "international": "Internacional", "other": "Otro"},
    "ai_tool": {
        "chatgpt": "ChatGPT",
        "copilot": "Copilot",
        "gemini": "Gemini",
        "claude": "Claude",
        "custom_internal_tool": "Herramienta propia",
        "other": "Otra",
    },
    "ai_tool_formal": {
        "chatgpt": "ChatGPT (OpenAI)",
        "copilot": "Microsoft Copilot",
        "gemini": "Gemini (Google)",
        "claude": "Claude (Anthropic)",
        "custom_internal_tool": "Herramienta propia",
        "other": "Otra herramienta",
    },
    "ai_use_case": {
        "drafting": "Redacción",
        "summaries": "Resumen",
        "translation": "Traducción",
        "data_analysis": "Análisis de datos",
        "customer_support": "Atención al cliente",
        "hr_selection": "RRHH / selección",
        "marketing": "Marketing",
        "accounting": "Contabilidad",
        "programming": "Programación",
        "other": "Otro",
    },
    "chatbot_function": {
        "faq": "Responde FAQ",
        "collects_handoff": "Recoge datos iniciales y deriva",
        "guides": "Orienta",
        "recommends": "Recomienda",
        "sensitive_complaints": "Gestiona reclamaciones sensibles",
        "other": "Otro",
    },
    "communication_channel": {
        "email": "correo electrónico",
        "meeting": "reunión presencial o virtual",
        "intranet": "intranet corporativa",
        "signature": "firma de aceptación",
        "training": "formación",
        "other": "otro canal",
    },
    "status": {
        "yes": "Sí",
        "no": "No",
        "unknown": "No lo sabemos",
        "planned": "Previsto / se va a crear",
        "sometimes": "A veces",
        "official": "Oficial",
        "informal": "Informal",
        "both": "Ambas",
        "annual": "Anual",
        "semiannual": "Semestral",
        "on_change": "Cuando cambien herramientas o riesgos",
        "defined": "Definido",
        "undefined": "Sin definir",
        "sensitive_only": "Solo en casos sensibles",
        "always": "Sí, siempre",
        "yes_with_review": "Sí, con revisión",
    },
}


EN_VALUE_LABELS: dict[str, dict[str, str]] = {
    "sector": {
        "services": "Services",
        "commerce": "Commerce",
        "industry": "Industry",
        "technology": "Technology",
        "professional_firm": "Law firm / advisory / consulting",
        "health": "Health",
        "education": "Education",
        "hospitality": "Hospitality / tourism",
        "construction": "Construction / real estate",
        "other": "Other",
    },
    "workforce": {"1_5": "1-5", "6_10": "6-10", "11_50": "11-50", "51_250": "51-250", "250_plus": "+250"},
    "country_scope": {"spain": "Spain", "eu": "EU", "international": "International", "other": "Other"},
    "ai_tool": {
        "chatgpt": "ChatGPT",
        "copilot": "Copilot",
        "gemini": "Gemini",
        "claude": "Claude",
        "custom_internal_tool": "Internal tool",
        "other": "Other",
    },
    "ai_tool_formal": {
        "chatgpt": "ChatGPT (OpenAI)",
        "copilot": "Microsoft Copilot",
        "gemini": "Gemini (Google)",
        "claude": "Claude (Anthropic)",
        "custom_internal_tool": "Internal tool",
        "other": "Other tool",
    },
    "ai_use_case": {
        "drafting": "Drafting",
        "summaries": "Summaries",
        "translation": "Translation",
        "data_analysis": "Data analysis",
        "customer_support": "Customer support",
        "hr_selection": "HR / selection",
        "marketing": "Marketing",
        "accounting": "Accounting",
        "programming": "Programming",
        "other": "Other",
    },
    "chatbot_function": {
        "faq": "FAQ responses",
        "collects_handoff": "Collects initial data and hands off",
        "guides": "Guides",
        "recommends": "Recommends",
        "sensitive_complaints": "Handles sensitive complaints",
        "other": "Other",
    },
    "communication_channel": {
        "email": "email",
        "meeting": "in-person or virtual meeting",
        "intranet": "corporate intranet",
        "signature": "acknowledgement signature",
        "training": "training",
        "other": "other channel",
    },
    "status": {
        "yes": "Yes",
        "no": "No",
        "unknown": "Unknown",
        "planned": "Planned",
        "sometimes": "Sometimes",
        "official": "Official",
        "informal": "Informal",
        "both": "Both",
        "annual": "Annual",
        "semiannual": "Semiannual",
        "on_change": "When tools or risks change",
        "defined": "Defined",
        "undefined": "Undefined",
        "sensitive_only": "Sensitive cases only",
        "always": "Yes, always",
        "yes_with_review": "Yes, with review",
    },
}


def _jsonb(value: Any):
    from psycopg.types.json import Jsonb

    return Jsonb(value)


def _table_cases() -> str:
    return qualified_table("hrevn_start_policy_cases")


def _table_submissions() -> str:
    return qualified_table("hrevn_start_policy_questionnaire_submissions")


def _table_documents() -> str:
    return qualified_table("hrevn_start_policy_documents")


def _table_activity_log() -> str:
    return qualified_table("hrevn_start_policy_activity_log")


def _sanitize_ip(value: str | None) -> str | None:
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return str(ipaddress.ip_address(text))
    except ValueError:
        return None


def _trim_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _strip_terminal_punctuation(value: Any) -> str | None:
    text = _trim_text(value)
    if text is None:
        return None
    return text.rstrip(" .;:")


def _ensure_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value).strip()
    return [text] if text else []


def _labels(language: str) -> dict[str, dict[str, str]]:
    return EN_VALUE_LABELS if language == "en" else VALUE_LABELS


def _label(value: Any, label_group: str, language: str) -> str:
    if value is None:
        return "-"
    text = str(value).strip()
    if not text:
        return "-"
    return _labels(language).get(label_group, {}).get(text, text)


def _label_list(values: list[str], label_group: str, language: str) -> str:
    if not values:
        return "-"
    return ", ".join(_label(item, label_group, language) for item in values)


def _same_value_set(left: list[str], right: list[str]) -> bool:
    return set(left) == set(right)


def _format_workforce_phrase(value: Any, language: str) -> str:
    text = str(value or "").strip()
    mapping_es = {
        "1_5": "entre 1 y 5 personas",
        "6_10": "entre 6 y 10 personas",
        "11_50": "entre 11 y 50 personas",
        "51_250": "entre 51 y 250 personas",
        "250_plus": "más de 250 personas",
    }
    mapping_en = {
        "1_5": "between 1 and 5 people",
        "6_10": "between 6 and 10 people",
        "11_50": "between 11 and 50 people",
        "51_250": "between 51 and 250 people",
        "250_plus": "more than 250 people",
    }
    mapping = mapping_en if language == "en" else mapping_es
    return mapping.get(text, _label(text, "workforce", language))


def _format_short_date(value: str | None, language: str) -> str:
    if not value:
        return "-"
    text = str(value).strip()
    if not text:
        return "-"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        try:
            dt = datetime.fromisoformat(f"{text}T00:00:00")
        except ValueError:
            return text
    if language == "en":
        months = [
            "January",
            "February",
            "March",
            "April",
            "May",
            "June",
            "July",
            "August",
            "September",
            "October",
            "November",
            "December",
        ]
        return f"{months[dt.month - 1]} {dt.day}, {dt.year}"
    months_es = [
        "enero",
        "febrero",
        "marzo",
        "abril",
        "mayo",
        "junio",
        "julio",
        "agosto",
        "septiembre",
        "octubre",
        "noviembre",
        "diciembre",
    ]
    return f"{dt.day} de {months_es[dt.month - 1]} de {dt.year}"


def _normalize_answers(answers: dict[str, Any]) -> dict[str, Any]:
    normalized: dict[str, Any] = {}
    for key, value in answers.items():
        if isinstance(value, str):
            text = value.strip()
            normalized[key] = text
        elif isinstance(value, list):
            normalized[key] = [str(item).strip() for item in value if str(item).strip()]
        elif isinstance(value, dict):
            normalized[key] = {
                str(sub_key).strip(): (sub_value.strip() if isinstance(sub_value, str) else sub_value)
                for sub_key, sub_value in value.items()
            }
        else:
            normalized[key] = value
    return normalized


def _derive_policy_risk_signals(answers: dict[str, Any]) -> dict[str, Any]:
    ai_usage_formality = answers.get("ai_usage_formality")
    chatbot_functions = set(_ensure_list(answers.get("chatbot_functions")))
    uses_client_data = answers.get("uses_client_data_in_ai") in {"yes", "sometimes"}
    uses_employee_data = answers.get("uses_employee_data_in_ai") in {"yes", "sometimes"}
    uses_financial_contract_data = answers.get("uses_financial_contract_data_in_ai") in {"yes", "sometimes"}
    chatbot_sensitive_functions = bool({"recommends", "sensitive_complaints"} & chatbot_functions)
    governance_gap = (
        answers.get("ai_responsible_status") == "undefined"
        or answers.get("data_criteria_status") in {"no", "informal"}
        or answers.get("ai_user_scope") == "unknown"
        or answers.get("incident_channel_status") in {"no", "planned"}
    )

    return {
        "shadow_ai_detected": ai_usage_formality in {"informal", "both"},
        "client_data_in_ai": uses_client_data,
        "employee_data_in_ai": uses_employee_data,
        "financial_or_contract_data_in_ai": uses_financial_contract_data,
        "chatbot_present": answers.get("has_chatbot") == "yes",
        "chatbot_sensitive_functions": chatbot_sensitive_functions,
        "chatbot_requires_deeper_review": answers.get("has_chatbot") == "yes" and chatbot_sensitive_functions,
        "governance_gap": governance_gap,
        "undefined_people_decision_policy": answers.get("people_decision_policy") == "undefined",
        "uses_personal_accounts": answers.get("ai_account_scope") in {"personal_accounts", "both"},
        "uses_corporate_accounts": answers.get("ai_account_scope") in {"corporate_accounts", "both"},
        "tool_list_known": len(_ensure_list(answers.get("ai_tools_used"))) > 0,
        "user_scope_known": answers.get("ai_user_scope") not in {None, "", "unknown"},
        "policy_needs_remedial_language": governance_gap
        or answers.get("uses_ai_tools") == "unknown"
        or len(_ensure_list(answers.get("ai_tools_used"))) == 0 and answers.get("uses_ai_tools") == "yes",
    }


def _derive_scope_result(answers: dict[str, Any], risk_signals: dict[str, Any]) -> str:
    if risk_signals["chatbot_requires_deeper_review"]:
        return "outside_start_review"

    if (
        answers.get("uses_ai_tools") == "unknown"
        and answers.get("ai_user_scope") == "unknown"
        and answers.get("data_criteria_status") == "no"
    ):
        return "outside_start_review"

    if (
        risk_signals["shadow_ai_detected"]
        or risk_signals["client_data_in_ai"]
        or risk_signals["employee_data_in_ai"]
        or risk_signals["financial_or_contract_data_in_ai"]
        or risk_signals["governance_gap"]
        or answers.get("has_chatbot") == "yes"
        or answers.get("people_decision_policy") in {"yes_with_review", "undefined"}
    ):
        return "start_reinforced"

    return "start_basic"


def _build_policy_document_context(case_row: dict[str, Any], answers: dict[str, Any], risk_signals: dict[str, Any]) -> dict[str, Any]:
    ai_usage_formality = answers.get("ai_usage_formality")
    human_review_policy = answers.get("human_review_policy")
    people_decision_policy = answers.get("people_decision_policy")
    individual_policy_acceptance_status = answers.get("individual_policy_acceptance_status")
    communication_evidence_mode = answers.get("communication_evidence_mode")

    return {
        "organization_legal_name": case_row["organization_legal_name"],
        "organization_tax_id": case_row["organization_tax_id"],
        "sector_label": answers.get("sector_other") or case_row["sector_label"],
        "workforce_range": case_row["workforce_range"],
        "representative_name": case_row["representative_name"],
        "representative_role": case_row["representative_role"],
        "contact_email": case_row["representative_email"],
        "country_scope": answers.get("country_scope") or case_row["country_scope"],
        "policy_language": answers.get("policy_language") or case_row["policy_language"],
        "policy_issue_date": answers.get("policy_issue_date"),
        "policy_effective_date": answers.get("policy_effective_date"),
        "policy_version": answers.get("policy_version") or "v1.0",
        "existing_policy_status": answers.get("existing_policy_status"),
        "ai_tools_used": _ensure_list(answers.get("ai_tools_used")),
        "ai_tools_allowed": _ensure_list(answers.get("ai_tools_allowed")),
        "ai_tools_prohibited": _ensure_list(answers.get("ai_tools_prohibited")),
        "ai_use_cases": _ensure_list(answers.get("ai_use_cases")),
        "ai_user_scope": answers.get("ai_user_scope"),
        "ai_usage_formality": ai_usage_formality,
        "account_type_for_ai_tools": answers.get("ai_account_scope"),
        "chatbot_present_status": answers.get("has_chatbot"),
        "chatbot_functions": _ensure_list(answers.get("chatbot_functions")),
        "chatbot_discloses_ai_status": answers.get("chatbot_discloses_ai"),
        "chatbot_has_human_handoff": answers.get("chatbot_has_handoff"),
        "client_data_usage_status": answers.get("uses_client_data_in_ai"),
        "employee_data_usage_status": answers.get("uses_employee_data_in_ai"),
        "financial_contract_data_usage_status": answers.get("uses_financial_contract_data_in_ai"),
        "data_criteria_status": answers.get("data_criteria_status"),
        "prior_authorization_required": answers.get("requires_prior_authorization") == "yes",
        "prior_authorization_cases": _ensure_list(answers.get("prior_authorization_cases")),
        "human_review_policy": human_review_policy,
        "people_decision_policy": people_decision_policy,
        "ai_responsible_name": answers.get("ai_responsible_name"),
        "ai_responsible_role": answers.get("ai_responsible_role"),
        "doubts_contact_channel": answers.get("doubts_contact_channel"),
        "incident_channel_status": answers.get("incident_channel_status"),
        "incident_channel_detail": answers.get("incident_channel_detail"),
        "policy_review_frequency": answers.get("policy_review_frequency"),
        "responsible_target_date_if_missing": answers.get("responsible_target_date_if_missing"),
        "policy_communication_channels": _ensure_list(answers.get("policy_communication_channels")),
        "individual_policy_acceptance_status": individual_policy_acceptance_status,
        "communication_evidence_mode": communication_evidence_mode,
        "uses_ai_tools": answers.get("uses_ai_tools") == "yes",
        "uses_chatbot": answers.get("has_chatbot") == "yes",
        "chatbot_requires_deeper_review": risk_signals["chatbot_requires_deeper_review"],
        "uses_client_data": risk_signals["client_data_in_ai"],
        "uses_employee_data": risk_signals["employee_data_in_ai"],
        "uses_financial_or_contract_data": risk_signals["financial_or_contract_data_in_ai"],
        "has_written_data_criteria": answers.get("data_criteria_status") == "written",
        "requires_prior_authorization": answers.get("requires_prior_authorization") == "yes",
        "human_review_required_always": human_review_policy == "always",
        "human_review_required_sensitive_only": human_review_policy == "sensitive_only",
        "allows_ai_for_people_affecting_decisions": people_decision_policy == "yes_with_review",
        "prohibits_ai_for_people_affecting_decisions": people_decision_policy == "no",
        "responsible_person_defined": answers.get("ai_responsible_status") == "defined",
        "incident_channel_defined": answers.get("incident_channel_status") == "yes",
        "individual_policy_acceptance_required": individual_policy_acceptance_status == "yes",
        "evidence_of_communication_required": communication_evidence_mode in {"communication_only", "acceptance_only", "both"},
        "uses_official_tools": ai_usage_formality == "official",
        "uses_shadow_ai": risk_signals["shadow_ai_detected"],
        "uses_personal_accounts": risk_signals["uses_personal_accounts"],
        "uses_corporate_accounts": risk_signals["uses_corporate_accounts"],
        "tool_list_known": risk_signals["tool_list_known"],
        "user_scope_known": risk_signals["user_scope_known"],
        "policy_needs_remedial_language": risk_signals["policy_needs_remedial_language"],
    }


def _build_policy_render_plan(context: dict[str, Any], scope_result: str) -> dict[str, Any]:
    return {
        "include_chatbot_block": bool(context.get("uses_chatbot")),
        "include_sensitive_data_block": bool(
            context.get("uses_client_data")
            or context.get("uses_employee_data")
            or context.get("uses_financial_or_contract_data")
        ),
        "include_prior_authorization_block": bool(context.get("requires_prior_authorization")),
        "include_people_decision_block": bool(
            context.get("allows_ai_for_people_affecting_decisions")
            or context.get("prohibits_ai_for_people_affecting_decisions")
            or context.get("people_decision_policy") == "undefined"
        ),
        "include_pending_measures_block": bool(context.get("policy_needs_remedial_language")),
        "include_reinforced_scope_notice": scope_result == "start_reinforced",
        "include_outside_start_notice": scope_result == "outside_start_review",
        "document_length_target": "medium" if scope_result == "start_basic" else "extended",
    }


def _render_policy_content(
    case_row: dict[str, Any],
    context: dict[str, Any],
    render_plan: dict[str, Any],
    scope_result: str,
    title: str,
    language: str,
) -> dict[str, Any]:
    is_en = language == "en"
    organization_name = case_row["organization_legal_name"]
    representative_name = context.get("representative_name") or case_row["representative_name"]
    representative_role = context.get("representative_role") or case_row["representative_role"]
    sector_label = _label(context.get("sector_label"), "sector", language)
    workforce_label = _format_workforce_phrase(context.get("workforce_range"), language)
    allowed_tool_codes = context.get("ai_tools_allowed") or []
    declared_tool_codes = context.get("ai_tools_used") or []
    allowed_tools = _label_list(allowed_tool_codes, "ai_tool_formal", language)
    declared_tools = _label_list(declared_tool_codes, "ai_tool_formal", language)
    declared_uses = _label_list(context.get("ai_use_cases") or [], "ai_use_case", language)
    data_criteria_status = context.get("data_criteria_status")
    doubts_channel = _strip_terminal_punctuation(context.get("doubts_contact_channel")) or context.get("contact_email") or "-"
    review_frequency = _label(context.get("policy_review_frequency"), "status", language)
    incident_channel_detail = _strip_terminal_punctuation(context.get("incident_channel_detail")) or doubts_channel
    communication_channels = _label_list(context.get("policy_communication_channels") or [], "communication_channel", language)
    prior_authorization_cases = _label_list(context.get("prior_authorization_cases") or [], "status", language)
    chatbot_functions = _label_list(context.get("chatbot_functions") or [], "chatbot_function", language)
    issue_date = _format_short_date(context.get("policy_issue_date"), language)
    effective_date = _format_short_date(context.get("policy_effective_date"), language)
    policy_version = context.get("policy_version") or "v1.0"

    summary_parts = [
        (
            f"Initial internal policy for {organization_name}."
            if is_en
            else f"Política interna inicial para {organization_name}."
        ),
        (
            "It transforms the declared questionnaire answers into initial internal rules on tools, data, human review and escalation."
            if is_en
            else "Transforma las respuestas declaradas en reglas internas iniciales sobre herramientas, datos, revisión humana y escalado."
        ),
    ]
    if scope_result == "start_reinforced":
        summary_parts.append(
            "It includes reinforced measures because the declared use still needs stronger controls."
            if is_en
            else "Incluye medidas reforzadas porque el uso declarado todavía necesita controles más claros."
        )
    if scope_result == "outside_start_review":
        summary_parts.append(
            "It should be treated as an initial base pending deeper legal, technical or compliance review."
            if is_en
            else "Debe tratarse como una base inicial pendiente de revisión jurídica, técnica o de cumplimiento más profunda."
        )

    sections: list[dict[str, Any]] = [
        {
            "id": "object",
            "title": "Purpose" if is_en else "Objeto y finalidad",
            "body": [
                (
                    f"This policy establishes the initial internal rules that govern the use of artificial intelligence tools in {organization_name}."
                    if is_en
                    else f"La presente política establece las normas internas iniciales que regulan el uso de herramientas de inteligencia artificial en {organization_name}."
                ),
                (
                    "Its purpose is to define which tools are authorised, for which purposes they may be used, what data may or may not be entered, what level of human review is required before using the results, and who must be contacted in the event of a doubt or incident."
                    if is_en
                    else "Su finalidad es definir qué herramientas están autorizadas, para qué finalidades pueden utilizarse, qué datos pueden o no introducirse, qué nivel de revisión humana se exige antes de utilizar los resultados y a quién debe acudirse en caso de duda o incidencia."
                ),
                (
                    "This policy does not constitute legal advice and does not certify full regulatory compliance. It is a documented initial internal step on which the organisation can continue building."
                    if is_en
                    else "Esta política no constituye asesoramiento legal ni certifica el cumplimiento completo de ninguna normativa. Es un primer paso interno, documentado y revisable, sobre el que la organización puede seguir construyendo."
                ),
            ],
        },
        {
            "id": "scope",
            "title": "Scope of application" if is_en else "Ámbito de aplicación",
            "body": [
                (
                    f"This policy applies to all persons working for {organization_name}, including employees, external collaborators and any person using AI tools on behalf of the organisation or with access to its data."
                    if is_en
                    else f"Esta política es de aplicación a todas las personas que trabajan en {organization_name}, incluyendo personal en plantilla, colaboradores externos y cualquier persona que utilice herramientas de IA en nombre de la empresa o con acceso a datos de la misma."
                ),
                (
                    f"The organisation operates in the {sector_label} sector and has an approximate workforce of {workforce_label}."
                    if is_en
                    else f"La empresa opera en el sector {sector_label} y cuenta con una plantilla aproximada de {workforce_label}."
                ),
            ],
        },
        {
            "id": "tools",
            "title": "Authorised tools" if is_en else "Herramientas autorizadas",
            "body": [
                *(
                    [
                        (
                            f"The organisation authorises the use of the following tools, which match those currently declared as in use: {allowed_tools}."
                            if is_en
                            else f"La empresa autoriza el uso de las siguientes herramientas, que coinciden con las declaradas actualmente en uso: {allowed_tools}."
                        )
                    ]
                    if _same_value_set(allowed_tool_codes, declared_tool_codes) and allowed_tool_codes
                    else [
                        (
                            f"The organisation authorises the use of the following AI tools for the purposes described in this policy: {allowed_tools}."
                            if is_en
                            else f"La empresa autoriza el uso de las siguientes herramientas de inteligencia artificial para las finalidades indicadas en esta política: {allowed_tools}."
                        ),
                        (
                            f"The questionnaire declared the following tools already in use: {declared_tools}."
                            if is_en
                            else f"En el cuestionario se han declarado actualmente en uso las siguientes herramientas: {declared_tools}."
                        ),
                    ]
                ),
                (
                    "The use of any other AI tool not included in this list is prohibited unless prior express authorisation is granted by the internal person responsible."
                    if is_en
                    else "El uso de cualquier otra herramienta de IA no incluida en esta lista queda prohibido salvo autorización previa y expresa del responsable interno designado."
                ),
            ],
        },
        {
            "id": "uses",
            "title": "Authorised uses" if is_en else "Usos autorizados",
            "body": [
                (
                    f"The authorised tools may be used for the following purposes: {declared_uses}."
                    if is_en
                    else f"Las herramientas autorizadas pueden utilizarse para las siguientes finalidades: {declared_uses}."
                ),
                (
                    "Any use not covered by this list requires prior internal consultation."
                    if is_en
                    else "Cualquier uso no contemplado en esta lista requiere consulta interna previa."
                ),
            ],
        },
    ]

    if render_plan["include_people_decision_block"]:
        if context.get("prohibits_ai_for_people_affecting_decisions"):
            sections[-1]["body"].append(
                "The use of AI for decisions or recommendations that directly affect people remains expressly prohibited, including recruitment, performance evaluation or disciplinary action."
                if is_en
                else "Queda expresamente prohibido utilizar IA para decisiones o recomendaciones que afecten directamente a personas, incluyendo selección de personal, evaluaciones de desempeño o medidas disciplinarias."
            )
        elif context.get("allows_ai_for_people_affecting_decisions"):
            sections[-1]["body"].append(
                "Where AI may influence decisions affecting people, no result may be used without explicit human intervention, review and approval."
                if is_en
                else "Cuando la IA pueda influir en decisiones que afecten a personas, ningún resultado podrá utilizarse sin intervención, revisión y aprobación humana expresa."
            )
        else:
            sections[-1]["body"].append(
                "The organisation has not yet fully defined its internal rule for decisions or recommendations affecting people, so no such use should be activated until that rule is documented."
                if is_en
                else "La empresa todavía no ha definido por completo su regla interna para decisiones o recomendaciones que afecten a personas, por lo que no debe activarse ese uso hasta que la regla quede documentada."
            )

    data_body: list[str] = []
    client_data_status = context.get("client_data_usage_status")
    employee_data_status = context.get("employee_data_usage_status")
    financial_data_status = context.get("financial_contract_data_usage_status")

    if client_data_status == "sometimes":
        data_body.append(
            (
                f"Occasional use of client data in AI tools has been declared. Until a formal protocol is defined, identifiable client data may not be entered without prior authorisation from {context.get('ai_responsible_name')}."
                if is_en and context.get("ai_responsible_name")
                else "Occasional use of client data in AI tools has been declared. Until an internal AI owner is formally designated, entering identifiable client data into AI tools remains prohibited. This restriction will remain in force until a formal protocol is approved."
                if is_en
                else f"Se ha identificado uso ocasional de datos de clientes en herramientas de IA. Mientras no se establezca un protocolo formal, queda prohibido introducir datos identificativos de clientes sin autorización previa de {context.get('ai_responsible_name')}."
                if context.get("ai_responsible_name")
                else "Se ha identificado uso ocasional de datos de clientes en herramientas de IA. Mientras no se designe un responsable interno de IA, queda prohibido introducir datos identificativos de clientes en herramientas de IA. Esta prohibición se mantendrá hasta que se apruebe un protocolo formal."
            )
        )
    elif client_data_status == "yes":
        data_body.append(
            "Use of client data in AI tools has been declared. That use must remain restricted to authorised cases and subject to a written internal criterion."
            if is_en
            else "Se ha declarado uso de datos de clientes en herramientas de IA. Ese uso debe quedar restringido a los supuestos autorizados y sometido a un criterio interno escrito."
        )
    else:
        data_body.append(
            "No client data use in AI tools has been declared. This restriction must remain in force unless expressly authorised and documented."
            if is_en
            else "No se ha declarado uso de datos de clientes en herramientas de IA. Esta restricción debe mantenerse salvo autorización expresa y documentada."
        )

    if employee_data_status in {"yes", "sometimes"}:
        data_body.append(
            "The use of employee or candidate data in AI tools requires reinforced caution and should not occur without an explicit internal rule and prior review."
            if is_en
            else "El uso de datos de empleados o candidatos en herramientas de IA exige cautela reforzada y no debe producirse sin regla interna explícita y revisión previa."
        )
    else:
        data_body.append(
            "No use of employee or candidate data in AI tools has been declared. This restriction must be maintained as an internal rule."
            if is_en
            else "No se ha declarado uso de datos de empleados o candidatos en herramientas de IA. Esta restricción debe mantenerse como norma interna."
        )

    if financial_data_status in {"yes", "sometimes"}:
        data_body.append(
            "Financial, contractual or strategic information must not be entered into AI tools without a specific prior authorisation framework."
            if is_en
            else "La información financiera, contractual o estratégica no debe introducirse en herramientas de IA sin un marco específico de autorización previa."
        )
    else:
        data_body.append(
            "No use of financial, contractual or strategic information in AI tools has been declared. This restriction is incorporated as an internal rule."
            if is_en
            else "No se ha declarado uso de información financiera, contractual o estratégica en herramientas de IA. Esta restricción queda incorporada como norma interna."
        )

    data_body.append(
        (
            "As a general rule, names, identification numbers, direct contact details, contracts, economic proposals, banking or tax data, strategic information and any data whose disclosure could harm the organisation or third parties must not be entered into AI tools."
            if is_en
            else "Como regla general, no deben introducirse en herramientas de IA nombres, documentos identificativos, datos directos de contacto, contratos, propuestas económicas, datos bancarios o fiscales, información estratégica ni cualquier dato cuya difusión pueda perjudicar a la empresa o a terceros."
        )
    )
    if data_criteria_status == "written":
        data_body.append(
            "The organisation states that it already has a written criterion on what data may or may not be entered into AI tools. That criterion must prevail over any more general informal practice."
            if is_en
            else "La empresa declara que ya existe un criterio escrito sobre qué datos pueden o no introducirse en herramientas de IA. Ese criterio debe prevalecer sobre cualquier práctica informal más general."
        )
    elif data_criteria_status == "informal":
        data_body.append(
            "The organisation states that some data criteria already exist, but only informally. Those criteria should be formalised in writing before this policy is treated as sufficient on its own."
            if is_en
            else "La empresa declara que ya existen algunos criterios sobre datos, pero solo de forma informal. Esos criterios deben formalizarse por escrito antes de tratar esta política como suficiente por sí sola."
        )
    else:
        data_body.append(
            "No written or informal data criterion has been declared. In the event of doubt, the responsible person must be consulted before entering any data."
            if is_en
            else "No se ha declarado ningún criterio escrito o informal sobre datos. En caso de duda, debe consultarse al responsable antes de introducir cualquier información."
        )

    sections.append(
        {
            "id": "data",
            "title": "Data and confidentiality" if is_en else "Datos y confidencialidad",
            "body": data_body,
        }
    )

    human_review_body = [
        (
            "Every output generated by an AI tool must be reviewed by a person before it is used, sent or published."
            if is_en
            else "Todo resultado generado por una herramienta de IA debe ser revisado por una persona antes de ser utilizado, enviado o publicado."
        ),
        (
            "The review must check, at a minimum, that the information is correct, verifiable, appropriate for the recipient and free of invented or unsupported statements."
            if is_en
            else "La revisión debe comprobar, como mínimo, que la información es correcta, verificable, adecuada para el destinatario y que no contiene afirmaciones inventadas o no contrastadas."
        ),
        (
            "Responsibility for the final result always rests with the person who uses it, not with the tool that generated it."
            if is_en
            else "La responsabilidad sobre el resultado final recae siempre en la persona que lo utiliza, no en la herramienta que lo generó."
        ),
    ]
    if context.get("human_review_policy") == "always":
        human_review_body.append(
            "Human review is mandatory in all cases before any externally visible use."
            if is_en
            else "La revisión humana es obligatoria en todos los casos antes de cualquier uso con proyección externa."
        )
    elif context.get("human_review_policy") == "sensitive_only":
        human_review_body.append(
            "At a minimum, human review is mandatory in sensitive cases, external communications and any scenario that could affect people or relevant business conditions."
            if is_en
            else "Como mínimo, la revisión humana es obligatoria en casos sensibles, comunicaciones externas y cualquier escenario que pueda afectar a personas o a condiciones relevantes del negocio."
        )
    sections.append(
        {
            "id": "human-review",
            "title": "Human review" if is_en else "Revisión humana",
            "body": human_review_body,
        }
    )

    if render_plan["include_chatbot_block"]:
        chatbot_body = [
            (
                f"The organisation declares an automated assistant or chatbot with the following functions: {chatbot_functions}."
                if is_en
                else f"La empresa declara un chatbot o asistente automatizado con las siguientes funciones: {chatbot_functions}."
            ),
            (
                f"The chatbot {'does' if context.get('chatbot_discloses_ai_status') == 'yes' else 'does not'} disclose to the user that they are interacting with an AI system."
                if is_en
                else (
                    "El chatbot informa al usuario de que está interactuando con un sistema automatizado."
                    if context.get("chatbot_discloses_ai_status") == "yes"
                    else "El chatbot no declara con suficiente claridad que es un sistema automatizado y esa medida debe corregirse."
                )
            ),
            (
                "Human handoff exists when the system cannot resolve the issue."
                if is_en
                else (
                    "Existe derivación a una persona cuando el sistema no puede resolver la consulta."
                    if context.get("chatbot_has_human_handoff") == "yes"
                    else "No se ha declarado una derivación humana suficientemente clara, por lo que esa medida debe definirse antes de ampliar el uso del chatbot."
                )
            ),
            (
                "If the chatbot expands into recommendations, sensitive complaints or higher-impact functions, this policy must be reviewed before those functions are activated."
                if is_en
                else "Si el chatbot amplía sus funciones a recomendaciones, reclamaciones sensibles o tareas de mayor impacto, esta política deberá revisarse antes de activar esas funciones."
            ),
        ]
        sections.append(
            {
                "id": "chatbot",
                "title": "Chatbot and automated assistance" if is_en else "Chatbot y atención automatizada",
                "body": chatbot_body,
            }
        )

    governance_body = [
        (
            f"Questions or incidents related to AI use must be communicated through the following channel: {doubts_channel}."
            if is_en
            else f"Cualquier duda o incidencia relacionada con el uso de IA debe comunicarse a través del siguiente canal: {doubts_channel}."
        ),
        (
            f"The organisation declares the following incident channel detail: {incident_channel_detail}."
            if is_en
            else f"La empresa declara el siguiente detalle de canal de incidencias: {incident_channel_detail}."
        ),
        (
            f"The person making this declaration is {representative_name}, acting as {representative_role}."
            if is_en
            else f"La persona que realiza esta declaración es {representative_name}, actuando como {representative_role}."
        ),
    ]
    if context.get("responsible_person_defined"):
        governance_body.append(
            (
                f"The organisation identifies {context.get('ai_responsible_name')} ({context.get('ai_responsible_role')}) as the internal person responsible for AI."
                if is_en
                else f"La empresa identifica a {context.get('ai_responsible_name')} ({context.get('ai_responsible_role')}) como responsable interno de IA."
            )
        )
    else:
        governance_body.append(
            (
                "No formally designated internal AI owner has been declared yet."
                if is_en
                else "Todavía no se ha declarado un responsable interno de IA designado formalmente."
            )
        )
    sections.append(
        {
            "id": "governance",
            "title": "Governance, doubts and incidents" if is_en else "Gobernanza, dudas e incidencias",
            "body": governance_body,
        }
    )

    if render_plan["include_pending_measures_block"]:
        pending_body = [
            (
                "This policy reflects an initial internal step. The following measures should be implemented before the framework is treated as fully operational."
                if is_en
                else "Esta política refleja un primer paso interno. Las siguientes medidas deben implantarse antes de tratar el marco como plenamente operativo."
            )
        ]
        pending_measures: list[str] = []
        if not context.get("responsible_person_defined"):
            pending_measures.append(
                (
                    f"Formally designate an internal AI owner before {context.get('responsible_target_date_if_missing') or 'the next review date'}."
                    if is_en
                    else f"Designar formalmente un responsable interno de IA antes de {context.get('responsible_target_date_if_missing') or 'la siguiente revisión prevista'}."
                )
            )
        if data_criteria_status in {"no", "informal"}:
            pending_measures.append(
                (
                    "Approve a written criterion explaining what data may and may not be entered into AI tools."
                    if is_en
                    else "Aprobar un criterio escrito que defina qué datos pueden y no pueden introducirse en herramientas de IA."
                )
            )
        if context.get("uses_shadow_ai") or not context.get("tool_list_known"):
            pending_measures.append(
                (
                    "Confirm the tools actually being used and detect any informal tools, browser extensions, plugins or mobile apps with AI features."
                    if is_en
                    else "Confirmar las herramientas realmente usadas y detectar cualquier herramienta informal, extensión de navegador, plugin o app móvil con funciones de IA."
                )
            )
        if context.get("incident_channel_status") != "yes":
            pending_measures.append(
                (
                    "Create a formal incident channel and define who records and evaluates AI-related incidents."
                    if is_en
                    else "Crear un canal formal de incidencias y definir quién registra y evalúa los incidentes relacionados con IA."
                )
            )
        if "training" not in (context.get("policy_communication_channels") or []):
            pending_measures.append(
                (
                    "Plan minimum staff training so the people using AI know this policy and the main responsible-use criteria."
                    if is_en
                    else "Planificar una formación mínima de plantilla para que las personas que usan IA conozcan esta política y los criterios básicos de uso responsable."
                )
            )
        pending_body.extend(pending_measures)
        sections.append(
            {
                "id": "pending",
                "title": "Pending implementation measures" if is_en else "Medidas pendientes de implantación",
                "body": pending_body,
                "items": pending_measures,
            }
        )

    review_body = [
        (
            f"This policy takes effect on {effective_date} and will be reviewed on a {review_frequency.lower()} basis, or earlier if there are relevant changes to tools, uses, risks or applicable regulation."
            if is_en
            else f"Esta política entra en vigor el {effective_date} y será revisada con periodicidad {review_frequency.lower()}, o antes si se producen cambios relevantes en herramientas, usos, riesgos o normativa aplicable."
        ),
        (
            f"The current version is {policy_version} and the issue date declared by the organisation is {issue_date}."
            if is_en
            else f"La versión actual es {policy_version} y la fecha de emisión declarada por la empresa es {issue_date}."
        ),
        (
            f"The organisation plans to communicate this policy through the following channels: {communication_channels}."
            if is_en
            else f"La empresa prevé comunicar esta política a través de los siguientes canales: {communication_channels}."
        ),
    ]
    if context.get("individual_policy_acceptance_required"):
        review_body.append(
            "Individual acknowledgement or acceptance by the staff is required as part of the implementation evidence."
            if is_en
            else "Se exigirá acuse o aceptación individual de la plantilla como parte de la evidencia de implantación."
        )
    sections.append(
        {
            "id": "review",
            "title": "Review, communication and entry into force" if is_en else "Revisión, comunicación y entrada en vigor",
            "body": review_body,
        }
    )

    disclaimer_body = [
        (
            "This document has been generated by HREVN Start from the answers provided by the organisation's representative. It reflects the declared situation and the internal intention expressed on the issue date. HREVN does not independently verify the accuracy of the answers, does not assess actual compliance with applicable regulation and does not replace professional legal advice. The organisation remains responsible for implementing, communicating and keeping this policy updated."
            if is_en
            else "Este documento ha sido generado por HREVN Start a partir de las respuestas proporcionadas por el representante de la empresa. Refleja la situación declarada y la voluntad interna manifestada en la fecha de emisión. HREVN no verifica de forma independiente la exactitud de las respuestas, no evalúa el cumplimiento real de la normativa aplicable y no sustituye el asesoramiento legal profesional. La empresa es responsable de implantar, comunicar y mantener actualizada esta política."
        )
    ]
    if render_plan["include_outside_start_notice"]:
        disclaimer_body.append(
            "The declared case exceeds the lightest HREVN Start layer and should be escalated to deeper legal, technical or compliance review."
            if is_en
            else "El caso declarado supera la capa más ligera de HREVN Start y debe escalarse a una revisión jurídica, técnica o de cumplimiento más profunda."
        )
    sections.append(
        {
            "id": "disclaimer",
            "title": "Scope notice" if is_en else "Nota de alcance",
            "body": disclaimer_body,
        }
    )

    return {"title": title, "summary": " ".join(summary_parts), "sections": sections}


def _iso(value) -> str | None:
    if not value:
        return None
    return value.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _record_activity_tx(
    cur,
    policy_case_id: str,
    event_type: str,
    event_payload: dict[str, Any],
    *,
    actor_type: str = "representative",
    submission_id: str | None = None,
    policy_document_id: str | None = None,
) -> None:
    cur.execute(
        f"""
        INSERT INTO {_table_activity_log()} (
          activity_id,
          policy_case_id,
          submission_id,
          policy_document_id,
          event_type,
          event_payload,
          actor_type
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        """,
        (
            str(uuid4()),
            policy_case_id,
            submission_id,
            policy_document_id,
            event_type,
            _jsonb(event_payload),
            actor_type,
        ),
    )


def _fetch_case_summary_tx(cur, policy_case_id: str) -> dict[str, Any]:
    cur.execute(
        f"""
        SELECT
          policy_case_id,
          status,
          organization_legal_name,
          organization_tax_id,
          sector_label,
          workforce_range,
          representative_name,
          representative_role,
          representative_email::text AS representative_email,
          country_scope,
          policy_language,
          source_page,
          source_lead_id,
          latest_scope_result,
          latest_submission_id,
          current_policy_document_id,
          created_at,
          updated_at
        FROM {_table_cases()}
        WHERE policy_case_id = %s
        """,
        (policy_case_id,),
    )
    row = cur.fetchone()
    if not row:
        raise PolicyCaseNotFoundError(f"Policy case not found: {policy_case_id}")
    return {
        "policy_case_id": str(row["policy_case_id"]),
        "status": row["status"],
        "organization_legal_name": row["organization_legal_name"],
        "organization_tax_id": row["organization_tax_id"],
        "sector_label": row["sector_label"],
        "workforce_range": row["workforce_range"],
        "representative_name": row["representative_name"],
        "representative_role": row["representative_role"],
        "representative_email": row["representative_email"],
        "country_scope": row["country_scope"],
        "policy_language": row["policy_language"],
        "source_page": row["source_page"],
        "source_lead_id": row["source_lead_id"],
        "latest_scope_result": row["latest_scope_result"],
        "latest_submission_id": str(row["latest_submission_id"]) if row["latest_submission_id"] else None,
        "current_policy_document_id": str(row["current_policy_document_id"]) if row["current_policy_document_id"] else None,
        "created_at": _iso(row["created_at"]),
        "updated_at": _iso(row["updated_at"]),
    }


def _fetch_submission_tx(cur, submission_id: str) -> dict[str, Any]:
    cur.execute(
        f"""
        SELECT
          submission_id,
          policy_case_id,
          questionnaire_id,
          questionnaire_version,
          language,
          source_page,
          submitted_at,
          scope_result,
          representative_declaration_confirmed,
          answers,
          normalized_answers,
          policy_document_context,
          policy_render_plan,
          policy_risk_signals
        FROM {_table_submissions()}
        WHERE submission_id = %s
        """,
        (submission_id,),
    )
    row = cur.fetchone()
    if not row:
        raise PolicySubmissionNotFoundError(f"Policy submission not found: {submission_id}")
    return {
        "submission_id": str(row["submission_id"]),
        "policy_case_id": str(row["policy_case_id"]),
        "questionnaire_id": row["questionnaire_id"],
        "questionnaire_version": row["questionnaire_version"],
        "language": row["language"],
        "source_page": row["source_page"],
        "submitted_at": _iso(row["submitted_at"]),
        "scope_result": row["scope_result"],
        "representative_declaration_confirmed": row["representative_declaration_confirmed"],
        "answers": row["answers"] or {},
        "normalized_answers": row["normalized_answers"] or {},
        "policy_document_context": row["policy_document_context"] or {},
        "policy_render_plan": row["policy_render_plan"] or {},
        "policy_risk_signals": row["policy_risk_signals"] or {},
    }


def _fetch_document_tx(cur, policy_document_id: str) -> dict[str, Any]:
    cur.execute(
        f"""
        SELECT
          policy_document_id,
          policy_case_id,
          source_submission_id,
          supersedes_document_id,
          language,
          policy_version,
          document_kind,
          status,
          scope_result,
          title,
          created_at,
          updated_at,
          issued_at,
          context_snapshot,
          render_plan,
          rendered_content,
          storage_path,
          sha256,
          artifact_id,
          verification_code,
          verification_url,
          anchor_network,
          anchor_status,
          anchor_method,
          anchor_transaction_reference,
          anchored_at,
          anchor_error,
          metadata
        FROM {_table_documents()}
        WHERE policy_document_id = %s
        """,
        (policy_document_id,),
    )
    row = cur.fetchone()
    if not row:
        raise PolicyDocumentNotFoundError(f"Policy document not found: {policy_document_id}")
    return {
        "policy_document_id": str(row["policy_document_id"]),
        "policy_case_id": str(row["policy_case_id"]),
        "source_submission_id": str(row["source_submission_id"]) if row["source_submission_id"] else None,
        "supersedes_document_id": str(row["supersedes_document_id"]) if row["supersedes_document_id"] else None,
        "language": row["language"],
        "policy_version": row["policy_version"],
        "document_kind": row["document_kind"],
        "status": row["status"],
        "scope_result": row["scope_result"],
        "title": row["title"],
        "created_at": _iso(row["created_at"]),
        "updated_at": _iso(row["updated_at"]),
        "issued_at": _iso(row["issued_at"]),
        "context_snapshot": row["context_snapshot"] or {},
        "render_plan": row["render_plan"] or {},
        "rendered_content": row["rendered_content"] or {},
        "storage_path": row["storage_path"],
        "metadata": row["metadata"] or {},
        "artifact": {
            "artifact_id": row["artifact_id"],
            "verification_code": row["verification_code"],
            "verification_url": row["verification_url"],
            "sha256": row["sha256"],
            "anchor": {
                "root_hash": (row["metadata"] or {}).get("anchor_payload_sha256"),
                "network": row["anchor_network"],
                "anchor_method": row["anchor_method"],
                "transaction_reference": row["anchor_transaction_reference"],
                "anchored_at": _iso(row["anchored_at"]),
                "status": row["anchor_status"],
                "error": row["anchor_error"],
            }
            if row["anchor_status"] or row["anchor_network"] or row["anchor_transaction_reference"] or row["anchor_error"]
            else None,
        },
    }


def _load_policy_case_bundle_tx(cur, policy_case_id: str) -> dict[str, Any]:
    policy_case = _fetch_case_summary_tx(cur, policy_case_id)
    latest_submission = None
    current_policy_document = None
    if policy_case["latest_submission_id"]:
        latest_submission = _fetch_submission_tx(cur, policy_case["latest_submission_id"])
    if policy_case["current_policy_document_id"]:
        current_policy_document = _fetch_document_tx(cur, policy_case["current_policy_document_id"])
    return {
        "policy_case": policy_case,
        "latest_submission": latest_submission,
        "current_policy_document": current_policy_document,
    }


def _request_context(http_request_context: dict[str, Any] | None) -> tuple[str | None, str | None]:
    http_request_context = http_request_context or {}
    return _sanitize_ip(http_request_context.get("client_ip")), _trim_text(http_request_context.get("user_agent"))


def create_policy_case(
    request: PolicyCaseCreateRequest, request_context: dict[str, Any] | None = None
) -> dict[str, Any]:
    client_ip, user_agent = _request_context(request_context)
    with connect_dict() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT policy_case_id
                FROM {_table_cases()}
                WHERE organization_tax_id = %s
                  AND representative_email = %s
                  AND status <> 'archived'
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (request.organization_tax_id, request.representative_email),
            )
            existing = cur.fetchone()
            if existing:
                return _fetch_case_summary_tx(cur, str(existing["policy_case_id"]))

            policy_case_id = str(uuid4())
            cur.execute(
                f"""
                INSERT INTO {_table_cases()} (
                  policy_case_id,
                  status,
                  organization_legal_name,
                  organization_tax_id,
                  sector_label,
                  workforce_range,
                  representative_name,
                  representative_role,
                  representative_email,
                  country_scope,
                  policy_language,
                  source_page,
                  source_lead_id,
                  metadata
                )
                VALUES (%s, 'created', %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    policy_case_id,
                    request.organization_legal_name,
                    request.organization_tax_id,
                    request.sector_label,
                    request.workforce_range,
                    request.representative_name,
                    request.representative_role,
                    request.representative_email,
                    request.country_scope,
                    request.policy_language,
                    request.source_page,
                    request.source_lead_id,
                    _jsonb(
                        {
                            "page_url": request.page_url,
                            "user_agent": request.user_agent or user_agent,
                            "created_from_ip": client_ip,
                        }
                    ),
                ),
            )
            _record_activity_tx(
                cur,
                policy_case_id,
                "policy_case_created",
                {
                    "source_page": request.source_page,
                    "source_lead_id": request.source_lead_id,
                    "policy_language": request.policy_language,
                },
            )
            return _fetch_case_summary_tx(cur, policy_case_id)


def load_policy_case(policy_case_id: str) -> dict[str, Any]:
    with connect_dict() as conn:
        with conn.cursor() as cur:
            return _load_policy_case_bundle_tx(cur, policy_case_id)


def update_policy_case(policy_case_id: str, request: PolicyCaseUpdateRequest) -> dict[str, Any]:
    with connect_dict() as conn:
        with conn.cursor() as cur:
            _fetch_case_summary_tx(cur, policy_case_id)
            updates: list[str] = []
            values: list[Any] = []
            if request.status is not None:
                updates.append("status = %s")
                values.append(request.status)
            if request.latest_scope_result is not None:
                updates.append("latest_scope_result = %s")
                values.append(request.latest_scope_result)
            if request.policy_language is not None:
                updates.append("policy_language = %s")
                values.append(request.policy_language)

            if not updates:
                raise ValueError("No policy case fields to update.")

            values.append(policy_case_id)
            cur.execute(
                f"""
                UPDATE {_table_cases()}
                SET {", ".join(updates)}
                WHERE policy_case_id = %s
                """,
                tuple(values),
            )
            _record_activity_tx(
                cur,
                policy_case_id,
                "policy_case_updated",
                {
                    "status": request.status,
                    "latest_scope_result": request.latest_scope_result,
                    "policy_language": request.policy_language,
                },
                actor_type="admin",
            )
            return _fetch_case_summary_tx(cur, policy_case_id)


def create_policy_questionnaire_submission(
    policy_case_id: str,
    request: PolicyQuestionnaireSubmissionRequest,
    request_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    client_ip, user_agent = _request_context(request_context)
    submitted_at = _now_iso()
    with connect_dict() as conn:
        with conn.cursor() as cur:
            case_summary = _fetch_case_summary_tx(cur, policy_case_id)
            normalized_answers = _normalize_answers(request.answers)
            risk_signals = _derive_policy_risk_signals(normalized_answers)
            scope_result = _derive_scope_result(normalized_answers, risk_signals)
            document_context = _build_policy_document_context(case_summary, normalized_answers, risk_signals)
            render_plan = _build_policy_render_plan(document_context, scope_result)

            submission_id = str(uuid4())
            cur.execute(
                f"""
                INSERT INTO {_table_submissions()} (
                  submission_id,
                  policy_case_id,
                  submitted_at,
                  questionnaire_id,
                  questionnaire_version,
                  language,
                  source_page,
                  page_url,
                  user_agent,
                  ip_address,
                  answers,
                  normalized_answers,
                  policy_document_context,
                  policy_render_plan,
                  policy_risk_signals,
                  scope_result,
                  representative_declaration_confirmed,
                  metadata
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    submission_id,
                    policy_case_id,
                    submitted_at,
                    request.questionnaire_id,
                    request.questionnaire_version,
                    request.language,
                    request.source_page,
                    request.page_url,
                    request.user_agent or user_agent,
                    client_ip,
                    _jsonb(request.answers),
                    _jsonb(normalized_answers),
                    _jsonb(document_context),
                    _jsonb(render_plan),
                    _jsonb(risk_signals),
                    scope_result,
                    request.representative_declaration_confirmed,
                    _jsonb(
                        {
                            "submitted_from_ip": client_ip,
                            "submitted_user_agent": request.user_agent or user_agent,
                        }
                    ),
                ),
            )

            cur.execute(
                f"""
                UPDATE {_table_cases()}
                SET
                  status = 'questionnaire_submitted',
                  latest_scope_result = %s,
                  latest_submission_id = %s,
                  policy_language = %s
                WHERE policy_case_id = %s
                """,
                (scope_result, submission_id, normalized_answers.get("policy_language") or case_summary["policy_language"], policy_case_id),
            )
            _record_activity_tx(
                cur,
                policy_case_id,
                "questionnaire_submitted",
                {
                    "questionnaire_version": request.questionnaire_version,
                    "scope_result": scope_result,
                },
                submission_id=submission_id,
            )
            return {
                "policy_case": _fetch_case_summary_tx(cur, policy_case_id),
                "submission": _fetch_submission_tx(cur, submission_id),
            }


def generate_policy_document(policy_case_id: str, request: PolicyDocumentGenerateRequest) -> dict[str, Any]:
    with connect_dict() as conn:
        with conn.cursor() as cur:
            case_summary = _fetch_case_summary_tx(cur, policy_case_id)
            submission_id = request.source_submission_id or case_summary["latest_submission_id"]
            if not submission_id:
                raise PolicySubmissionNotFoundError(
                    f"No questionnaire submission available for policy case: {policy_case_id}"
                )
            submission = _fetch_submission_tx(cur, submission_id)
            if submission["policy_case_id"] != policy_case_id:
                raise PolicySubmissionNotFoundError(
                    f"Submission {submission_id} does not belong to policy case {policy_case_id}"
                )

            title = request.title or (
                "Politica interna de uso responsable de inteligencia artificial"
                if request.language == "es"
                else "Internal policy for the responsible use of artificial intelligence"
            )
            rendered_content = _render_policy_content(
                case_summary,
                submission["policy_document_context"],
                submission["policy_render_plan"],
                submission["scope_result"],
                title,
                request.language,
            )

            previous_document_id = case_summary["current_policy_document_id"]
            if previous_document_id:
                cur.execute(
                    f"""
                    UPDATE {_table_documents()}
                    SET status = 'superseded'
                    WHERE policy_document_id = %s
                      AND status IN ('draft', 'generated', 'reviewed', 'issued')
                    """,
                    (previous_document_id,),
                )

            policy_document_id = str(uuid4())
            cur.execute(
                f"""
                INSERT INTO {_table_documents()} (
                  policy_document_id,
                  policy_case_id,
                  source_submission_id,
                  supersedes_document_id,
                  language,
                  policy_version,
                  document_kind,
                  status,
                  scope_result,
                  title,
                  context_snapshot,
                  render_plan,
                  rendered_content
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, 'generated', %s, %s, %s, %s, %s)
                """,
                (
                    policy_document_id,
                    policy_case_id,
                    submission_id,
                    previous_document_id,
                    request.language,
                    request.policy_version,
                    request.document_kind,
                    submission["scope_result"],
                    title,
                    _jsonb(submission["policy_document_context"]),
                    _jsonb(submission["policy_render_plan"]),
                    _jsonb(rendered_content),
                ),
            )

            cur.execute(
                f"""
                UPDATE {_table_cases()}
                SET
                  status = 'policy_generated',
                  current_policy_document_id = %s
                WHERE policy_case_id = %s
                """,
                (policy_document_id, policy_case_id),
            )
            _record_activity_tx(
                cur,
                policy_case_id,
                "policy_generated",
                {
                    "source_submission_id": submission_id,
                    "policy_version": request.policy_version,
                    "document_kind": request.document_kind,
                    "language": request.language,
                },
                submission_id=submission_id,
                policy_document_id=policy_document_id,
                actor_type="system",
            )
            return {
                "policy_case": _fetch_case_summary_tx(cur, policy_case_id),
                "policy_document": _fetch_document_tx(cur, policy_document_id),
            }


def load_policy_document(policy_case_id: str, policy_document_id: str) -> dict[str, Any]:
    with connect_dict() as conn:
        with conn.cursor() as cur:
            policy_case = _fetch_case_summary_tx(cur, policy_case_id)
            policy_document = _fetch_document_tx(cur, policy_document_id)
            if policy_document["policy_case_id"] != policy_case_id:
                raise PolicyDocumentNotFoundError(
                    f"Policy document {policy_document_id} does not belong to policy case {policy_case_id}"
                )
            return {
                "policy_case": policy_case,
                "policy_document": policy_document,
            }
