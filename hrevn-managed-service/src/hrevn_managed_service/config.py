from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os
from typing import Any


SERVICE_ROOT = Path(__file__).resolve().parents[2]
WORKSPACE_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CORE_SRC = WORKSPACE_ROOT / "repo-core" / "src"
DEFAULT_VERIFIER_PLUGIN_ROOT = WORKSPACE_ROOT.parent / "_publish_hrevn_aer_verifier" / "hrevn_plugin"
DEFAULT_BUNDLES_DIR = SERVICE_ROOT / "storage" / "bundles"
DEFAULT_LEADS_DIR = SERVICE_ROOT / "storage" / "leads"
DEFAULT_COURSE_DIR = SERVICE_ROOT / "storage" / "course"
DEFAULT_POLICY_DIR = SERVICE_ROOT / "storage" / "policy"
DEFAULT_PROPERTY_DEMO_DIR = SERVICE_ROOT / "storage" / "property_demo"
DEFAULT_DB_SCHEMA = "public"
DEFAULT_PUBLIC_SITE_BASE_URL = "https://hrevn.com"
DEFAULT_PUBLIC_API_BASE_URL = "https://api.hrevn.com"
DEFAULT_COMPANY_ACCESS_PATH_PREFIX = "/empresa/acceso"
DEFAULT_COMPANY_INVITE_ACCEPT_PATH_PREFIX = "/empresa/aceptar-invitacion"
DEFAULT_PRIVATE_DEV_ORIGIN_REGEX = (
    r"^https?://("
    r"localhost|127\.0\.0\.1|"
    r"192\.168\.\d+\.\d+|"
    r"10\.\d+\.\d+\.\d+|"
    r"172\.(1[6-9]|2\d|3[0-1])\.\d+\.\d+"
    r")(:\d+)?$"
)


def _parse_api_keys(raw: str) -> dict[str, dict[str, Any]]:
    registry: dict[str, dict[str, Any]] = {}
    if not raw.strip():
        return registry

    for chunk in raw.split(","):
        item = chunk.strip()
        if not item:
            continue

        parts = [part.strip() for part in item.split(":")]
        api_key = parts[0]
        if not api_key:
            continue

        registry[api_key] = {
            "customer_id": parts[1] if len(parts) > 1 and parts[1] else "local-dev",
            "plan": parts[2] if len(parts) > 2 and parts[2] else "default",
            "license_id": parts[3] if len(parts) > 3 and parts[3] else None,
            "active": True,
        }
    return registry


def _parse_csv(raw: str) -> list[str]:
    return [item.strip() for item in raw.split(",") if item.strip()]


@dataclass(frozen=True)
class Settings:
    service_name: str = os.getenv("HREVN_MANAGED_SERVICE_NAME", "hrevn-managed-service")
    service_version: str = os.getenv("HREVN_MANAGED_SERVICE_VERSION", "0.1.0")
    core_src: Path = Path(os.getenv("HREVN_CORE_SRC", str(DEFAULT_CORE_SRC))).resolve()
    verifier_plugin_root: Path = Path(
        os.getenv("HREVN_VERIFIER_PLUGIN_ROOT", str(DEFAULT_VERIFIER_PLUGIN_ROOT))
    ).resolve()
    bundles_dir: Path = Path(os.getenv("HREVN_BUNDLES_DIR", str(DEFAULT_BUNDLES_DIR))).resolve()
    bundle_retention_hours: int = int(os.getenv("HREVN_BUNDLE_RETENTION_HOURS", "24"))
    managed_license_id: str = os.getenv("HREVN_MANAGED_LICENSE_ID", "LIC-MANAGED-LOCAL")
    managed_installation_id: str = os.getenv("HREVN_MANAGED_INSTALLATION_ID", "INST-MANAGED-LOCAL")
    require_api_key: bool = os.getenv("HREVN_REQUIRE_API_KEY", "false").lower() == "true"
    api_keys_raw: str = os.getenv("HREVN_API_KEYS", "")
    default_retention_hours: int = int(os.getenv("HREVN_DEFAULT_RETENTION_HOURS", "24"))
    database_url: str = os.getenv("HREVN_DATABASE_URL", "")
    database_schema: str = os.getenv("HREVN_DATABASE_SCHEMA", DEFAULT_DB_SCHEMA)
    public_site_base_url: str = os.getenv("HREVN_PUBLIC_SITE_BASE_URL", DEFAULT_PUBLIC_SITE_BASE_URL).rstrip("/")
    public_api_base_url: str = os.getenv("HREVN_PUBLIC_API_BASE_URL", DEFAULT_PUBLIC_API_BASE_URL).rstrip("/")
    course_verification_path_prefix: str = os.getenv(
        "HREVN_COURSE_VERIFICATION_PATH_PREFIX", "/verify/hrevn-start"
    ).rstrip("/")
    course_invitation_path_prefix_es: str = os.getenv(
        "HREVN_COURSE_INVITATION_PATH_PREFIX_ES", "/chequeo-uso-ia/formacion"
    ).rstrip("/")
    course_invitation_path_prefix_en: str = os.getenv(
        "HREVN_COURSE_INVITATION_PATH_PREFIX_EN", "/en/ai-use-check/training"
    ).rstrip("/")
    policy_verification_path_prefix: str = os.getenv(
        "HREVN_POLICY_VERIFICATION_PATH_PREFIX", "/verify/hrevn-start/policy"
    ).rstrip("/")
    company_access_path_prefix: str = os.getenv(
        "HREVN_COMPANY_ACCESS_PATH_PREFIX", DEFAULT_COMPANY_ACCESS_PATH_PREFIX
    ).rstrip("/")
    company_invite_accept_path_prefix: str = os.getenv(
        "HREVN_COMPANY_INVITE_ACCEPT_PATH_PREFIX", DEFAULT_COMPANY_INVITE_ACCEPT_PATH_PREFIX
    ).rstrip("/")
    company_admin_invite_ttl_hours: int = int(os.getenv("HREVN_COMPANY_ADMIN_INVITE_TTL_HOURS", "72"))
    company_magic_link_ttl_minutes: int = int(os.getenv("HREVN_COMPANY_MAGIC_LINK_TTL_MINUTES", "20"))
    company_session_ttl_days: int = int(os.getenv("HREVN_COMPANY_SESSION_TTL_DAYS", "14"))
    company_auth_cookie_name: str = os.getenv("HREVN_COMPANY_AUTH_COOKIE_NAME", "hrevn_company_session")
    company_auth_cookie_domain: str = os.getenv("HREVN_COMPANY_AUTH_COOKIE_DOMAIN", "").strip()
    company_auth_cookie_secure: bool = os.getenv("HREVN_COMPANY_AUTH_COOKIE_SECURE", "true").lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    company_auth_cookie_samesite: str = os.getenv("HREVN_COMPANY_AUTH_COOKIE_SAMESITE", "lax").strip().lower()
    hrevn_start_anchor_enabled: bool = os.getenv("HREVN_START_ANCHOR_ENABLED", "false").lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    hrevn_start_anchor_emit_real: bool = os.getenv("HREVN_START_ANCHOR_EMIT_REAL", "true").lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    hrevn_start_anchor_network: str = os.getenv("HREVN_START_ANCHOR_NETWORK", "sepolia").strip().lower()
    hrevn_start_anchor_method: str = os.getenv("HREVN_START_ANCHOR_METHOD", "hrevn_start_anchor").strip()
    hrevn_start_anchor_transaction_reference: str = os.getenv(
        "HREVN_START_ANCHOR_TRANSACTION_REFERENCE", ""
    ).strip()
    hrevn_start_anchor_explorer_base_url: str = os.getenv(
        "HREVN_START_ANCHOR_EXPLORER_BASE_URL",
        "https://sepolia.etherscan.io/tx/",
    ).strip()
    hrevn_start_sepolia_rpc_url: str = os.getenv("HREVN_START_SEPOLIA_RPC_URL", "").strip()
    hrevn_start_sepolia_private_key: str = os.getenv("HREVN_START_SEPOLIA_PRIVATE_KEY", "").strip()
    hrevn_start_sepolia_from_address: str = os.getenv("HREVN_START_SEPOLIA_FROM_ADDRESS", "").strip()
    hrevn_start_sepolia_wait_confirmations: int = int(
        os.getenv("HREVN_START_SEPOLIA_WAIT_CONFIRMATIONS", "1")
    )
    hrevn_eb_signing_algorithm: str = os.getenv("HREVN_EB_SIGNING_ALGORITHM", "Ed25519").strip()
    hrevn_eb_signing_private_key: str = os.getenv("HREVN_EB_SIGNING_PRIVATE_KEY", "").strip()
    hrevn_eb_signing_public_key: str = os.getenv("HREVN_EB_SIGNING_PUBLIC_KEY", "").strip()
    hrevn_eb_signing_public_key_id: str = os.getenv(
        "HREVN_EB_SIGNING_PUBLIC_KEY_ID", "hrevn-eb-ed25519-01"
    ).strip()
    hrevn_eb_anchor_emit_real: bool = os.getenv("HREVN_EB_ANCHOR_EMIT_REAL", "false").lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    hrevn_eb_anchor_network: str = os.getenv("HREVN_EB_ANCHOR_NETWORK", "base").strip().lower()
    hrevn_eb_anchor_method: str = os.getenv("HREVN_EB_ANCHOR_METHOD", "hrevn_managed_anchor").strip()
    hrevn_eb_anchor_explorer_base_url: str = os.getenv(
        "HREVN_EB_ANCHOR_EXPLORER_BASE_URL",
        "https://base.blockscout.com/tx/",
    ).strip()
    hrevn_eb_base_rpc_url: str = os.getenv("HREVN_EB_BASE_RPC_URL", "").strip()
    hrevn_eb_base_private_key: str = os.getenv("HREVN_EB_BASE_PRIVATE_KEY", "").strip()
    hrevn_eb_base_from_address: str = os.getenv("HREVN_EB_BASE_FROM_ADDRESS", "").strip()
    hrevn_eb_base_wait_confirmations: int = int(os.getenv("HREVN_EB_BASE_WAIT_CONFIRMATIONS", "1"))
    hrevn_eb_base_explorer_base_url: str = os.getenv(
        "HREVN_EB_BASE_EXPLORER_BASE_URL",
        "https://base.blockscout.com/tx/",
    ).strip()
    hrevn_eb_base_sepolia_rpc_url: str = os.getenv("HREVN_EB_BASE_SEPOLIA_RPC_URL", "").strip()
    hrevn_eb_base_sepolia_private_key: str = os.getenv("HREVN_EB_BASE_SEPOLIA_PRIVATE_KEY", "").strip()
    hrevn_eb_base_sepolia_from_address: str = os.getenv("HREVN_EB_BASE_SEPOLIA_FROM_ADDRESS", "").strip()
    hrevn_eb_base_sepolia_wait_confirmations: int = int(
        os.getenv("HREVN_EB_BASE_SEPOLIA_WAIT_CONFIRMATIONS", "1")
    )
    hrevn_eb_base_sepolia_explorer_base_url: str = os.getenv(
        "HREVN_EB_BASE_SEPOLIA_EXPLORER_BASE_URL",
        "https://sepolia-explorer.base.org/tx/",
    ).strip()
    course_review_recommendation_attempts_threshold: int = int(
        os.getenv("HREVN_COURSE_REVIEW_RECOMMENDATION_ATTEMPTS_THRESHOLD", "3")
    )
    lead_storage_dir: Path = Path(os.getenv("HREVN_LEAD_STORAGE_DIR", str(DEFAULT_LEADS_DIR))).resolve()
    course_storage_dir: Path = Path(os.getenv("HREVN_COURSE_STORAGE_DIR", str(DEFAULT_COURSE_DIR))).resolve()
    policy_storage_dir: Path = Path(os.getenv("HREVN_POLICY_STORAGE_DIR", str(DEFAULT_POLICY_DIR))).resolve()
    property_demo_storage_dir: Path = Path(
        os.getenv("HREVN_PROPERTY_DEMO_STORAGE_DIR", str(DEFAULT_PROPERTY_DEMO_DIR))
    ).resolve()
    property_demo_enabled: bool = os.getenv("HREVN_PROPERTY_DEMO_ENABLED", "true").lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    lead_allowed_origins_raw: str = os.getenv(
        "HREVN_LEAD_ALLOWED_ORIGINS",
        "https://hrevn.com,https://www.hrevn.com,http://127.0.0.1:4321,http://127.0.0.1:4322,http://localhost:4321,http://localhost:4322",
    )
    lead_allowed_origin_regex: str = os.getenv(
        "HREVN_LEAD_ALLOWED_ORIGIN_REGEX",
        DEFAULT_PRIVATE_DEV_ORIGIN_REGEX,
    )
    lead_smtp_host: str = os.getenv("HREVN_LEAD_SMTP_HOST", "")
    lead_smtp_port: int = int(os.getenv("HREVN_LEAD_SMTP_PORT", os.getenv("SMTP_PORT", "587")))
    lead_smtp_username: str = os.getenv(
        "HREVN_LEAD_SMTP_USERNAME", os.getenv("SMTP_USERNAME", os.getenv("GMAIL_USER", ""))
    )
    lead_smtp_password: str = os.getenv(
        "HREVN_LEAD_SMTP_PASSWORD", os.getenv("SMTP_PASSWORD", os.getenv("GMAIL_PASS", ""))
    )
    lead_smtp_use_tls: bool = os.getenv("HREVN_LEAD_SMTP_USE_TLS", "true").lower() in {"1", "true", "yes", "on"}
    lead_smtp_use_ssl: bool = os.getenv("HREVN_LEAD_SMTP_USE_SSL", "false").lower() in {"1", "true", "yes", "on"}
    lead_email_sender: str = os.getenv("HREVN_LEAD_EMAIL_SENDER", "") or os.getenv(
        "HREVN_LEAD_SMTP_USERNAME", os.getenv("SMTP_USERNAME", os.getenv("GMAIL_USER", "contact@hrevn.com"))
    )
    lead_email_recipient: str = os.getenv("HREVN_LEAD_EMAIL_RECIPIENT", "contact@hrevn.com")
    lead_email_cc_raw: str = os.getenv("HREVN_LEAD_EMAIL_CC", "")

    @property
    def api_keys(self) -> dict[str, dict[str, Any]]:
        return _parse_api_keys(self.api_keys_raw)

    @property
    def lead_allowed_origins(self) -> list[str]:
        return _parse_csv(self.lead_allowed_origins_raw)

    @property
    def lead_email_cc(self) -> list[str]:
        return _parse_csv(self.lead_email_cc_raw)


settings = Settings()
