from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator


class LeadCaptureRequest(BaseModel):
    email: str
    honey: str = ""
    subject: str | None = None
    source_page: Literal["chequeo-uso-ia", "en-ai-use-check"]
    product_interest: str | None = None
    language: Literal["es", "en"]
    result_level: Literal["low", "medium", "high", "critical"]
    result_eligibility: Literal["apto", "no_apto", "eligible", "not_eligible"]
    result_eligibility_reasons: list[str] = Field(default_factory=list)
    result_primary_use: str | None = None
    result_signals: list[str] = Field(default_factory=list)
    answers: dict[str, Any] = Field(default_factory=dict)
    page_url: str | None = None
    user_agent: str | None = None

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        email = value.strip()
        if "@" not in email or "." not in email.split("@")[-1]:
            raise ValueError("Invalid email address.")
        return email

    @field_validator("result_eligibility")
    @classmethod
    def normalize_eligibility(cls, value: str) -> str:
        return "no_apto" if value == "not_eligible" else "apto" if value == "eligible" else value


class ContactRequest(BaseModel):
    name: str
    email: str
    organization: str
    subject: str | None = None
    honey: str = ""
    source_page: Literal[
        "contacto",
        "en-contact",
        "chequeo-ia",
        "en-ai-implementation-check",
        "chequeo-uso-ia-formacion",
    ]
    product_interest: str | None = None
    language: Literal["es", "en"]
    landing: str | None = None
    profile_type: str | None = None
    ai_system_type: str | None = None
    current_situation: str | None = None
    objective: str | None = None
    message: str | None = None
    contact_consent: str | bool | None = None
    page_url: str | None = None
    user_agent: str | None = None

    @field_validator("name", "organization")
    @classmethod
    def validate_required_text(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("This field is required.")
        return text

    @field_validator("email")
    @classmethod
    def validate_contact_email(cls, value: str) -> str:
        email = value.strip()
        if "@" not in email or "." not in email.split("@")[-1]:
            raise ValueError("Invalid email address.")
        return email


class BaselineCheckRequest(BaseModel):
    task_type: str | None = None
    profile: str | None = None
    record: dict[str, Any] | None = None
    metadata: dict[str, Any] | None = None


class ProfileValidateRequest(BaseModel):
    profile: str
    record: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] | None = None


class VerifyBundleRequest(BaseModel):
    source: str


class GenerateBundleOptions(BaseModel):
    include_report_pdf: bool = False


BundleMode = Literal["verified_record_v1", "evidence_bundle_eb1"]


class GenerateBundleRequest(BaseModel):
    bundle_mode: BundleMode = "verified_record_v1"
    record: dict[str, Any]
    traces: list[dict[str, Any]] = Field(default_factory=list)
    options: GenerateBundleOptions | None = None


CourseLanguage = Literal["es", "en"]
CourseBlockCode = Literal["block_1", "block_2", "block_3", "block_4", "block_5", "block_6"]
CourseEnrollmentStatus = Literal["created", "in_progress", "completed", "abandoned", "cancelled"]
CourseSourcePage = Literal["chequeo-uso-ia-formacion", "en-ai-use-check-training"]
PolicyQuestionnaireSourcePage = Literal["chequeo-uso-ia-politica", "en-ai-use-policy"]
PolicyLanguage = Literal["es", "en", "both"]
PolicyScopeResult = Literal["start_basic", "start_reinforced", "outside_start_review"]
PolicyCaseStatus = Literal[
    "created",
    "questionnaire_in_progress",
    "questionnaire_submitted",
    "policy_generated",
    "policy_reviewed",
    "policy_issued",
    "archived",
]
PolicyDocumentKind = Literal["policy_internal", "policy_record"]
PolicyDocumentStatus = Literal["draft", "generated", "reviewed", "issued", "superseded", "failed", "revoked"]
CompanyStatus = Literal["created", "active", "archived"]
CompanyAdminStatus = Literal["invited", "active", "revoked", "archived"]
CompanyAdminAccessLevel = Literal["owner", "admin", "viewer"]
TrainingGroupStatus = Literal["draft", "inviting", "in_progress", "completed", "archived", "cancelled"]
CompanyParticipantStatus = Literal["invited", "opened", "in_progress", "completed", "certificate_issued", "cancelled", "bounced"]
TrainingGroupExportKind = Literal["participants_csv", "certificates_zip", "completion_report", "evidence_bundle"]
TrainingGroupExportStatus = Literal["queued", "generated", "failed", "expired"]
EnrollmentOrigin = Literal["self_serve", "company_invite", "admin_created"]


class CourseEnrollmentCreateRequest(BaseModel):
    full_name: str
    email: str
    organization_name: str
    language: CourseLanguage
    identity_confirmation_accepted: bool
    identity_confirmation_text_version: str = "v1"
    role: str | None = None
    course_version: str = "v1"
    source_page: CourseSourcePage
    source_path: str | None = None
    source_lead_id: str | None = None
    invite_token: str | None = None
    optional_block_6_enabled: bool = False
    page_url: str | None = None
    user_agent: str | None = None

    @field_validator("full_name", "organization_name", "course_version", "identity_confirmation_text_version")
    @classmethod
    def validate_required_text(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("This field is required.")
        return text

    @field_validator("role", "source_path", "source_lead_id", "invite_token", "page_url", "user_agent")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        text = value.strip()
        return text or None

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        email = value.strip().lower()
        if "@" not in email or "." not in email.split("@")[-1]:
            raise ValueError("Invalid email address.")
        return email

    @field_validator("identity_confirmation_accepted")
    @classmethod
    def require_identity_confirmation(cls, value: bool) -> bool:
        if value is not True:
            raise ValueError("Identity confirmation is required.")
        return value


class CourseBlockAttemptRequest(BaseModel):
    attempt_number: int = Field(ge=1)
    questions_presented: list[dict[str, Any]] = Field(default_factory=list)
    answers_submitted: list[dict[str, Any]] = Field(default_factory=list)
    score: int = Field(ge=0, le=5)
    passed: bool
    result_snapshot: dict[str, Any] = Field(default_factory=dict)


class CourseEnrollmentUpdateRequest(BaseModel):
    current_block_code: CourseBlockCode | None = None
    optional_block_6_enabled: bool | None = None
    last_seen_at: str | None = None
    status: CourseEnrollmentStatus | None = None

    @model_validator(mode="after")
    def ensure_any_field_present(self) -> "CourseEnrollmentUpdateRequest":
        if (
            self.current_block_code is None
            and self.optional_block_6_enabled is None
            and self.last_seen_at is None
            and self.status is None
        ):
            raise ValueError("At least one field must be provided.")
        return self

    @field_validator("last_seen_at")
    @classmethod
    def normalize_last_seen_at(cls, value: str | None) -> str | None:
        if value is None:
            return None
        text = value.strip()
        return text or None


class PolicyCaseCreateRequest(BaseModel):
    organization_legal_name: str
    organization_tax_id: str
    sector_label: str
    workforce_range: Literal["1_5", "6_10", "11_50", "51_250", "250_plus"]
    representative_name: str
    representative_role: str
    representative_email: str
    country_scope: str
    policy_language: PolicyLanguage
    source_page: PolicyQuestionnaireSourcePage
    source_lead_id: str | None = None
    page_url: str | None = None
    user_agent: str | None = None

    @field_validator(
        "organization_legal_name",
        "organization_tax_id",
        "sector_label",
        "representative_name",
        "representative_role",
        "country_scope",
    )
    @classmethod
    def validate_required_text(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("This field is required.")
        return text

    @field_validator("source_lead_id", "page_url", "user_agent")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        text = value.strip()
        return text or None

    @field_validator("representative_email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        email = value.strip().lower()
        if "@" not in email or "." not in email.split("@")[-1]:
            raise ValueError("Invalid email address.")
        return email


class PolicyQuestionnaireSubmissionRequest(BaseModel):
    questionnaire_id: Literal["hrevn_start_policy_questionnaire"] = "hrevn_start_policy_questionnaire"
    questionnaire_version: str = "v1"
    language: Literal["es", "en"] = "es"
    source_page: PolicyQuestionnaireSourcePage
    answers: dict[str, Any] = Field(default_factory=dict)
    representative_declaration_confirmed: bool
    page_url: str | None = None
    user_agent: str | None = None

    @field_validator("questionnaire_version")
    @classmethod
    def validate_questionnaire_version(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("Questionnaire version is required.")
        return text

    @field_validator("page_url", "user_agent")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        text = value.strip()
        return text or None

    @field_validator("representative_declaration_confirmed")
    @classmethod
    def require_representative_confirmation(cls, value: bool) -> bool:
        if value is not True:
            raise ValueError("Representative declaration confirmation is required.")
        return value

    @model_validator(mode="after")
    def ensure_answers_present(self) -> "PolicyQuestionnaireSubmissionRequest":
        if not self.answers:
            raise ValueError("Questionnaire answers are required.")
        return self


class PolicyDocumentGenerateRequest(BaseModel):
    source_submission_id: str | None = None
    language: Literal["es", "en"] = "es"
    document_kind: PolicyDocumentKind = "policy_internal"
    policy_version: str = "v1.0"
    title: str | None = None

    @field_validator("source_submission_id", "title")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        text = value.strip()
        return text or None

    @field_validator("policy_version")
    @classmethod
    def validate_policy_version(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("Policy version is required.")
        return text


class PolicyCaseUpdateRequest(BaseModel):
    status: PolicyCaseStatus | None = None
    latest_scope_result: PolicyScopeResult | None = None
    policy_language: PolicyLanguage | None = None

    @model_validator(mode="after")
    def ensure_any_field_present(self) -> "PolicyCaseUpdateRequest":
        if self.status is None and self.latest_scope_result is None and self.policy_language is None:
            raise ValueError("At least one field must be provided.")
        return self


class RequestCompanyMagicLinkRequest(BaseModel):
    email: str
    page_url: str | None = None
    user_agent: str | None = None

    @field_validator("page_url", "user_agent")
    @classmethod
    def normalize_optional_magic_link_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        text = value.strip()
        return text or None

    @field_validator("email")
    @classmethod
    def validate_magic_link_email(cls, value: str) -> str:
        email = value.strip().lower()
        if "@" not in email or "." not in email.split("@")[-1]:
            raise ValueError("Invalid email address.")
        return email


class ConsumeCompanyMagicLinkRequest(BaseModel):
    token: str
    page_url: str | None = None
    user_agent: str | None = None

    @field_validator("token")
    @classmethod
    def validate_magic_link_token(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("Magic link token is required.")
        return text

    @field_validator("page_url", "user_agent")
    @classmethod
    def normalize_optional_magic_link_consume_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        text = value.strip()
        return text or None


class CreateCompanyWithOwnerRequest(BaseModel):
    legal_name: str
    tax_id: str
    contact_email: str
    owner_full_name: str
    owner_email: str
    owner_job_title: str | None = None
    display_name: str | None = None
    country_scope: str = "spain"
    workforce_range: Literal["1_5", "6_10", "11_50", "51_250", "250_plus"] = "1_5"
    current_policy_case_id: str | None = None
    page_url: str | None = None
    user_agent: str | None = None

    @field_validator(
        "legal_name",
        "tax_id",
        "contact_email",
        "owner_full_name",
        "owner_email",
        "country_scope",
    )
    @classmethod
    def validate_required_company_with_owner_text(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("This field is required.")
        return text

    @field_validator("display_name", "owner_job_title", "current_policy_case_id", "page_url", "user_agent")
    @classmethod
    def normalize_optional_company_with_owner_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        text = value.strip()
        return text or None

    @field_validator("contact_email", "owner_email")
    @classmethod
    def validate_company_with_owner_email(cls, value: str) -> str:
        email = value.strip().lower()
        if "@" not in email or "." not in email.split("@")[-1]:
            raise ValueError("Invalid email address.")
        return email


class AcceptCompanyAdminInviteRequest(BaseModel):
    token: str
    page_url: str | None = None
    user_agent: str | None = None

    @field_validator("token")
    @classmethod
    def validate_company_admin_invite_token(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("Invite token is required.")
        return text

    @field_validator("page_url", "user_agent")
    @classmethod
    def normalize_optional_company_admin_invite_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        text = value.strip()
        return text or None


class CompanyCreateRequest(BaseModel):
    legal_name: str
    tax_id: str
    contact_email: str
    country_scope: str = "spain"
    workforce_range: Literal["1_5", "6_10", "11_50", "51_250", "250_plus"] = "1_5"
    display_name: str | None = None
    current_policy_case_id: str | None = None

    @field_validator("legal_name", "tax_id", "country_scope")
    @classmethod
    def validate_required_company_text(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("This field is required.")
        return text

    @field_validator("display_name", "current_policy_case_id")
    @classmethod
    def normalize_optional_company_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        text = value.strip()
        return text or None

    @field_validator("contact_email")
    @classmethod
    def validate_company_email(cls, value: str) -> str:
        email = value.strip().lower()
        if "@" not in email or "." not in email.split("@")[-1]:
            raise ValueError("Invalid email address.")
        return email


class CompanyAdminCreateRequest(BaseModel):
    full_name: str
    email: str
    access_level: CompanyAdminAccessLevel = "admin"
    job_title: str | None = None
    send_invite: bool = True

    @field_validator("full_name")
    @classmethod
    def validate_required_admin_name(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("This field is required.")
        return text

    @field_validator("job_title")
    @classmethod
    def normalize_optional_admin_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        text = value.strip()
        return text or None

    @field_validator("email")
    @classmethod
    def validate_admin_email(cls, value: str) -> str:
        email = value.strip().lower()
        if "@" not in email or "." not in email.split("@")[-1]:
            raise ValueError("Invalid email address.")
        return email


class CompanyAdminUpdateRequest(BaseModel):
    full_name: str | None = None
    access_level: CompanyAdminAccessLevel | None = None
    job_title: str | None = None
    status: CompanyAdminStatus | None = None

    @field_validator("full_name", "job_title")
    @classmethod
    def normalize_optional_admin_update_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        text = value.strip()
        return text or None

    @model_validator(mode="after")
    def ensure_any_admin_field_present(self) -> "CompanyAdminUpdateRequest":
        if self.full_name is None and self.access_level is None and self.job_title is None and self.status is None:
            raise ValueError("At least one field must be provided.")
        return self


class TrainingGroupCreateRequest(BaseModel):
    title: str
    course_version: str = "v1"
    default_language: PolicyLanguage = "es"
    description: str | None = None
    policy_case_id: str | None = None
    policy_document_id: str | None = None
    planned_start_date: str | None = None
    planned_end_date: str | None = None

    @field_validator("title", "course_version")
    @classmethod
    def validate_required_group_text(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("This field is required.")
        return text

    @field_validator("description", "policy_case_id", "policy_document_id", "planned_start_date", "planned_end_date")
    @classmethod
    def normalize_optional_group_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        text = value.strip()
        return text or None


class TrainingGroupUpdateRequest(BaseModel):
    status: TrainingGroupStatus | None = None
    title: str | None = None
    description: str | None = None
    planned_start_date: str | None = None
    planned_end_date: str | None = None

    @field_validator("title", "description", "planned_start_date", "planned_end_date")
    @classmethod
    def normalize_optional_group_update_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        text = value.strip()
        return text or None

    @model_validator(mode="after")
    def ensure_any_group_field_present(self) -> "TrainingGroupUpdateRequest":
        if (
            self.status is None
            and self.title is None
            and self.description is None
            and self.planned_start_date is None
            and self.planned_end_date is None
        ):
            raise ValueError("At least one field must be provided.")
        return self


class CompanyParticipantCreateRequest(BaseModel):
    full_name: str
    email: str
    language: CourseLanguage
    role: str | None = None
    employee_reference: str | None = None
    send_invite: bool = True

    @field_validator("full_name")
    @classmethod
    def validate_required_participant_name(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("This field is required.")
        return text

    @field_validator("role", "employee_reference")
    @classmethod
    def normalize_optional_participant_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        text = value.strip()
        return text or None

    @field_validator("email")
    @classmethod
    def validate_participant_email(cls, value: str) -> str:
        email = value.strip().lower()
        if "@" not in email or "." not in email.split("@")[-1]:
            raise ValueError("Invalid email address.")
        return email


class TrainingGroupParticipantsImportRequest(BaseModel):
    participants: list[CompanyParticipantCreateRequest] = Field(default_factory=list)
    send_invites: bool = True

    @model_validator(mode="after")
    def ensure_participants_present(self) -> "TrainingGroupParticipantsImportRequest":
        if not self.participants:
            raise ValueError("At least one participant is required.")
        return self


class CompanyParticipantUpdateRequest(BaseModel):
    full_name: str | None = None
    email: str | None = None
    status: CompanyParticipantStatus | None = None
    role: str | None = None
    language: CourseLanguage | None = None
    employee_reference: str | None = None

    @field_validator("full_name", "role", "employee_reference")
    @classmethod
    def normalize_optional_participant_update_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        text = value.strip()
        return text or None

    @field_validator("email")
    @classmethod
    def validate_optional_participant_email(cls, value: str | None) -> str | None:
        if value is None:
            return None
        email = value.strip().lower()
        if "@" not in email or "." not in email.split("@")[-1]:
            raise ValueError("Invalid email address.")
        return email

    @model_validator(mode="after")
    def ensure_any_participant_field_present(self) -> "CompanyParticipantUpdateRequest":
        if (
            self.full_name is None
            and self.email is None
            and self.status is None
            and self.role is None
            and self.language is None
            and self.employee_reference is None
        ):
            raise ValueError("At least one field must be provided.")
        return self


class TrainingGroupExportCreateRequest(BaseModel):
    export_kind: TrainingGroupExportKind


class CompanyParticipantInviteAcceptRequest(BaseModel):
    page_url: str | None = None
    user_agent: str | None = None

    @field_validator("page_url", "user_agent")
    @classmethod
    def normalize_optional_invite_accept_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        text = value.strip()
        return text or None
