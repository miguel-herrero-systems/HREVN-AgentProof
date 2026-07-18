from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class ErrorResponse(BaseModel):
    output_version: str = "1.0"
    result: str = "ERROR"
    error_code: str
    message: str


class HealthResponse(BaseModel):
    output_version: str = "1.0"
    status: str = "ok"


class VersionResponse(BaseModel):
    output_version: str = "1.0"
    service_name: str
    service_version: str
    core_version: str = "unknown"
    toolkit_version: str = "unknown"


class BaselineResponse(BaseModel):
    output_version: str = "1.0"
    result: str
    profile_detected: str
    readiness_level: str
    missing_required_blocks: list[str] = Field(default_factory=list)
    risk_flags: list[str] = Field(default_factory=list)
    recommended_next_step: str
    remedy_payload: dict[str, Any] = Field(default_factory=dict)
    check_id: str
    checked_at: str


class ProfileValidateResponse(BaseModel):
    output_version: str = "1.0"
    result: str = "PROFILE_VALIDATION_COMPLETE"
    profile: str
    validation_status: str
    readiness_level: str
    warnings: list[str] = Field(default_factory=list)
    details: dict[str, Any] = Field(default_factory=dict)


class VerifyBundleChecksumsResponse(BaseModel):
    valid: bool
    passed: list[str] = Field(default_factory=list)
    failed: list[dict[str, Any]] = Field(default_factory=list)
    missing: list[str] = Field(default_factory=list)
    unchecked: list[str] = Field(default_factory=list)


class VerifyBundleResponse(BaseModel):
    output_version: str = "1.0"
    tool: str
    source: str
    valid: bool
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    schema_version: str | None = None
    package_type: str | None = None
    manifest_hash: str | None = None
    root_hash_declared: str | None = None
    root_hash_computed: str | None = None
    root_hash_match: bool = False
    anchor: "BlockchainAnchorResponse | None" = None
    signature_status: str | None = None
    signature_valid: bool | None = None
    signature_algorithm: str | None = None
    signature_public_key_id: str | None = None
    checksums: VerifyBundleChecksumsResponse | None = None
    artifact_count: int | None = None
    aer_id: str | None = None


class GenerateBundleMetadataResponse(BaseModel):
    record_id: str
    verification_url: str | None = None
    schema_version: str
    bundle_mode: str | None = None
    bundle_profile: str | None = None
    package_type: str | None = None
    root_hash: str | None = None
    anchor_status: str | None = None
    anchor: "BlockchainAnchorResponse | None" = None
    signature_status: str | None = None
    signature_algorithm: str | None = None
    signature_public_key_id: str | None = None
    warnings: list[str] = Field(default_factory=list)


class GenerateBundleResponse(BaseModel):
    output_version: str = "1.0"
    result: str = "GENERATED"
    bundle_id: str
    download_url: str
    expires_at: str
    metadata: GenerateBundleMetadataResponse


LeadDeliveryStatus = Literal["emailed", "stored_only"]
BlockchainAnchorStatus = Literal["anchored", "anchor_pending", "anchor_failed"]


class BlockchainAnchorResponse(BaseModel):
    root_hash: str | None = None
    network: str | None = None
    anchor_method: str | None = None
    transaction_reference: str | None = None
    anchored_at: str | None = None
    status: BlockchainAnchorStatus | None = None
    block_number: int | None = None
    wallet_address: str | None = None
    explorer_url: str | None = None
    error: str | None = None


class LeadCaptureResponse(BaseModel):
    output_version: str = "1.0"
    result: str = "LEAD_CAPTURED"
    submission_id: str
    delivery_status: LeadDeliveryStatus
    email_error: str | None = None


class ContactCaptureResponse(BaseModel):
    output_version: str = "1.0"
    result: str = "CONTACT_CAPTURED"
    submission_id: str
    delivery_status: LeadDeliveryStatus
    email_error: str | None = None


CourseEnrollmentStatus = Literal["created", "in_progress", "completed", "abandoned", "cancelled"]
CourseCertificateStatus = Literal["not_issued", "queued", "issued", "failed", "revoked"]
CourseBlockCode = Literal["block_1", "block_2", "block_3", "block_4", "block_5", "block_6"]


class CourseReviewRecommendationResponse(BaseModel):
    recommended: bool = False
    threshold_attempts: int
    blocks: list[CourseBlockCode] = Field(default_factory=list)
    note: str | None = None


class CourseIdentityAttestationResponse(BaseModel):
    accepted: bool = False
    accepted_at: str | None = None
    text_version: str | None = None


class CourseAccessEvidenceResponse(BaseModel):
    first_access_at: str | None = None
    completed_at: str | None = None


class CourseCertificateArtifactResponse(BaseModel):
    artifact_id: str | None = None
    verification_code: str | None = None
    verification_url: str | None = None
    issued_at: str | None = None
    anchor: BlockchainAnchorResponse | None = None


class CourseBlockStatusResponse(BaseModel):
    block_code: CourseBlockCode
    passed: bool = False
    attempts_count: int = 0
    best_score: int | None = None
    last_score: int | None = None
    first_passed_at: str | None = None
    updated_at: str | None = None


class CourseEnrollmentStateResponse(BaseModel):
    enrollment_id: str
    status: CourseEnrollmentStatus
    full_name: str
    email: str
    organization_name: str
    language: Literal["es", "en"]
    role: str | None = None
    course_version: str
    optional_block_6_enabled: bool = False
    current_block_code: CourseBlockCode | None = None
    required_blocks_passed_count: int = 0
    required_course_completed: bool = False
    certificate_status: CourseCertificateStatus = "not_issued"
    started_at: str | None = None
    completed_at: str | None = None
    last_seen_at: str | None = None
    identity_attestation: CourseIdentityAttestationResponse
    access_evidence: CourseAccessEvidenceResponse
    certificate_artifact: CourseCertificateArtifactResponse
    review_recommendation: CourseReviewRecommendationResponse
    blocks: dict[CourseBlockCode, CourseBlockStatusResponse] = Field(default_factory=dict)


class CourseEnrollmentCreateResponse(BaseModel):
    output_version: str = "1.0"
    result: str = "COURSE_ENROLLMENT_CREATED"
    course: CourseEnrollmentStateResponse


class CourseEnrollmentLoadResponse(BaseModel):
    output_version: str = "1.0"
    result: str = "COURSE_ENROLLMENT_LOADED"
    course: CourseEnrollmentStateResponse


class CourseBlockAttemptResponse(BaseModel):
    output_version: str = "1.0"
    result: str = "COURSE_BLOCK_ATTEMPT_RECORDED"
    enrollment_id: str
    block_code: CourseBlockCode
    attempt_number: int
    passed: bool
    score: int
    course: CourseEnrollmentStateResponse


class CourseEnrollmentUpdateResponse(BaseModel):
    output_version: str = "1.0"
    result: str = "COURSE_ENROLLMENT_UPDATED"
    course: CourseEnrollmentStateResponse


class CourseCompleteResponse(BaseModel):
    output_version: str = "1.0"
    result: str = "COURSE_COMPLETED"
    enrollment_id: str
    required_course_completed: bool = True
    certificate_status: CourseCertificateStatus
    completed_at: str
    review_recommendation: CourseReviewRecommendationResponse
    course: CourseEnrollmentStateResponse


class CourseCertificateIssueResponse(BaseModel):
    output_version: str = "1.0"
    result: str = "COURSE_CERTIFICATE_ISSUED"
    enrollment_id: str
    certificate_status: CourseCertificateStatus
    download_url: str
    certificate_artifact: CourseCertificateArtifactResponse
    course: CourseEnrollmentStateResponse


class CourseCertificateVerifyRecordResponse(BaseModel):
    artifact_id: str
    verification_code: str
    verification_url: str
    issued_at: str
    language: Literal["es", "en"]
    participant_full_name: str
    organization_name: str
    course_version: str
    completed_at: str
    required_course_completed: bool = True
    certificate_status: CourseCertificateStatus
    identity_confirmed: bool = False
    review_recommendation: CourseReviewRecommendationResponse
    anchor: BlockchainAnchorResponse | None = None


class CourseCertificateVerifyResponse(BaseModel):
    output_version: str = "1.0"
    result: str = "COURSE_CERTIFICATE_VERIFIED"
    valid: bool = True
    certificate: CourseCertificateVerifyRecordResponse


PolicyCaseStatus = Literal[
    "created",
    "questionnaire_in_progress",
    "questionnaire_submitted",
    "policy_generated",
    "policy_reviewed",
    "policy_issued",
    "archived",
]
PolicyScopeResult = Literal["start_basic", "start_reinforced", "outside_start_review"]
PolicyDocumentKind = Literal["policy_internal", "policy_record"]
PolicyDocumentStatus = Literal["draft", "generated", "reviewed", "issued", "superseded", "failed", "revoked"]
PolicyLanguage = Literal["es", "en", "both"]
CompanyStatus = Literal["created", "active", "archived"]
CompanyAdminStatus = Literal["invited", "active", "revoked", "archived"]
CompanyAdminAccessLevel = Literal["owner", "admin", "viewer"]
TrainingGroupStatus = Literal["draft", "inviting", "in_progress", "completed", "archived", "cancelled"]
CompanyParticipantStatus = Literal["invited", "opened", "in_progress", "completed", "certificate_issued", "cancelled", "bounced"]
TrainingGroupExportKind = Literal["participants_csv", "certificates_zip", "completion_report", "evidence_bundle"]
TrainingGroupExportStatus = Literal["queued", "generated", "failed", "expired"]
EnrollmentOrigin = Literal["self_serve", "company_invite", "admin_created"]
CompanyParticipantInviteDeliveryStatus = Literal["emailed", "stored_only", "not_requested"]


class PolicyCaseSummaryResponse(BaseModel):
    policy_case_id: str
    status: PolicyCaseStatus
    organization_legal_name: str
    organization_tax_id: str
    sector_label: str
    workforce_range: Literal["1_5", "6_10", "11_50", "51_250", "250_plus"]
    representative_name: str
    representative_role: str
    representative_email: str
    country_scope: str
    policy_language: PolicyLanguage
    source_page: str
    source_lead_id: str | None = None
    latest_scope_result: PolicyScopeResult | None = None
    latest_submission_id: str | None = None
    current_policy_document_id: str | None = None
    created_at: str
    updated_at: str


class PolicyQuestionnaireSubmissionResponse(BaseModel):
    submission_id: str
    policy_case_id: str
    questionnaire_id: str
    questionnaire_version: str
    language: Literal["es", "en"]
    source_page: str
    submitted_at: str
    scope_result: PolicyScopeResult
    representative_declaration_confirmed: bool
    answers: dict[str, Any] = Field(default_factory=dict)
    normalized_answers: dict[str, Any] = Field(default_factory=dict)
    policy_document_context: dict[str, Any] = Field(default_factory=dict)
    policy_render_plan: dict[str, Any] = Field(default_factory=dict)
    policy_risk_signals: dict[str, Any] = Field(default_factory=dict)


class PolicyDocumentArtifactResponse(BaseModel):
    artifact_id: str | None = None
    verification_code: str | None = None
    verification_url: str | None = None
    sha256: str | None = None
    anchor: BlockchainAnchorResponse | None = None


class PolicyDocumentResponse(BaseModel):
    policy_document_id: str
    policy_case_id: str
    source_submission_id: str | None = None
    supersedes_document_id: str | None = None
    language: Literal["es", "en"]
    policy_version: str
    document_kind: PolicyDocumentKind
    status: PolicyDocumentStatus
    scope_result: PolicyScopeResult
    title: str
    created_at: str
    updated_at: str
    issued_at: str | None = None
    context_snapshot: dict[str, Any] = Field(default_factory=dict)
    render_plan: dict[str, Any] = Field(default_factory=dict)
    rendered_content: dict[str, Any] = Field(default_factory=dict)
    storage_path: str | None = None
    artifact: PolicyDocumentArtifactResponse = Field(default_factory=PolicyDocumentArtifactResponse)


class PolicyCaseCreateResponse(BaseModel):
    output_version: str = "1.0"
    result: str = "POLICY_CASE_CREATED"
    policy_case: PolicyCaseSummaryResponse


class PolicyCaseLoadResponse(BaseModel):
    output_version: str = "1.0"
    result: str = "POLICY_CASE_LOADED"
    policy_case: PolicyCaseSummaryResponse
    latest_submission: PolicyQuestionnaireSubmissionResponse | None = None
    current_policy_document: PolicyDocumentResponse | None = None


class PolicyQuestionnaireSubmissionCreateResponse(BaseModel):
    output_version: str = "1.0"
    result: str = "POLICY_QUESTIONNAIRE_SUBMITTED"
    policy_case: PolicyCaseSummaryResponse
    submission: PolicyQuestionnaireSubmissionResponse


class PolicyCaseUpdateResponse(BaseModel):
    output_version: str = "1.0"
    result: str = "POLICY_CASE_UPDATED"
    policy_case: PolicyCaseSummaryResponse


class PolicyDocumentGenerateResponse(BaseModel):
    output_version: str = "1.0"
    result: str = "POLICY_DOCUMENT_GENERATED"
    policy_case: PolicyCaseSummaryResponse
    policy_document: PolicyDocumentResponse


class PolicyDocumentLoadResponse(BaseModel):
    output_version: str = "1.0"
    result: str = "POLICY_DOCUMENT_LOADED"
    policy_case: PolicyCaseSummaryResponse
    policy_document: PolicyDocumentResponse


class PolicyDocumentIssueResponse(BaseModel):
    output_version: str = "1.0"
    result: str = "POLICY_DOCUMENT_ISSUED"
    policy_case_id: str
    policy_document_id: str
    document_status: PolicyDocumentStatus
    download_url: str
    policy_document: PolicyDocumentResponse


class PolicyDocumentVerifyRecordResponse(BaseModel):
    artifact_id: str
    verification_code: str
    verification_url: str
    issued_at: str
    language: Literal["es", "en"]
    organization_name: str
    organization_tax_id: str
    representative_name: str
    representative_role: str
    representative_email: str
    policy_version: str
    document_kind: PolicyDocumentKind
    document_status: PolicyDocumentStatus
    scope_result: PolicyScopeResult
    effective_date: str | None = None
    issue_date: str | None = None
    sha256: str | None = None
    representative_declaration_confirmed: bool = False
    anchor: BlockchainAnchorResponse | None = None


class PolicyDocumentVerifyResponse(BaseModel):
    output_version: str = "1.0"
    result: str = "POLICY_DOCUMENT_VERIFIED"
    valid: bool = True
    policy_document: PolicyDocumentVerifyRecordResponse


class CompanySummaryResponse(BaseModel):
    company_id: str
    status: CompanyStatus
    legal_name: str
    tax_id: str
    display_name: str | None = None
    contact_email: str
    country_scope: str
    workforce_range: Literal["1_5", "6_10", "11_50", "51_250", "250_plus"]
    current_policy_case_id: str | None = None
    created_at: str
    updated_at: str


class CompanyAdminResponse(BaseModel):
    company_admin_id: str
    company_id: str
    status: CompanyAdminStatus
    access_level: CompanyAdminAccessLevel
    full_name: str
    email: str
    job_title: str | None = None
    invited_at: str | None = None
    accepted_at: str | None = None
    last_seen_at: str | None = None
    last_login_at: str | None = None
    created_at: str
    updated_at: str


class CompanyActivityEntryResponse(BaseModel):
    company_activity_id: str
    company_id: str
    training_group_id: str | None = None
    training_group_title: str | None = None
    company_participant_id: str | None = None
    company_participant_name: str | None = None
    company_admin_id: str | None = None
    company_admin_name: str | None = None
    course_enrollment_id: str | None = None
    event_type: str
    event_payload: dict[str, Any] = Field(default_factory=dict)
    actor_type: Literal["company_admin", "participant", "system"]
    created_at: str


class TrainingGroupSummaryResponse(BaseModel):
    training_group_id: str
    company_id: str
    created_by_admin_id: str | None = None
    policy_case_id: str | None = None
    policy_document_id: str | None = None
    status: TrainingGroupStatus
    title: str
    description: str | None = None
    course_version: str
    default_language: PolicyLanguage
    planned_start_date: str | None = None
    planned_end_date: str | None = None
    launched_at: str | None = None
    closed_at: str | None = None
    participant_count: int = 0
    completed_count: int = 0
    certificate_issued_count: int = 0
    created_at: str
    updated_at: str


class CompanyParticipantResponse(BaseModel):
    company_participant_id: str
    company_id: str
    training_group_id: str
    invited_by_admin_id: str | None = None
    course_enrollment_id: str | None = None
    status: CompanyParticipantStatus
    full_name: str
    email: str
    role: str | None = None
    language: Literal["es", "en"]
    employee_reference: str | None = None
    invite_token: str
    invite_url: str | None = None
    invite_delivery_status: CompanyParticipantInviteDeliveryStatus = "not_requested"
    invite_email_error: str | None = None
    certificate_download_url: str | None = None
    invited_at: str | None = None
    opened_at: str | None = None
    started_at: str | None = None
    completed_at: str | None = None
    certificate_issued_at: str | None = None
    last_seen_at: str | None = None
    enrollment_origin: EnrollmentOrigin | None = None
    certificate_artifact: CourseCertificateArtifactResponse | None = None
    created_at: str
    updated_at: str


class TrainingGroupExportResponse(BaseModel):
    training_group_export_id: str
    company_id: str
    training_group_id: str
    requested_by_admin_id: str | None = None
    export_kind: TrainingGroupExportKind
    status: TrainingGroupExportStatus
    file_name: str | None = None
    download_url: str | None = None
    storage_path: str | None = None
    sha256: str | None = None
    availability_message: str | None = None
    generated_at: str | None = None
    expires_at: str | None = None
    created_at: str


class CompanyPolicyDocumentSummaryResponse(BaseModel):
    policy_case_id: str
    policy_document_id: str
    status: PolicyDocumentStatus
    language: Literal["es", "en"]
    policy_version: str
    title: str
    issued_at: str | None = None
    download_url: str
    verification_code: str | None = None
    verification_url: str | None = None


class CompanyParticipantInviteLoadResponse(BaseModel):
    output_version: str = "1.0"
    result: str = "COMPANY_PARTICIPANT_INVITE_LOADED"
    company: CompanySummaryResponse
    training_group: TrainingGroupSummaryResponse
    participant: CompanyParticipantResponse


class CompanyParticipantInviteAcceptResponse(BaseModel):
    output_version: str = "1.0"
    result: str = "COMPANY_PARTICIPANT_INVITE_ACCEPTED"
    company: CompanySummaryResponse
    training_group: TrainingGroupSummaryResponse
    participant: CompanyParticipantResponse


class CompanyCreateResponse(BaseModel):
    output_version: str = "1.0"
    result: str = "COMPANY_CREATED"
    company: CompanySummaryResponse


class CompanyLoadResponse(BaseModel):
    output_version: str = "1.0"
    result: str = "COMPANY_LOADED"
    company: CompanySummaryResponse
    admins: list[CompanyAdminResponse] = Field(default_factory=list)
    active_training_groups: list[TrainingGroupSummaryResponse] = Field(default_factory=list)


class CompanyActivityLoadResponse(BaseModel):
    output_version: str = "1.0"
    result: str = "COMPANY_ACTIVITY_LOADED"
    company: CompanySummaryResponse
    activity: list[CompanyActivityEntryResponse] = Field(default_factory=list)


class CompanyAccountContextResponse(BaseModel):
    company: CompanySummaryResponse
    admin: CompanyAdminResponse
    active_training_groups: list[TrainingGroupSummaryResponse] = Field(default_factory=list)


class CompanyMagicLinkRequestResponse(BaseModel):
    output_version: str = "1.0"
    result: str = "COMPANY_MAGIC_LINK_REQUEST_ACCEPTED"
    accepted: bool = True
    message: str


class CompanyAuthSessionResponse(BaseModel):
    output_version: str = "1.0"
    result: str = "COMPANY_AUTH_SESSION_CREATED"
    session_expires_at: str
    context: CompanyAccountContextResponse


class CompanyMeResponse(BaseModel):
    output_version: str = "1.0"
    result: str = "COMPANY_AUTH_CONTEXT_LOADED"
    context: CompanyAccountContextResponse


class CompanyAdminInviteResponse(BaseModel):
    output_version: str = "1.0"
    result: str = "COMPANY_ADMIN_INVITE_ACCEPTED"
    company: CompanySummaryResponse
    admin: CompanyAdminResponse


class CompanyCreateWithOwnerResponse(BaseModel):
    output_version: str = "1.0"
    result: str = "COMPANY_WITH_OWNER_CREATED"
    company: CompanySummaryResponse
    admin: CompanyAdminResponse


class CompanyAdminCreateResponse(BaseModel):
    output_version: str = "1.0"
    result: str = "COMPANY_ADMIN_CREATED"
    company: CompanySummaryResponse
    admin: CompanyAdminResponse


class CompanyAdminUpdateResponse(BaseModel):
    output_version: str = "1.0"
    result: str = "COMPANY_ADMIN_UPDATED"
    admin: CompanyAdminResponse


class TrainingGroupCreateResponse(BaseModel):
    output_version: str = "1.0"
    result: str = "TRAINING_GROUP_CREATED"
    company: CompanySummaryResponse
    training_group: TrainingGroupSummaryResponse


class TrainingGroupParticipantProgressBlockResponse(BaseModel):
    block_code: CourseBlockCode
    is_optional: bool = False
    passed: bool = False
    attempts_count: int = 0
    best_score: int | None = None
    best_score_percent: int | None = None
    last_score: int | None = None
    last_score_percent: int | None = None
    updated_at: str | None = None


class TrainingGroupParticipantProgressResponse(BaseModel):
    company_participant_id: str
    course_enrollment_id: str | None = None
    full_name: str
    email: str
    status: CompanyParticipantStatus
    required_course_completed: bool = False
    optional_block_6_enabled: bool = False
    current_block_code: CourseBlockCode | None = None
    blocks: list[TrainingGroupParticipantProgressBlockResponse] = Field(default_factory=list)


class TrainingGroupProgressResponse(BaseModel):
    visible_block_codes: list[CourseBlockCode] = Field(default_factory=list)
    participants: list[TrainingGroupParticipantProgressResponse] = Field(default_factory=list)


class TrainingGroupLoadResponse(BaseModel):
    output_version: str = "1.0"
    result: str = "TRAINING_GROUP_LOADED"
    company: CompanySummaryResponse
    training_group: TrainingGroupSummaryResponse
    policy_document: CompanyPolicyDocumentSummaryResponse | None = None
    participants: list[CompanyParticipantResponse] = Field(default_factory=list)
    progress: TrainingGroupProgressResponse | None = None
    exports: list[TrainingGroupExportResponse] = Field(default_factory=list)


class TrainingGroupUpdateResponse(BaseModel):
    output_version: str = "1.0"
    result: str = "TRAINING_GROUP_UPDATED"
    training_group: TrainingGroupSummaryResponse


class CompanyParticipantCreateResponse(BaseModel):
    output_version: str = "1.0"
    result: str = "COMPANY_PARTICIPANT_CREATED"
    training_group: TrainingGroupSummaryResponse
    participant: CompanyParticipantResponse


class TrainingGroupParticipantsImportResponse(BaseModel):
    output_version: str = "1.0"
    result: str = "TRAINING_GROUP_PARTICIPANTS_IMPORTED"
    training_group: TrainingGroupSummaryResponse
    participants: list[CompanyParticipantResponse] = Field(default_factory=list)


class CompanyParticipantUpdateResponse(BaseModel):
    output_version: str = "1.0"
    result: str = "COMPANY_PARTICIPANT_UPDATED"
    participant: CompanyParticipantResponse


class TrainingGroupExportCreateResponse(BaseModel):
    output_version: str = "1.0"
    result: str = "TRAINING_GROUP_EXPORT_REQUESTED"
    training_group: TrainingGroupSummaryResponse
    export: TrainingGroupExportResponse
