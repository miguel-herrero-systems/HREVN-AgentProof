from __future__ import annotations

import difflib
import hashlib
import json
import subprocess
import sys
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Iterable, Sequence

from ..adapters.agentproof_adapter import build_session_receipt, canonical_json_bytes


MAX_SNAPSHOT_FILE_BYTES = 20 * 1024 * 1024
MAX_SNAPSHOT_TOTAL_BYTES = 100 * 1024 * 1024
_IGNORED_PREFIXES = (".agentproof/", ".git/")
_IGNORED_PATH_PARTS = {".mypy_cache", ".pytest_cache", ".ruff_cache", ".venv", "__pycache__", "node_modules", "venv"}
_IGNORED_SUFFIXES = {".pyc", ".pyo"}


class CodexCaptureError(RuntimeError):
    pass


@dataclass
class ParsedCodexStream:
    session_id: str | None = None
    event_inputs: list[dict[str, Any]] = field(default_factory=list)
    final_message: str | None = None


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _run_git(repo: Path, *args: str, allow_failure: bool = False) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if result.returncode != 0 and not allow_failure:
        raise CodexCaptureError(f"git_failed:{args[0] if args else 'unknown'}")
    return result.stdout.strip()


def resolve_repository_root(repo: Path) -> Path:
    root = _run_git(repo.resolve(), "rev-parse", "--show-toplevel")
    if not root:
        raise CodexCaptureError("git_repository_required")
    return Path(root).resolve()


def repository_id(repo: Path) -> str:
    origin = _run_git(repo, "config", "--get", "remote.origin.url", allow_failure=True)
    identity_material = origin or str(repo)
    return f"sha256:{_sha256(identity_material.encode('utf-8'))}"


def snapshot_repository(repo: Path) -> dict[str, bytes]:
    result = subprocess.run(
        ["git", "-C", str(repo), "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if result.returncode != 0:
        raise CodexCaptureError("git_failed:ls-files")

    snapshot: dict[str, bytes] = {}
    total_bytes = 0
    for raw_path in sorted(set(result.stdout.split(b"\0"))):
        if not raw_path:
            continue
        try:
            relative_path = raw_path.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise CodexCaptureError("non_utf8_repository_path") from exc
        posix_path = PurePosixPath(relative_path)
        if posix_path.is_absolute() or ".." in posix_path.parts:
            raise CodexCaptureError("unsafe_repository_path")
        if (
            relative_path.startswith(_IGNORED_PREFIXES)
            or any(part in _IGNORED_PATH_PARTS for part in posix_path.parts)
            or posix_path.suffix in _IGNORED_SUFFIXES
        ):
            continue

        full_path = (repo / relative_path).resolve()
        try:
            full_path.relative_to(repo)
        except ValueError as exc:
            raise CodexCaptureError("repository_path_escape") from exc
        if not full_path.is_file():
            continue

        size = full_path.stat().st_size
        if size > MAX_SNAPSHOT_FILE_BYTES:
            raise CodexCaptureError(f"snapshot_file_too_large:{relative_path}")
        total_bytes += size
        if total_bytes > MAX_SNAPSHOT_TOTAL_BYTES:
            raise CodexCaptureError("snapshot_total_too_large")
        snapshot[relative_path] = full_path.read_bytes()
    return snapshot


def _diff_bytes(path: str, before: bytes | None, after: bytes | None) -> tuple[str, bytes]:
    before_value = before or b""
    after_value = after or b""
    try:
        before_text = before_value.decode("utf-8").splitlines(keepends=True)
        after_text = after_value.decode("utf-8").splitlines(keepends=True)
    except UnicodeDecodeError:
        commitment = canonical_json_bytes(
            {
                "format": "HREVN_BINARY_TRANSITION_V1",
                "path": path,
                "before_sha256": _sha256(before_value) if before is not None else None,
                "after_sha256": _sha256(after_value) if after is not None else None,
            }
        )
        return "binary_transition_v1", commitment

    diff = "".join(
        difflib.unified_diff(
            before_text,
            after_text,
            fromfile=f"a/{path}" if before is not None else "/dev/null",
            tofile=f"b/{path}" if after is not None else "/dev/null",
            lineterm="\n",
        )
    ).encode("utf-8")
    return "unified_diff_v1", diff


def build_file_change_events(
    before_snapshot: dict[str, bytes],
    after_snapshot: dict[str, bytes],
    *,
    occurred_at: str,
) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for path in sorted(set(before_snapshot) | set(after_snapshot)):
        before = before_snapshot.get(path)
        after = after_snapshot.get(path)
        if before == after:
            continue
        if before is None:
            change_type = "created"
        elif after is None:
            change_type = "deleted"
        else:
            change_type = "modified"
        diff_format, diff = _diff_bytes(path, before, after)
        events.append(
            {
                "event_type": "file_change",
                "occurred_at": occurred_at,
                "payload": {
                    "path": path,
                    "change_type": change_type,
                    "before_sha256": _sha256(before) if before is not None else None,
                    "after_sha256": _sha256(after) if after is not None else None,
                    "diff_sha256": _sha256(diff),
                    "diff_format": diff_format,
                },
            }
        )
    return events


def parse_codex_jsonl(
    lines: Iterable[str],
    *,
    timestamp_factory: Callable[[], str] = _utc_now,
    on_item: Callable[[dict[str, Any]], None] | None = None,
) -> ParsedCodexStream:
    parsed = ParsedCodexStream()
    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError as exc:
            raise CodexCaptureError(f"invalid_codex_jsonl:{line_number}") from exc
        if on_item:
            on_item(event)

        event_type = event.get("type")
        if event_type == "thread.started":
            parsed.session_id = str(event.get("thread_id") or "").strip() or None
            continue
        if event_type != "item.completed":
            continue
        item = event.get("item")
        if not isinstance(item, dict):
            continue
        if item.get("type") == "command_execution":
            command = str(item.get("command") or "")
            output = str(item.get("aggregated_output") or "")
            exit_code = item.get("exit_code")
            if not command or not isinstance(exit_code, int):
                continue
            parsed.event_inputs.append(
                {
                    "event_type": "command",
                    "occurred_at": timestamp_factory(),
                    "payload": {
                        "command_class": "shell",
                        "command_sha256": _sha256(command.encode("utf-8")),
                        "output_capture_mode": "combined_stream",
                        "output_sha256": _sha256(output.encode("utf-8")),
                        "exit_code": exit_code,
                    },
                }
            )
        elif item.get("type") == "agent_message":
            parsed.final_message = str(item.get("text") or "") or None
    return parsed


def capture_codex_session(
    *,
    repo: Path,
    prompt: str,
    output_path: Path,
    model: str | None = None,
    sandbox: str = "workspace-write",
    approval_policy: str = "never",
    codex_command: Sequence[str] = ("codex",),
    on_item: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    if not prompt.strip():
        raise CodexCaptureError("prompt_required")
    if not model or not model.strip():
        raise CodexCaptureError("model_required_for_receipt")
    repo_root = resolve_repository_root(repo)
    before_snapshot = snapshot_repository(repo_root)
    started_at = _utc_now()
    base_commit = _run_git(repo_root, "rev-parse", "HEAD")

    command = [*codex_command, "-a", approval_policy]
    if model:
        command.extend(["-m", model])
    command.extend(["exec", "--sandbox", sandbox, "--json", "-C", str(repo_root), "-"])

    process = subprocess.Popen(
        command,
        cwd=repo_root,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
    )
    assert process.stdin is not None
    assert process.stdout is not None
    assert process.stderr is not None

    def drain_stderr() -> None:
        for line in process.stderr:
            sys.stderr.write(line)

    stderr_thread = threading.Thread(
        target=drain_stderr,
        name="agentproof-codex-stderr",
        daemon=True,
    )
    stderr_thread.start()
    try:
        process.stdin.write(prompt)
        process.stdin.close()
        parsed = parse_codex_jsonl(process.stdout, on_item=on_item)
        return_code = process.wait()
    except BaseException:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        raise
    finally:
        stderr_thread.join(timeout=5)
    if return_code != 0:
        raise CodexCaptureError(f"codex_exec_failed:{return_code}")
    if not parsed.session_id:
        raise CodexCaptureError("codex_session_id_missing")

    ended_at = _utc_now()
    after_snapshot = snapshot_repository(repo_root)
    parsed.event_inputs.extend(
        build_file_change_events(before_snapshot, after_snapshot, occurred_at=ended_at)
    )
    head_commit = _run_git(repo_root, "rev-parse", "HEAD")
    receipt = build_session_receipt(
        {
            "session_id": parsed.session_id,
            "agent_name": "Codex CLI",
            "model": model,
            "repository_id": repository_id(repo_root),
            "base_commit": base_commit,
            "head_commit": head_commit,
            "started_at": started_at,
            "ended_at": ended_at,
        },
        parsed.event_inputs,
    )

    destination = output_path.expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    temporary.write_bytes(canonical_json_bytes(receipt))
    temporary.replace(destination)
    return receipt
