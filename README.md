# HREVN AgentProof

**Cryptographically verifiable receipts for Codex agent sessions.**

[Live demo](https://agentproof.hrevn.com/) | [Sepolia transaction](https://sepolia.etherscan.io/tx/0x19a05ed31231e67388cda6513d18d72e5bafa38b1b6634fc772da6ba9d7308f3) | [Download the live EB1 bundle](https://agentproof.hrevn.com/api/v1/public/bundles/BND-A461FE81F6B2/download)

AgentProof turns an observed Codex session into a tamper-evident receipt. It commits each captured command and file change in sequence, seals the canonical trace inside an HREVN Evidence Bundle (EB1), signs the EB1 root with Ed25519, and anchors that root on Ethereum Sepolia.

The public verifier shows what was committed without publishing prompts, source code, command output, or diffs. It can then hash a repository locally in the browser and identify the exact committed file that changed after the session.

## Five-minute demo

1. Open the [live verifier](https://agentproof.hrevn.com/). The real bundle `BND-A461FE81F6B2` verifies its hash chain, Ed25519 signature, and Sepolia anchor.
2. Download the tiny demo repository from the verifier.
3. Select its folder. `calculator.py` reports **MATCH** in green.
4. Change `left + right` to `left - right` and select the folder again.
5. The same sealed receipt reports **MISMATCH** in red and identifies `calculator.py`.

Repository files never leave the browser during this comparison.

## What the receipt proves

- **Integrity:** changing a captured event invalidates the event hash chain and the EB1 root.
- **Order:** every event commits the previous event hash, so deletion, insertion, and reordering are detectable.
- **Authorship of the sealed root:** the EB1 root carries a verifiable Ed25519 signature.
- **Public timestamp evidence:** the same root is anchored in a public Sepolia transaction.
- **Repository drift:** a third party can compare current files with the final file commitments and locate a modified or missing file.

AgentProof is deliberately described as **tamper-evident, not exhaustive**. It proves the integrity of the events observed by the instrumented collector. It does not claim to observe actions that bypass that collector, and it is not a compliance certification.

## Architecture

```text
Codex CLI (`codex exec --json`)
        |
        v
AgentProof capture adapter
  - hashes commands and combined output
  - hashes files before and after
  - hashes unified diffs
  - builds an internal event hash chain
        |
        v
Canonical `agent-session.json`
  - UTF-8 + NFC
  - sorted object keys
  - no optional whitespace or trailing newline
        |
        v
Existing HREVN EB1 core
  - authoritative document checksum
  - EB1 root
  - Ed25519 signature
  - Sepolia anchor
        |
        v
Public verifier
  - verifies the sealed receipt
  - re-hashes selected repository files on-device
  - reports MATCH / MISMATCH by path
```

The session trace is an authoritative EB1 document with role `agent_session_trace`. AgentProof adds an adapter and a semantic profile; it does not duplicate or change the EB1 root algorithm.

## Privacy boundary

The public receipt includes:

- Repository-relative file paths.
- SHA-256 commitments for commands, output, file states, and diffs.
- Exit codes, timestamps, event types, and sequence links.
- Agent/model identifiers and Git commit identifiers.

It does **not** include prompt text, command text, stdout/stderr content, source code, or diff content. The live verifier also processes selected repository files locally with the Web Crypto API and does not upload them.

## Run locally

### Requirements

- Python 3.10 or newer.
- Git.
- Codex CLI installed and authenticated for live capture.
- A modern browser with directory-upload support for the live verifier (tested in Chrome). The CLI verification path does not require a browser.

### Install

```bash
cd hrevn-managed-service
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

### Run the focused tests

```bash
pytest -q \
  tests/test_agentproof_adapter.py \
  tests/test_agentproof_seal.py \
  tests/test_agentproof_verification.py \
  tests/test_codex_capture.py \
  tests/test_eb1_profile_registry.py
```

### Verify the included receipt without Codex

The repository includes the canonical receipt sealed in the live bundle and the matching one-file demo repository. After installation, this check takes a few seconds and requires no Codex account, HREVN credential, or network access:

```bash
hrevn-agentproof verify-repo \
  --receipt examples/agent-session.json \
  --repo examples/demo-repository
```

The result is `MATCH`. Change `left + right` to `left - right` in `examples/demo-repository/calculator.py` and run the same command again. It returns `MISMATCH`, identifies `calculator.py`, and exits non-zero. Restore the file before running the green case again.

See [`examples/README.md`](examples/README.md) for the provenance and privacy boundary of this sample.

### Capture a real Codex session

The target must be a Git repository with at least one commit.

```bash
hrevn-agentproof run \
  --repo /path/to/git/repository \
  --output /tmp/agent-session.json \
  --model gpt-5.6-sol \
  "Fix the failing test and verify the change"
```

The command invokes the real Codex CLI JSON event stream, records privacy-preserving commitments, snapshots the repository before and after, and writes canonical JSON.

### Re-verify repository state

```bash
hrevn-agentproof verify-repo \
  --receipt /tmp/agent-session.json \
  --repo /path/to/git/repository
```

A match exits successfully. A modified or missing committed file returns `MISMATCH`, lists the exact path, and exits non-zero.

### Seal through an EB1 service

Sealing requires an authorized HREVN EB1 API. Credentials are read only from the environment and are never included in the receipt or request body.

```bash
export HREVN_API_KEY="your-issued-key"
hrevn-agentproof seal \
  --receipt /tmp/agent-session.json \
  --api-url https://your-eb1-api.example
```

By default, `seal` rejects unsigned or unanchored output. `--allow-pending` is available only for local environments intentionally running without signing or real anchoring.

## Build Week boundary

AgentProof extends infrastructure that existed before OpenAI Build Week 2026. The imported baseline is tagged `pre-agentproof-buildweek`.

| Pre-existing HREVN | Built for AgentProof during Build Week |
| --- | --- |
| EB1 bundle generation and root algorithm | `agentproof_codex_session_v1` profile and contract |
| Ed25519 signing | Canonical privacy-preserving session receipt |
| Blockchain anchor service | Internal per-event SHA-256 hash chain |
| Generic EB1 verification | Real Codex CLI JSON-stream capture |
| Managed API foundation | Before/after file and unified-diff commitments |
|  | Repository re-verification with exact mismatch paths |
|  | AgentProof public API adapter and mobile verifier |

Review the complete Build Week change with:

```bash
git diff pre-agentproof-buildweek..HEAD
```

No production secrets, private keys, runtime storage, generated bundles, or deployment configuration are included in the public submission repository.

## Built with Codex and GPT-5.6

Codex is both the subject of the receipt and the primary development environment used to build AgentProof.

- Primary Codex build thread: `019e08ca-0b43-7192-b53c-a7c811171186`.
- Sealed Codex CLI demo session: `019f71f9-9e66-7392-a907-a54091483632`.
- Demo model recorded in the receipt: `gpt-5.6-sol`.
- The implementation, tests, production deployment, verifier, and green/red acceptance run were executed collaboratively through Codex.

The sealed demo session contains five events: four command commitments and one committed change to `calculator.py`. Its EB1 root is signed and anchored at Sepolia block `11295099`.

## Key files

- `hrevn-managed-service/src/hrevn_managed_service/agentproof/codex_capture.py`: Codex JSON-stream capture and repository snapshots.
- `hrevn-managed-service/src/hrevn_managed_service/adapters/agentproof_adapter.py`: canonical receipt and event-chain validation.
- `hrevn-managed-service/src/hrevn_managed_service/agentproof/seal.py`: EB1 sealing client and signed/anchored response checks.
- `hrevn-managed-service/src/hrevn_managed_service/agentproof/repository_verify.py`: exact repository-state comparison.
- `hrevn-managed-service/src/hrevn_managed_service/api/agentproof.py`: privacy-safe public receipt endpoint.
- `agentproof-site/`: public verifier and on-device green/red comparison.
- `docs/AGENTPROOF_SESSION_RECEIPT_V1.md`: receipt format and canonicalization specification.

## License

This Build Week snapshot is licensed under the [Apache License 2.0](LICENSE). HREVN and AgentProof names and marks are not granted by that license.
