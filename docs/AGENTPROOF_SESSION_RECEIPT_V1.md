# AgentProof Codex Session Receipt v1

This document describes the AgentProof semantic layer carried as the authoritative `documents/agent-session.json` file inside an HREVN EB1 bundle.

## Evidence boundary

The public receipt contains repository-relative paths and SHA-256 digests. It does not contain source code, command text, prompts, diffs, stdout, or stderr. The receipt proves that the instrumented event log has not changed after sealing; it does not claim that an untrusted collector observed every possible action.

Codex CLI capture uses the documented `codex exec --json` event stream. When a command event exposes one aggregated output stream rather than separate stdout and stderr, the payload declares `output_capture_mode: combined_stream` and commits that stream as `output_sha256`; it does not claim that the streams were separated.

## Canonical JSON

The normative rules live in the `agentproof_codex_session_v1` entry in `PROFILE_CONTRACTS`:

- UTF-8 encoding and Unicode NFC normalization.
- Object keys sorted by ascending Unicode code point.
- Array order preserved.
- `,` and `:` separators with no optional whitespace.
- No trailing newline.
- Integers are the only JSON number type; floating-point values are rejected.
- Booleans and null retain normal JSON representation.

These rules are named `HREVN_CANONICAL_JSON_V1`.

## Event hash chain

Events start at sequence 1. The first event uses 64 zeroes as `previous_event_hash`. Every subsequent event uses the prior event's declared `event_hash`.

For each event:

1. Build the event object with `sequence`, `event_type`, `occurred_at`, `previous_event_hash`, and `payload`.
2. Serialize that object with `HREVN_CANONICAL_JSON_V1`.
3. Compute SHA-256 over the exact serialized bytes.
4. Store the lowercase hexadecimal result as `event_hash`.

`event_hash` itself is excluded from its own hash scope. The receipt declares `event_count` and `chain_head_sha256`; both are checked during semantic verification. Altering, deleting, inserting, or reordering an event therefore invalidates the receipt.

## EB1 composition

The exact canonical bytes of `agent-session.json` are an authoritative EB1 document with role `agent_session_trace`. The existing EB1 core hashes those bytes into its evidentiary root, signs that root with Ed25519, and may anchor it on Sepolia. AgentProof does not change the EB1 root algorithm.

## Capture and seal

Run an instrumented Codex CLI task and write its canonical receipt:

```bash
hrevn-agentproof run \
  --repo /path/to/repository \
  --output /path/to/agent-session.json \
  --model gpt-5.6-sol \
  "Fix the failing test and verify the change"
```

Seal that exact receipt through the existing HREVN EB1 API:

```bash
export HREVN_API_KEY="..."
hrevn-agentproof seal \
  --receipt /path/to/agent-session.json \
  --api-url https://api.hrevn.com
```

`seal` rejects a receipt whose bytes are not canonical or whose internal hash chain is invalid. It also treats an unsigned or unanchored response as a failure by default. `--allow-pending` exists only for local environments where signing or real Sepolia anchoring is intentionally disabled. API credentials are read from the environment and are never placed in the receipt or request body.
