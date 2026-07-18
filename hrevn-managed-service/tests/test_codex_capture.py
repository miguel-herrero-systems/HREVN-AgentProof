from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

from hrevn_managed_service.adapters.agentproof_adapter import canonical_json_bytes, verify_session_receipt
from hrevn_managed_service.agentproof.codex_capture import (
    build_file_change_events,
    capture_codex_session,
    parse_codex_jsonl,
    snapshot_repository,
)


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True)


def _init_repo(repo: Path) -> None:
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.email", "agentproof@example.invalid")
    _git(repo, "config", "user.name", "AgentProof Test")
    (repo / "demo.txt").write_text("before\n", encoding="utf-8")
    _git(repo, "add", "demo.txt")
    _git(repo, "commit", "-m", "baseline")


def test_parse_codex_jsonl_hashes_command_and_combined_output():
    lines = [
        json.dumps({"type": "thread.started", "thread_id": "codex-session-123"}),
        json.dumps(
            {
                "type": "item.completed",
                "item": {
                    "type": "command_execution",
                    "command": "/bin/sh -lc 'pytest -q'",
                    "aggregated_output": "2 passed\n",
                    "exit_code": 0,
                    "status": "completed",
                },
            }
        ),
    ]

    parsed = parse_codex_jsonl(lines, timestamp_factory=lambda: "2026-07-17T20:00:00Z")
    payload = parsed.event_inputs[0]["payload"]

    assert parsed.session_id == "codex-session-123"
    assert payload["command_sha256"] == hashlib.sha256(b"/bin/sh -lc 'pytest -q'").hexdigest()
    assert payload["output_capture_mode"] == "combined_stream"
    assert payload["output_sha256"] == hashlib.sha256(b"2 passed\n").hexdigest()
    assert "pytest" not in json.dumps(payload)
    assert "2 passed" not in json.dumps(payload)


def test_file_change_event_hashes_real_unified_diff(tmp_path):
    repo = tmp_path / "repo"
    _init_repo(repo)
    before = snapshot_repository(repo)
    (repo / "demo.txt").write_text("after\n", encoding="utf-8")
    after = snapshot_repository(repo)

    events = build_file_change_events(before, after, occurred_at="2026-07-17T20:01:00Z")
    payload = events[0]["payload"]

    assert payload["path"] == "demo.txt"
    assert payload["change_type"] == "modified"
    assert payload["before_sha256"] == hashlib.sha256(b"before\n").hexdigest()
    assert payload["after_sha256"] == hashlib.sha256(b"after\n").hexdigest()
    assert payload["diff_format"] == "unified_diff_v1"
    assert len(payload["diff_sha256"]) == 64
    assert b"before\n" not in canonical_json_bytes(payload)
    assert b"after\n" not in canonical_json_bytes(payload)


def test_snapshot_ignores_runtime_caches(tmp_path):
    repo = tmp_path / "repo"
    _init_repo(repo)
    cache_dir = repo / "__pycache__"
    cache_dir.mkdir()
    (cache_dir / "demo.cpython-314.pyc").write_bytes(b"generated-bytecode")

    snapshot = snapshot_repository(repo)

    assert "demo.txt" in snapshot
    assert not any("__pycache__" in path for path in snapshot)


def test_capture_codex_session_with_fake_json_stream(tmp_path):
    repo = tmp_path / "repo"
    _init_repo(repo)
    fake_codex = tmp_path / "fake_codex.py"
    fake_codex.write_text(
        """from pathlib import Path
import json

Path('demo.txt').write_text('after\\n', encoding='utf-8')
events = [
    {'type': 'thread.started', 'thread_id': 'codex-live-demo-001'},
    {
        'type': 'item.completed',
        'item': {
            'type': 'command_execution',
            'command': \"/bin/sh -lc 'apply fix'\",
            'aggregated_output': 'ok\\n',
            'exit_code': 0,
            'status': 'completed',
        },
    },
]
for event in events:
    print(json.dumps(event), flush=True)
""",
        encoding="utf-8",
    )
    output = tmp_path / "agent-session.json"

    receipt = capture_codex_session(
        repo=repo,
        prompt="Fix the demo file",
        output_path=output,
        model="gpt-test",
        codex_command=(sys.executable, str(fake_codex)),
    )

    assert output.read_bytes().endswith(b"}")
    assert not output.read_bytes().endswith(b"\n")
    assert receipt["session_id"] == "codex-live-demo-001"
    assert receipt["event_count"] == 2
    assert [event["event_type"] for event in receipt["events"]] == ["command", "file_change"]
    assert verify_session_receipt(receipt)["valid"] is True
    serialized = output.read_text(encoding="utf-8")
    assert "Fix the demo file" not in serialized
    assert "apply fix" not in serialized
    assert "ok\\n" not in serialized
