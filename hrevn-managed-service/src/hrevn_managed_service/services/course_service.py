from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import secrets
from typing import Any
from uuid import uuid4

from ..config import settings
from ..models.requests import (
    CourseBlockAttemptRequest,
    CourseEnrollmentCreateRequest,
    CourseEnrollmentUpdateRequest,
)
from .db import connect_dict, qualified_table


COURSE_BLOCK_CODES = ("block_1", "block_2", "block_3", "block_4", "block_5", "block_6")
REQUIRED_BLOCK_CODES = ("block_1", "block_2", "block_3", "block_4", "block_5")


class CourseServiceError(RuntimeError):
    error_code = "course_service_error"


class CourseEnrollmentNotFoundError(CourseServiceError):
    error_code = "course_enrollment_not_found"


class CourseInviteNotFoundError(CourseServiceError):
    error_code = "course_invite_not_found"


class CourseCompletionBlockedError(CourseServiceError):
    error_code = "course_completion_blocked"


def _now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _validate_block_code(block_code: str) -> None:
    if block_code not in COURSE_BLOCK_CODES:
        raise ValueError(f"Invalid block code: {block_code}")


def _table_enrollments() -> str:
    return qualified_table("hrevn_start_course_enrollments")


def _table_attempts() -> str:
    return qualified_table("hrevn_start_course_block_attempts")


def _table_block_status() -> str:
    return qualified_table("hrevn_start_course_block_status")


def _table_activity_log() -> str:
    return qualified_table("hrevn_start_course_activity_log")


def _table_company_participants() -> str:
    return qualified_table("hrevn_start_company_participants")


def _table_companies() -> str:
    return qualified_table("hrevn_start_companies")


def _table_training_groups() -> str:
    return qualified_table("hrevn_start_training_groups")


def _table_company_activity_log() -> str:
    return qualified_table("hrevn_start_company_activity_log")


def _default_block_state(block_code: str) -> dict[str, Any]:
    return {
        "block_code": block_code,
        "passed": False,
        "attempts_count": 0,
        "best_score": None,
        "last_score": None,
        "first_passed_at": None,
        "updated_at": None,
    }


def _required_blocks_passed_count(blocks: dict[str, Any]) -> int:
    return sum(1 for code in REQUIRED_BLOCK_CODES if blocks.get(code, {}).get("passed") is True)


def _build_review_recommendation(blocks: dict[str, Any]) -> dict[str, Any]:
    threshold = max(2, settings.course_review_recommendation_attempts_threshold)
    recommended_blocks = [
        code
        for code in REQUIRED_BLOCK_CODES
        if int(blocks.get(code, {}).get("attempts_count") or 0) >= threshold
    ]
    recommended = len(recommended_blocks) > 0
    note = None
    if recommended:
        note = (
            "Review recommended for the blocks that required repeated attempts before passing. "
            "Consider refreshing those topics before using AI in more sensitive tasks."
        )
    return {
        "recommended": recommended,
        "threshold_attempts": threshold,
        "blocks": recommended_blocks,
        "note": note,
    }


def _sanitize_ip(value: str | None) -> str | None:
    if not value:
        return None
    text = str(value).strip()
    return text or None


def _build_identity_attestation(metadata: dict[str, Any]) -> dict[str, Any]:
    identity = metadata.get("identity_confirmation") or {}
    return {
        "accepted": bool(identity.get("accepted")),
        "accepted_at": identity.get("accepted_at"),
        "text_version": identity.get("text_version"),
    }


def _build_access_evidence(metadata: dict[str, Any], completed_at: str | None) -> dict[str, Any]:
    first_access = metadata.get("first_access") or {}
    completion_access = metadata.get("completion_access") or {}
    return {
        "first_access_at": first_access.get("at"),
        "completed_at": completion_access.get("at") or completed_at,
    }


def _build_certificate_artifact(metadata: dict[str, Any]) -> dict[str, Any]:
    artifact = metadata.get("certificate_artifact") or {}
    return {
        "artifact_id": artifact.get("artifact_id"),
        "verification_code": artifact.get("verification_code"),
        "verification_url": artifact.get("verification_url"),
        "issued_at": artifact.get("issued_at"),
        "anchor": artifact.get("anchor"),
    }


def _make_verification_code(issued_at: str) -> str:
    compact_date = issued_at[2:4] + issued_at[5:7]
    suffix = secrets.token_hex(2).upper()
    return f"HST-TRN-{compact_date}-{suffix}"


def _make_verification_url(artifact_id: str) -> str:
    return (
        f"{settings.public_site_base_url}"
        f"{settings.course_verification_path_prefix}/?artifact_id={artifact_id}"
    )


def _ensure_certificate_artifact(metadata: dict[str, Any], issued_at: str) -> tuple[dict[str, Any], bool]:
    artifact = dict(metadata.get("certificate_artifact") or {})
    changed = False

    artifact_id = artifact.get("artifact_id")
    if not artifact_id:
        artifact_id = str(uuid4())
        artifact["artifact_id"] = artifact_id
        changed = True

    if not artifact.get("verification_code"):
        artifact["verification_code"] = _make_verification_code(issued_at)
        changed = True

    verification_url = _make_verification_url(artifact_id)
    if artifact.get("verification_url") != verification_url:
        artifact["verification_url"] = verification_url
        changed = True

    if not artifact.get("issued_at"):
        artifact["issued_at"] = issued_at
        changed = True

    metadata["certificate_artifact"] = artifact
    return artifact, changed


def _jsonb(value: Any):
    from psycopg.types.json import Jsonb

    return Jsonb(value)


def _record_activity_tx(cur, enrollment_id: str, event_type: str, event_payload: dict[str, Any]) -> None:
    cur.execute(
        f"""
        INSERT INTO {_table_activity_log()} (
          activity_id,
          enrollment_id,
          event_type,
          event_payload,
          actor_type
        )
        VALUES (%s, %s, %s, %s, 'participant')
        """,
        (
            str(uuid4()),
            enrollment_id,
            event_type,
            _jsonb(event_payload),
        ),
    )


def _record_company_activity_tx(
    cur,
    company_id: str,
    event_type: str,
    event_payload: dict[str, Any],
    *,
    training_group_id: str | None = None,
    company_participant_id: str | None = None,
    course_enrollment_id: str | None = None,
) -> None:
    cur.execute(
        f"""
        INSERT INTO {_table_company_activity_log()} (
          company_activity_id,
          company_id,
          training_group_id,
          company_participant_id,
          course_enrollment_id,
          event_type,
          event_payload,
          actor_type
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, 'participant')
        """,
        (
            str(uuid4()),
            company_id,
            training_group_id,
            company_participant_id,
            course_enrollment_id,
            event_type,
            _jsonb(event_payload),
        ),
    )


def _refresh_training_group_counts_tx(cur, training_group_id: str) -> None:
    cur.execute(
        f"""
        WITH stats AS (
          SELECT
            COUNT(*)::integer AS participant_count,
            COUNT(*) FILTER (WHERE status IN ('completed', 'certificate_issued'))::integer AS completed_count,
            COUNT(*) FILTER (WHERE status = 'certificate_issued')::integer AS certificate_issued_count
          FROM {_table_company_participants()}
          WHERE training_group_id = %s
        )
        UPDATE {_table_training_groups()} AS groups
        SET
          participant_count = stats.participant_count,
          completed_count = stats.completed_count,
          certificate_issued_count = stats.certificate_issued_count
        FROM stats
        WHERE groups.training_group_id = %s
        """,
        (training_group_id, training_group_id),
    )


def _fetch_company_invite_tx(cur, invite_token: str) -> dict[str, Any]:
    cur.execute(
        f"""
        SELECT
          participant.company_participant_id,
          participant.company_id,
          participant.training_group_id,
          participant.course_enrollment_id,
          participant.status,
          participant.full_name,
          participant.email::text AS email,
          participant.role,
          participant.language,
          participant.invite_token,
          company.legal_name,
          company.display_name
        FROM {_table_company_participants()} AS participant
        JOIN {_table_companies()} AS company
          ON company.company_id = participant.company_id
        WHERE participant.invite_token = %s
        """,
        (invite_token,),
    )
    row = cur.fetchone()
    if not row:
        raise CourseInviteNotFoundError(f"Invite not found: {invite_token}")
    return {
        "company_participant_id": str(row["company_participant_id"]),
        "company_id": str(row["company_id"]),
        "training_group_id": str(row["training_group_id"]),
        "course_enrollment_id": str(row["course_enrollment_id"]) if row["course_enrollment_id"] else None,
        "status": row["status"],
        "full_name": row["full_name"],
        "email": row["email"],
        "role": row["role"],
        "language": row["language"],
        "invite_token": row["invite_token"],
        "organization_name": row["display_name"] or row["legal_name"],
    }


def _link_company_participant_to_enrollment_tx(
    cur,
    invite: dict[str, Any],
    enrollment_id: str,
    *,
    status: str = "opened",
    last_seen_at: str | None = None,
) -> None:
    cur.execute(
        f"""
        UPDATE {_table_company_participants()}
        SET
          course_enrollment_id = %s,
          status = CASE
            WHEN status IN ('completed', 'certificate_issued', 'cancelled', 'bounced') THEN status
            ELSE %s
          END,
          opened_at = COALESCE(opened_at, %s),
          last_seen_at = COALESCE(%s, last_seen_at)
        WHERE company_participant_id = %s
        """,
        (
            enrollment_id,
            status,
            last_seen_at,
            last_seen_at,
            invite["company_participant_id"],
        ),
    )
    _record_company_activity_tx(
        cur,
        invite["company_id"],
        "course_enrollment_linked",
        {
            "company_participant_id": invite["company_participant_id"],
            "course_enrollment_id": enrollment_id,
            "status": status,
        },
        training_group_id=invite["training_group_id"],
        company_participant_id=invite["company_participant_id"],
        course_enrollment_id=enrollment_id,
    )
    if invite.get("training_group_id"):
        _refresh_training_group_counts_tx(cur, invite["training_group_id"])


def _sync_company_participant_from_enrollment_tx(
    cur,
    enrollment_id: str,
    *,
    status: str,
    last_seen_at: str | None = None,
    started_at: str | None = None,
    completed_at: str | None = None,
    certificate_issued_at: str | None = None,
) -> None:
    cur.execute(
        f"""
        SELECT company_id, training_group_id, company_participant_id
        FROM {_table_enrollments()}
        WHERE enrollment_id = %s
        """,
        (enrollment_id,),
    )
    row = cur.fetchone()
    if not row or not row["company_participant_id"]:
        return

    cur.execute(
        f"""
        UPDATE {_table_company_participants()}
        SET
          status = %s,
          last_seen_at = COALESCE(%s, last_seen_at),
          started_at = COALESCE(%s, started_at),
          completed_at = COALESCE(%s, completed_at),
          certificate_issued_at = COALESCE(%s, certificate_issued_at)
        WHERE company_participant_id = %s
        """,
        (
            status,
            last_seen_at,
            started_at,
            completed_at,
            certificate_issued_at,
            str(row["company_participant_id"]),
        ),
    )
    _record_company_activity_tx(
        cur,
        str(row["company_id"]),
        "course_participant_status_synced",
        {
            "course_enrollment_id": enrollment_id,
            "status": status,
        },
        training_group_id=str(row["training_group_id"]) if row["training_group_id"] else None,
        company_participant_id=str(row["company_participant_id"]),
        course_enrollment_id=enrollment_id,
    )
    if row["training_group_id"]:
        _refresh_training_group_counts_tx(cur, str(row["training_group_id"]))


def _fetch_course_tx(cur, enrollment_id: str) -> dict[str, Any]:
    cur.execute(
        f"""
        SELECT
          enrollment_id,
          status,
          full_name,
          email::text AS email,
          organization_name,
          language,
          role,
          course_version,
          company_id,
          training_group_id,
          company_participant_id,
          enrollment_origin,
          optional_block_6_enabled,
          current_block_code,
          required_blocks_passed_count,
          required_course_completed,
          certificate_status,
          started_at,
          completed_at,
          last_seen_at,
          metadata
        FROM {_table_enrollments()}
        WHERE enrollment_id = %s
        """,
        (enrollment_id,),
    )
    row = cur.fetchone()
    if not row:
        raise CourseEnrollmentNotFoundError(f"Enrollment not found: {enrollment_id}")

    cur.execute(
        f"""
        SELECT
          block_code,
          passed,
          attempts_count,
          best_score,
          last_score,
          first_passed_at,
          updated_at
        FROM {_table_block_status()}
        WHERE enrollment_id = %s
        """,
        (enrollment_id,),
    )
    block_rows = cur.fetchall()
    blocks = {code: _default_block_state(code) for code in COURSE_BLOCK_CODES}
    for block_row in block_rows:
        blocks[block_row["block_code"]] = {
            "block_code": block_row["block_code"],
            "passed": block_row["passed"],
            "attempts_count": block_row["attempts_count"],
            "best_score": block_row["best_score"],
            "last_score": block_row["last_score"],
            "first_passed_at": (
                block_row["first_passed_at"].replace(microsecond=0).isoformat().replace("+00:00", "Z")
                if block_row["first_passed_at"]
                else None
            ),
            "updated_at": (
                block_row["updated_at"].replace(microsecond=0).isoformat().replace("+00:00", "Z")
                if block_row["updated_at"]
                else None
            ),
        }

    return {
        "enrollment_id": str(row["enrollment_id"]),
        "status": row["status"],
        "full_name": row["full_name"],
        "email": row["email"],
        "organization_name": row["organization_name"],
        "language": row["language"],
        "role": row["role"],
        "course_version": row["course_version"],
        "optional_block_6_enabled": row["optional_block_6_enabled"],
        "current_block_code": row["current_block_code"],
        "required_blocks_passed_count": row["required_blocks_passed_count"],
        "required_course_completed": row["required_course_completed"],
        "certificate_status": row["certificate_status"],
        "company_id": str(row["company_id"]) if row.get("company_id") else None,
        "training_group_id": str(row["training_group_id"]) if row.get("training_group_id") else None,
        "company_participant_id": str(row["company_participant_id"]) if row.get("company_participant_id") else None,
        "enrollment_origin": row["enrollment_origin"] if "enrollment_origin" in row else None,
        "started_at": (
            row["started_at"].replace(microsecond=0).isoformat().replace("+00:00", "Z")
            if row["started_at"]
            else None
        ),
        "completed_at": (
            row["completed_at"].replace(microsecond=0).isoformat().replace("+00:00", "Z")
            if row["completed_at"]
            else None
        ),
        "last_seen_at": (
            row["last_seen_at"].replace(microsecond=0).isoformat().replace("+00:00", "Z")
            if row["last_seen_at"]
            else None
        ),
        "identity_attestation": _build_identity_attestation(row["metadata"] or {}),
        "access_evidence": _build_access_evidence(
            row["metadata"] or {},
            row["completed_at"].replace(microsecond=0).isoformat().replace("+00:00", "Z")
            if row["completed_at"]
            else None,
        ),
        "certificate_artifact": _build_certificate_artifact(row["metadata"] or {}),
        "review_recommendation": _build_review_recommendation(blocks),
        "blocks": blocks,
    }


def _compute_required_passed_count_tx(cur, enrollment_id: str) -> int:
    cur.execute(
        f"""
        SELECT COUNT(*) AS passed_count
        FROM {_table_block_status()}
        WHERE enrollment_id = %s
          AND block_code = ANY(%s)
          AND passed = true
        """,
        (enrollment_id, list(REQUIRED_BLOCK_CODES)),
    )
    row = cur.fetchone()
    return int(row["passed_count"])


def create_course_enrollment(
    request: CourseEnrollmentCreateRequest, request_context: dict[str, Any] | None = None
) -> dict[str, Any]:
    request_context = request_context or {}
    now = _now_iso()
    client_ip = _sanitize_ip(request_context.get("client_ip"))
    user_agent = request.user_agent or request_context.get("user_agent")
    with connect_dict() as conn:
        with conn.cursor() as cur:
            invite = None
            effective_full_name = request.full_name
            effective_email = request.email
            effective_organization_name = request.organization_name
            effective_language = request.language
            effective_role = request.role
            company_id = None
            training_group_id = None
            company_participant_id = None
            enrollment_origin = "self_serve"

            if request.invite_token:
                invite = _fetch_company_invite_tx(cur, request.invite_token)
                if invite["course_enrollment_id"]:
                    return _fetch_course_tx(cur, invite["course_enrollment_id"])
                effective_full_name = invite["full_name"]
                effective_email = invite["email"]
                effective_organization_name = invite["organization_name"]
                effective_language = invite["language"]
                effective_role = invite["role"] or request.role
                company_id = invite["company_id"]
                training_group_id = invite["training_group_id"]
                company_participant_id = invite["company_participant_id"]
                enrollment_origin = "company_invite"
            else:
                cur.execute(
                    f"""
                    SELECT enrollment_id
                    FROM {_table_enrollments()}
                    WHERE course_version = %s AND email = %s AND company_participant_id IS NULL
                    """,
                    (request.course_version, request.email),
                )
                existing = cur.fetchone()
                if existing:
                    return _fetch_course_tx(cur, str(existing["enrollment_id"]))

            cur.execute(
                f"""
                INSERT INTO {_table_enrollments()} (
                  enrollment_id,
                  status,
                  full_name,
                  email,
                  organization_name,
                  language,
                  role,
                  course_version,
                  company_id,
                  training_group_id,
                  company_participant_id,
                  enrollment_origin,
                  optional_block_6_enabled,
                  source_path,
                  source_lead_id,
                  metadata
                )
                VALUES (%s, 'created', %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING enrollment_id
                """,
                (
                    str(uuid4()),
                    effective_full_name,
                    effective_email,
                    effective_organization_name,
                    effective_language,
                    effective_role,
                    request.course_version,
                    company_id,
                    training_group_id,
                    company_participant_id,
                    enrollment_origin,
                    request.optional_block_6_enabled,
                    request.source_path,
                    request.source_lead_id,
                    _jsonb(
                        {
                            "source_page": request.source_page,
                            "page_url": request.page_url,
                            "invite_token": request.invite_token,
                            "user_agent": user_agent,
                            "identity_confirmation": {
                                "accepted": request.identity_confirmation_accepted,
                                "accepted_at": now,
                                "text_version": request.identity_confirmation_text_version,
                                "accepted_from_ip": client_ip,
                                "accepted_user_agent": user_agent,
                            },
                            "first_access": {
                                "at": now,
                                "ip": client_ip,
                                "user_agent": user_agent,
                            },
                        }
                    ),
                ),
            )
            enrollment_row = cur.fetchone()
            enrollment_id = str(enrollment_row["enrollment_id"])
            if invite:
                _link_company_participant_to_enrollment_tx(
                    cur,
                    invite,
                    enrollment_id,
                    status="opened",
                    last_seen_at=now,
                )
            _record_activity_tx(
                cur,
                enrollment_id,
                "course_created",
                {
                    "source_page": request.source_page,
                    "source_path": request.source_path,
                    "invite_token": request.invite_token,
                    "enrollment_origin": enrollment_origin,
                    "optional_block_6_enabled": request.optional_block_6_enabled,
                },
            )
            return _fetch_course_tx(cur, enrollment_id)


def load_course_enrollment(enrollment_id: str) -> dict[str, Any]:
    with connect_dict() as conn:
        with conn.cursor() as cur:
            return _fetch_course_tx(cur, enrollment_id)


def record_course_block_attempt(
    enrollment_id: str,
    block_code: str,
    request: CourseBlockAttemptRequest,
) -> dict[str, Any]:
    _validate_block_code(block_code)
    now = _now_iso()

    with connect_dict() as conn:
        with conn.cursor() as cur:
            course = _fetch_course_tx(cur, enrollment_id)
            if block_code == "block_6" and not course.get("optional_block_6_enabled", False):
                raise ValueError("Optional block 6 is not enabled for this enrollment.")

            cur.execute(
                f"""
                INSERT INTO {_table_attempts()} (
                  attempt_id,
                  enrollment_id,
                  block_code,
                  attempt_number,
                  passed,
                  score,
                  questions_presented,
                  answers_submitted,
                  result_snapshot
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    str(uuid4()),
                    enrollment_id,
                    block_code,
                    request.attempt_number,
                    request.passed,
                    request.score,
                    _jsonb(request.questions_presented),
                    _jsonb(request.answers_submitted),
                    _jsonb(request.result_snapshot),
                ),
            )

            cur.execute(
                f"""
                INSERT INTO {_table_block_status()} (
                  block_status_id,
                  enrollment_id,
                  block_code,
                  passed,
                  attempts_count,
                  best_score,
                  last_score,
                  first_passed_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (enrollment_id, block_code)
                DO UPDATE SET
                  passed = ({_table_block_status()}.passed OR EXCLUDED.passed),
                  attempts_count = GREATEST({_table_block_status()}.attempts_count, EXCLUDED.attempts_count),
                  best_score = GREATEST(COALESCE({_table_block_status()}.best_score, 0), EXCLUDED.best_score),
                  last_score = EXCLUDED.last_score,
                  first_passed_at = COALESCE({_table_block_status()}.first_passed_at, EXCLUDED.first_passed_at)
                """,
                (
                    str(uuid4()),
                    enrollment_id,
                    block_code,
                    request.passed,
                    request.attempt_number,
                    request.score,
                    request.score,
                    now if request.passed else None,
                ),
            )

            required_passed_count = _compute_required_passed_count_tx(cur, enrollment_id)
            started_at = course.get("started_at") or now
            next_status = "completed" if course.get("required_course_completed") else "in_progress"

            cur.execute(
                f"""
                UPDATE {_table_enrollments()}
                SET
                  status = %s,
                  started_at = COALESCE(started_at, %s),
                  last_seen_at = %s,
                  current_block_code = %s,
                  required_blocks_passed_count = %s
                WHERE enrollment_id = %s
                """,
                (
                    next_status,
                    started_at,
                    now,
                    block_code,
                    required_passed_count,
                    enrollment_id,
                ),
            )
            _sync_company_participant_from_enrollment_tx(
                cur,
                enrollment_id,
                status="in_progress",
                last_seen_at=now,
                started_at=started_at,
            )

            _record_activity_tx(
                cur,
                enrollment_id,
                "block_attempt_submitted",
                {
                    "block_code": block_code,
                    "attempt_number": request.attempt_number,
                    "passed": request.passed,
                    "score": request.score,
                },
            )
            _record_activity_tx(
                cur,
                enrollment_id,
                "block_passed" if request.passed else "block_failed",
                {"block_code": block_code, "score": request.score},
            )
            return _fetch_course_tx(cur, enrollment_id)


def update_course_enrollment(enrollment_id: str, request: CourseEnrollmentUpdateRequest) -> dict[str, Any]:
    with connect_dict() as conn:
        with conn.cursor() as cur:
            course = _fetch_course_tx(cur, enrollment_id)
            fields: list[str] = []
            values: list[Any] = []
            changed: dict[str, Any] = {}

            if request.current_block_code is not None:
                fields.append("current_block_code = %s")
                values.append(request.current_block_code)
                changed["current_block_code"] = request.current_block_code
            if request.optional_block_6_enabled is not None:
                fields.append("optional_block_6_enabled = %s")
                values.append(request.optional_block_6_enabled)
                changed["optional_block_6_enabled"] = request.optional_block_6_enabled
            if request.last_seen_at is not None:
                fields.append("last_seen_at = %s")
                values.append(request.last_seen_at)
                changed["last_seen_at"] = request.last_seen_at
            if request.status is not None:
                fields.append("status = %s")
                values.append(request.status)
                changed["status"] = request.status
                if request.status == "in_progress" and course.get("started_at") is None:
                    fields.append("started_at = %s")
                    values.append(_now_iso())

            values.append(enrollment_id)
            cur.execute(
                f"""
                UPDATE {_table_enrollments()}
                SET {", ".join(fields)}
                WHERE enrollment_id = %s
                """,
                values,
            )
            if request.status == "in_progress" or request.last_seen_at is not None:
                _sync_company_participant_from_enrollment_tx(
                    cur,
                    enrollment_id,
                    status="in_progress" if request.status == "in_progress" else course.get("status") or "opened",
                    last_seen_at=request.last_seen_at or _now_iso(),
                    started_at=_now_iso() if request.status == "in_progress" and course.get("started_at") is None else None,
                )

            _record_activity_tx(
                cur,
                enrollment_id,
                "optional_block_enabled" if request.optional_block_6_enabled else "course_updated",
                changed,
            )
            return _fetch_course_tx(cur, enrollment_id)


@dataclass(frozen=True)
class CourseCompletionResult:
    course: dict[str, Any]
    completed_at: str
    certificate_status: str
    review_recommendation: dict[str, Any]


def complete_course_enrollment(
    enrollment_id: str, request_context: dict[str, Any] | None = None
) -> CourseCompletionResult:
    request_context = request_context or {}
    with connect_dict() as conn:
        with conn.cursor() as cur:
            course = _fetch_course_tx(cur, enrollment_id)
            if _required_blocks_passed_count(course.get("blocks", {})) < len(REQUIRED_BLOCK_CODES):
                raise CourseCompletionBlockedError("Required blocks are not all passed yet.")

            now = _now_iso()
            completed_at = course.get("completed_at") or now
            cur.execute(
                f"SELECT metadata FROM {_table_enrollments()} WHERE enrollment_id = %s",
                (enrollment_id,),
            )
            metadata_row = cur.fetchone()
            metadata = dict(metadata_row["metadata"] or {}) if metadata_row else {}
            metadata["completion_access"] = {
                "at": now,
                "ip": _sanitize_ip(request_context.get("client_ip")),
                "user_agent": request_context.get("user_agent"),
            }
            _, certificate_artifact_changed = _ensure_certificate_artifact(metadata, completed_at)
            cur.execute(
                f"""
                UPDATE {_table_enrollments()}
                SET
                  required_blocks_passed_count = %s,
                  required_course_completed = true,
                  completed_at = %s,
                  last_seen_at = %s,
                  status = 'completed',
                  certificate_status = 'queued',
                  started_at = COALESCE(started_at, %s),
                  metadata = %s
                WHERE enrollment_id = %s
                """,
                (
                    len(REQUIRED_BLOCK_CODES),
                    completed_at,
                    now,
                    now,
                    _jsonb(metadata),
                    enrollment_id,
                ),
            )
            _record_activity_tx(
                cur,
                enrollment_id,
                "course_completed",
                {
                    "completed_at": completed_at,
                    "review_recommendation": _build_review_recommendation(course.get("blocks", {})),
                },
            )
            if certificate_artifact_changed:
                _record_activity_tx(
                    cur,
                    enrollment_id,
                    "certificate_artifact_prepared",
                    metadata.get("certificate_artifact") or {},
                )
            _sync_company_participant_from_enrollment_tx(
                cur,
                enrollment_id,
                status="completed",
                last_seen_at=now,
                started_at=course.get("started_at") or now,
                completed_at=completed_at,
            )
            course = _fetch_course_tx(cur, enrollment_id)
            return CourseCompletionResult(
                course=course,
                completed_at=course["completed_at"],
                certificate_status=course["certificate_status"],
                review_recommendation=course["review_recommendation"],
            )
